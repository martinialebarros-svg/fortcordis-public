from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_any_papel, require_papel
from app.db.database import get_db
from app.models.configuracao import Configuracao
from app.models.user import User
from app.models.clinica import Clinica
from app.models.whatsapp_bot import (
    WhatsAppBotClinicaEstado,
    WhatsAppBotConversaEstado,
    WhatsAppBotJob,
    WhatsAppBotResposta,
)
from app.services.whatsapp_bot_gates import (
    MODOS_VALIDOS,
    _assisted_send_pause_hours,
    is_locally_paused,
    is_whatsapp_bot_enabled,
    pause_conversation,
    resolve_conversation_mode,
    resolve_conversation_state,
    resolve_participacao,
)
from app.services.whatsapp_bot_readiness_service import coletar_prontidao
from app.services.whatsapp_bot_metrics_service import (
    JANELA_PADRAO_DIAS,
    coletar_metricas_observacao,
)
from app.services.auditoria_service import registrar_auditoria

router = APIRouter()

_WHATSAPP_BOT_PAPEIS = ("admin", "recepcao", "veterinario", "cardiologista")

# Supressoes que o atendente PRECISA ver. `suppressed` inteiro viraria ruido
# permanente - `bot_desabilitado` apareceria em toda conversa com o kill switch
# desligado, `modo_off` e redundante com `modo` no mesmo payload, e
# `sem_pergunta` (cortesia, RF-P11) alertar inverteria a intencao da regra.
# Estes quatro sao acionaveis: explicam um silencio que, sem explicacao, parece
# bot quebrado - foi exatamente o que aconteceu em producao em 2026-08-25.
_SUPRESSOES_VISIVEIS = ("pausado", "janela_fechada", "teto_diario", "conversa_divergente", "contexto_alterado")


class WhatsAppBotConversaEstadoUpdateRequest(BaseModel):
    modo: Optional[str] = Field(default=None)
    pausar: Optional[bool] = Field(
        default=None,
        description=(
            "true pausa a conversa por WHATSAPP_BOT_HANDOFF_PAUSE_HOURS; "
            "false limpa a pausa vigente (RF-030)."
        ),
    )


class WhatsAppBotRespostaEnviarRequest(BaseModel):
    texto: Optional[str] = Field(
        default=None,
        max_length=900,
        description="Texto editado pelo atendente; ausente usa o rascunho original.",
    )


def _node_client_config() -> tuple[str, dict[str, str], int]:
    base_url = str(settings.WHATSAPP_AGENDA_SERVICE_URL or "").strip().rstrip("/")
    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "").strip()
    timeout = max(1, int(settings.WHATSAPP_AGENDA_TIMEOUT_SECONDS or 15))
    if not base_url or not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviço interno do WhatsApp não configurado.",
        )
    return base_url, {"x-whatsapp-internal-token": token}, timeout


def _reset_sending_to_draft(db: Session, resposta_id: int) -> None:
    resposta = db.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.id == resposta_id).first()
    if resposta is not None and resposta.decisao == "sending":
        resposta.decisao = "draft"
        resposta.enviado_por_id = None
        db.commit()


def _sent_payload(resposta: WhatsAppBotResposta, *, idempotent: bool) -> dict:
    return {
        "resposta_id": resposta.id,
        "status": "sent",
        "idempotent": idempotent,
        "texto_enviado": resposta.texto_enviado,
    }


def _estado_payload(db: Session, wa_identity: str) -> dict:
    estado = resolve_conversation_state(db, wa_identity)
    modo = resolve_conversation_mode(db, wa_identity, estado=estado)
    rascunho = (
        db.query(WhatsAppBotResposta)
        .filter(
            WhatsAppBotResposta.wa_identity == wa_identity,
            WhatsAppBotResposta.decisao == "draft",
            WhatsAppBotResposta.feedback.is_(None),
        )
        .order_by(WhatsAppBotResposta.id.desc())
        .first()
    )

    # RF-022: bloqueio nunca vira silencio. Ate aqui a central so mostrava
    # `draft`, entao `blocked` e `handoff` eram invisiveis: o bot recusava
    # responder e ninguem ficava sabendo. Olhamos a ULTIMA resposta da conversa
    # em vez de "a ultima recusa" para nao ressuscitar um bloqueio velho que ja
    # foi superado por um rascunho ou por um envio.
    ultima = (
        db.query(WhatsAppBotResposta)
        .filter(WhatsAppBotResposta.wa_identity == wa_identity)
        .order_by(WhatsAppBotResposta.id.desc())
        .first()
    )
    recusa = ultima if ultima is not None and ultima.decisao in ("blocked", "handoff") else None
    # `suppressed` nao era so invisivel: por a regra ser "a ULTIMA linha", uma
    # supressao posterior APAGAVA o aviso de blocked/handoff anterior, deixando
    # a central em branco. Derivar o silencio da mesma linha conserta os dois
    # problemas de uma vez, e sem query nova - `ultima` ja esta carregada.
    silencio = (
        ultima
        if ultima is not None
        and ultima.decisao == "suppressed"
        and str(ultima.motivo or "") in _SUPRESSOES_VISIVEIS
        else None
    )
    from app.services.whatsapp_bot_generation import _resolver_contexto, _escopo_da_persona
    from app.services.whatsapp_bot_agendamento import carregar, resumo
    ultima_clinica = db.query(WhatsAppBotResposta).filter(
        WhatsAppBotResposta.wa_identity == wa_identity,
        WhatsAppBotResposta.clinica_id.is_not(None),
    ).order_by(WhatsAppBotResposta.id.desc()).first()
    coleta = carregar(db, wa_identity, ultima_clinica.clinica_id) if ultima_clinica else None
    from app.services.whatsapp_bot_fila import ultimo as ultimo_pedido, LABELS
    pedido = ultimo_pedido(db, wa_identity, ultima_clinica.clinica_id) if ultima_clinica else None
    if coleta or pedido:
        contexto = _resolver_contexto(db, wa_identity)
        _, _, clinic_id = _escopo_da_persona(contexto) if contexto.get("resolution") == "matched" else (None, None, None)
        if coleta and coleta.get("clinica_id") != clinic_id:
            coleta = None
        if pedido and pedido.clinica_id != clinic_id:
            pedido = None
    acompanhamento = ({"status":"acompanhamento", "resumo":pedido.resumo,
        "status_equipe":LABELS[pedido.status], "preferencia_recebida_em":None}
        if pedido and (not coleta or coleta.get("status") not in ("coletando", "aguardando_confirmacao")) else None)
    return {
        "solicitacao_agendamento": acompanhamento or ({"status": coleta["status"], "resumo": resumo(coleta), "preferencia_recebida_em": coleta.get("preferencia_recebida_em")} if coleta else None),
        "wa_identity": wa_identity,
        "envio_automatico_liberado": settings.WHATSAPP_BOT_AUTO_SEND_ENABLED,
        "modo": modo,
        "modo_origem": "conversa" if estado is not None and estado.modo else "institucional",
        "pausado_ate": estado.pausado_ate.isoformat() if estado and estado.pausado_ate else None,
        "pausado": is_locally_paused(estado),
        "handoff_motivo": estado.handoff_motivo if estado else None,
        "rascunho_pendente": (
            {
                "resposta_id": rascunho.id,
                "texto_gerado": rascunho.texto_gerado,
                "criado_em": rascunho.created_at.isoformat() if rascunho.created_at else None,
            }
            if rascunho is not None
            else None
        ),
        # Sem `texto_gerado` de proposito. Em `blocked` o texto e justamente o
        # que o guardrail recusou - diagnostico, dose, valor sem fonte - e
        # coloca-lo no payload o deixa a um copiar-colar de ser enviado ao
        # cliente. O atendente precisa saber QUE o bot recusou e POR QUE, nao
        # receber a frase proibida de volta.
        "ultima_recusa": (
            {
                "resposta_id": recusa.id,
                "decisao": recusa.decisao,
                "motivo": recusa.motivo,
                "aviso_enviado": bool(recusa.texto_enviado),
                "criado_em": recusa.created_at.isoformat() if recusa.created_at else None,
            }
            if recusa is not None
            else None
        ),
        # Irma de `ultima_recusa`, para o silencio deixar de ser ausencia de
        # dado. Sem `decisao` (e sempre "suppressed") e sem `texto_gerado`
        # (linha suprimida nunca grava texto).
        "ultimo_silencio": (
            {
                "resposta_id": silencio.id,
                "motivo": silencio.motivo,
                "criado_em": silencio.created_at.isoformat() if silencio.created_at else None,
            }
            if silencio is not None
            else None
        ),
    }


@router.get("/conversas/{wa_identity}/estado")
def get_conversa_estado(
    wa_identity: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    del current_user
    return _estado_payload(db, wa_identity)


@router.patch("/conversas/{wa_identity}/estado")
def atualizar_conversa_estado(
    wa_identity: str,
    payload: WhatsAppBotConversaEstadoUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """RF-030: por conversa, a central permite alternar `auto`/`suggest`/`off`

    e pausar o bot - sem exigir papel de admin (esse e o controle operacional
    do dia a dia; o toggle institucional em Configuracoes e que e admin-only).
    """
    if payload.modo is not None:
        modo_normalizado = payload.modo.strip().lower()
        if modo_normalizado not in MODOS_VALIDOS:
            raise HTTPException(
                status_code=422, detail="modo deve ser 'off', 'suggest' ou 'auto'."
            )
        estado = resolve_conversation_state(db, wa_identity)
        if estado is None:
            estado = WhatsAppBotConversaEstado(wa_identity=wa_identity)
            db.add(estado)
        estado.modo = modo_normalizado
        estado.atualizado_por_id = current_user.id

    if payload.pausar is True:
        pause_conversation(db, wa_identity, atualizado_por_id=current_user.id)
    elif payload.pausar is False:
        estado = resolve_conversation_state(db, wa_identity)
        if estado is not None:
            estado.pausado_ate = None
            estado.atualizado_por_id = current_user.id

    db.commit()
    return _estado_payload(db, wa_identity)


@router.post("/respostas/{resposta_id}/enviar")
def enviar_rascunho(
    resposta_id: int,
    payload: WhatsAppBotRespostaEnviarRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """RF-028: envia uma única vez o rascunho revisado pelo atendente.

    A transição condicional `draft -> sending` fecha a corrida entre dois
    cliques/processos. Repetir depois de `sent` é idempotente e não chama o
    serviço Node novamente.
    """
    resposta = db.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.id == resposta_id).first()
    if resposta is None:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado.")
    if resposta.decisao == "sent" and resposta.texto_enviado:
        return _sent_payload(resposta, idempotent=True)
    if resposta.decisao != "draft" or resposta.feedback is not None:
        raise HTTPException(status_code=409, detail="Rascunho não está mais disponível.")

    texto = resposta.texto_gerado if payload.texto is None else payload.texto
    texto = str(texto or "").strip()
    if not texto:
        raise HTTPException(status_code=422, detail="O texto do rascunho não pode ficar vazio.")
    if len(texto) > int(settings.WHATSAPP_BOT_MAX_REPLY_CHARS or 900):
        raise HTTPException(status_code=422, detail="O texto excede o limite configurado do bot.")

    base_url, headers, timeout = _node_client_config()

    claimed = (
        db.query(WhatsAppBotResposta)
        .filter(
            WhatsAppBotResposta.id == resposta_id,
            WhatsAppBotResposta.decisao == "draft",
            WhatsAppBotResposta.feedback.is_(None),
            WhatsAppBotResposta.enviado_por_id.is_(None),
        )
        .update(
            {"decisao": "sending", "enviado_por_id": current_user.id},
            synchronize_session=False,
        )
    )
    db.commit()
    if claimed != 1:
        db.expire_all()
        atual = db.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.id == resposta_id).first()
        if atual is not None and atual.decisao == "sent" and atual.texto_enviado:
            return _sent_payload(atual, idempotent=True)
        raise HTTPException(status_code=409, detail="Rascunho já está sendo processado.")

    from app.services.whatsapp_contexto_selecao_service import lock_contexto, resposta_contexto_vigente
    lock_contexto(db, resposta.wa_identity)
    if not resposta_contexto_vigente(db, resposta):
        resposta.decisao = "suppressed"
        resposta.motivo = "contexto_alterado"
        resposta.enviado_por_id = None
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="O cadastro usado neste rascunho mudou. Solicite uma nova mensagem antes de responder com o bot.",
        )

    node_idempotent = False
    try:
        node_response = httpx.post(
            f"{base_url}/conversations/{resposta.conversation_id}/messages",
            headers=headers,
            json={
                "body": texto,
                "type": "text",
                "metadata": {
                    "origem": "bot",
                    "source": "bot_suggest_reviewed",
                    "resposta_id": str(resposta.id),
                    "idempotency_key": f"whatsapp-bot-resposta-{resposta.id}",
                },
            },
            timeout=timeout,
        )
        node_response.raise_for_status()
        try:
            response_payload = node_response.json()
            node_idempotent = bool(
                isinstance(response_payload, dict) and response_payload.get("idempotent", False)
            )
        except Exception:
            node_idempotent = False
    except httpx.HTTPStatusError as exc:
        _reset_sending_to_draft(db, resposta_id)
        response_status = exc.response.status_code
        if response_status == 409:
            try:
                response_code = exc.response.json().get("code")
            except Exception:
                response_code = None
            if response_code == "MESSAGE_SEND_IN_PROGRESS":
                raise HTTPException(
                    status_code=409,
                    detail="O envio deste rascunho já está em processamento.",
                ) from None
            raise HTTPException(
                status_code=409,
                detail="A janela de atendimento do WhatsApp está fechada.",
            ) from None
        raise HTTPException(status_code=502, detail="Falha ao enviar o rascunho pelo WhatsApp.") from None
    except Exception:
        _reset_sending_to_draft(db, resposta_id)
        raise HTTPException(status_code=502, detail="Falha ao acessar o serviço do WhatsApp.") from None

    db.expire_all()
    resposta = db.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.id == resposta_id).first()
    if resposta is None:
        raise HTTPException(status_code=500, detail="Rascunho desapareceu após o envio.")
    resposta.decisao = "sent"
    resposta.texto_enviado = texto
    resposta.feedback = "positivo"
    resposta.enviado_por_id = current_user.id
    # Aprovar resposta nao assume a conversa. Pausa apenas quando configurada.
    if _assisted_send_pause_hours() > 0:
        pause_conversation(
            db,
            resposta.wa_identity,
            atualizado_por_id=current_user.id,
            horas=_assisted_send_pause_hours(),
        )
    from app.services.whatsapp_bot_agendamento import encaminhar
    encaminhar(db, resposta)
    db.commit()
    db.refresh(resposta)
    registrar_auditoria(
        current_user=current_user,
        modulo="whatsapp_chatbot",
        entidade="whatsapp_bot_resposta",
        entidade_id=resposta.id,
        acao="ENVIAR_RASCUNHO",
        descricao="Rascunho do chatbot revisado e enviado por atendente.",
        detalhes={"editado": texto != str(resposta.texto_gerado or "").strip()},
    )
    return _sent_payload(resposta, idempotent=node_idempotent)


@router.post("/respostas/{resposta_id}/descartar")
def descartar_rascunho(
    resposta_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """RF-028: descarta sem enviar e registra feedback negativo."""
    updated = (
        db.query(WhatsAppBotResposta)
        .filter(
            WhatsAppBotResposta.id == resposta_id,
            WhatsAppBotResposta.decisao == "draft",
            WhatsAppBotResposta.feedback.is_(None),
        )
        .update(
            {"feedback": "negativo", "enviado_por_id": current_user.id},
            synchronize_session=False,
        )
    )
    db.commit()
    if updated != 1:
        resposta = db.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.id == resposta_id).first()
        if resposta is None:
            raise HTTPException(status_code=404, detail="Rascunho não encontrado.")
        if resposta.feedback == "negativo":
            return {"resposta_id": resposta.id, "status": "discarded", "idempotent": True}
        raise HTTPException(status_code=409, detail="Rascunho não está mais disponível.")
    registrar_auditoria(
        current_user=current_user,
        modulo="whatsapp_chatbot",
        entidade="whatsapp_bot_resposta",
        entidade_id=resposta_id,
        acao="DESCARTAR_RASCUNHO",
        descricao="Rascunho do chatbot descartado por atendente, sem envio.",
    )
    return {"resposta_id": resposta_id, "status": "discarded", "idempotent": False}


@router.get("/preview")
def preview_whatsapp_bot(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """CA-019: somente leitura - nenhum job e alterado, nada e gerado nem

    enviado. Serve para inspecionar o estado atual antes/depois de habilitar
    o bot, no mesmo espirito do `lembrete-preview`.
    """
    del current_user
    config = db.query(Configuracao).first()

    jobs_por_status = dict(
        db.query(WhatsAppBotJob.status, func.count(WhatsAppBotJob.id))
        .group_by(WhatsAppBotJob.status)
        .all()
    )
    respostas_por_decisao = dict(
        db.query(WhatsAppBotResposta.decisao, func.count(WhatsAppBotResposta.id))
        .group_by(WhatsAppBotResposta.decisao)
        .all()
    )

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "whatsapp_bot_enabled_env": bool(settings.WHATSAPP_BOT_ENABLED),
        "whatsapp_bot_atendimento_habilitado_banco": bool(
            getattr(config, "whatsapp_bot_atendimento_habilitado", False)
        ),
        "whatsapp_bot_ativo": is_whatsapp_bot_enabled(),
        "whatsapp_bot_modo_institucional": getattr(config, "whatsapp_bot_modo", None) or "suggest",
        "jobs_por_status": jobs_por_status,
        "respostas_por_decisao": respostas_por_decisao,
    }


@router.get("/metricas")
def metricas_observacao(
    dias: int = JANELA_PADRAO_DIAS,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """P6.3/P6.5: metricas da observacao em `suggest`, somente leitura.

    Aceite, edicao, descarte, bloqueios, latencia e custo, quebrados por
    persona e por dentro/fora do expediente. Nenhuma linha e alterada e
    nenhuma geracao ou envio acontece - e o insumo da decisao de `auto`, que
    continua exigindo autorizacao humana registrada no verify.md.
    """
    del current_user
    return coletar_metricas_observacao(db, dias=dias)


# --------------------------------------------------------------------------
# Painel de configuracao do bot (Fase 6)
# --------------------------------------------------------------------------

# Categoria imposta ao conteudo cadastrado por aqui. O campo livre da tela do
# assistente interno e a origem do erro mais comum: com o default `manual` o
# documento fica invisivel para o bot, em silencio. Aqui a audiencia nao e
# digitada, e derivada da persona escolhida.
_CATEGORIA_POR_PUBLICO = {
    "tutor": "institucional_tutor",
    "clinica": "institucional_clinica",
    "ambos": "institucional",
}


class WhatsAppBotConhecimentoCreateRequest(BaseModel):
    titulo: str = Field(min_length=3, max_length=220)
    conteudo: str = Field(min_length=20)
    publico: str = Field(
        default="ambos", description="tutor | clinica | ambos - define a categoria."
    )
    fonte: str = Field(
        min_length=2,
        max_length=500,
        description="Obrigatoria: a RF-020 exige que o bot cite fonte.",
    )
    indexar_semanticamente: bool = False


class WhatsAppBotSimulacaoMensagem(BaseModel):
    de: str = Field(description="cliente | nos")
    texto: str = Field(min_length=1, max_length=1000)


class WhatsAppBotSimulacaoRequest(BaseModel):
    mensagem: str = Field(min_length=3, max_length=1000)
    persona: str = Field(default="tutor", description="tutor | clinica")
    # Mensagens anteriores fingidas, para testar a memoria de conversa sem
    # precisar de uma conversa real. Teto igual ao do worker.
    historico: list[WhatsAppBotSimulacaoMensagem] = Field(default_factory=list, max_length=12)


@router.get("/prontidao")
def prontidao_do_bot(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """Por persona e intent: o bot consegue responder hoje, e o que falta.

    Somente leitura e sem chamada de LLM - cada intent e verificada rodando a
    tool que a sustenta. Mede se a FONTE existe, nao se a resposta e boa.
    """
    del current_user
    return coletar_prontidao(db)


@router.get("/conhecimento")
def listar_conhecimento_do_bot(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """Lista apenas o conteudo que o BOT enxerga.

    A base e compartilhada com o assistente interno; esta rota filtra pela
    mesma regra de audiencia da tool, para a tela nao mostrar documento que o
    bot descarta (nem esconder documento que ele usa).
    """
    del current_user
    from app.services.assistente_ia_management import list_documents
    from app.services.whatsapp_bot_tools import _categoria_e_institucional

    todos = list_documents(db, include_archived=False)
    visiveis, ignorados = [], []
    for item in todos:
        alvo = visiveis if _categoria_e_institucional(item.get("category")) else ignorados
        alvo.append(item)
    return {
        "visiveis_para_o_bot": visiveis,
        "ignorados_pelo_bot": ignorados,
        "total_visiveis": len(visiveis),
        "total_ignorados": len(ignorados),
    }


@router.post("/conhecimento")
def criar_conhecimento_do_bot(
    payload: WhatsAppBotConhecimentoCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    """Cadastra conteudo JA com a audiencia e a fonte corretas.

    Diferenca em relacao a tela do assistente interno: categoria nao e campo
    livre (deriva de `publico`) e `fonte` e obrigatoria. As duas coisas que
    silenciosamente tornavam um documento invisivel para o bot deixam de ser
    possiveis por construcao.
    """
    publico = str(payload.publico or "ambos").strip().lower()
    categoria = _CATEGORIA_POR_PUBLICO.get(publico)
    if categoria is None:
        raise HTTPException(
            status_code=422, detail="publico deve ser 'tutor', 'clinica' ou 'ambos'."
        )

    from app.services.assistente_ia_management import create_document

    documento = create_document(
        db,
        current_user,
        title=payload.titulo,
        content=payload.conteudo,
        category=categoria,
        source=payload.fonte,
        semantic_index=payload.indexar_semanticamente,
    )
    registrar_auditoria(
        current_user=current_user,
        modulo="whatsapp_chatbot",
        entidade="assistente_ia_conhecimento_documento",
        entidade_id=None,
        acao="CADASTRAR_CONHECIMENTO_BOT",
        descricao=f"Conteudo institucional do bot cadastrado para publico '{publico}'.",
    )
    return {"documento": documento, "categoria_aplicada": categoria, "publico": publico}


@router.post("/simular")
def simular_resposta_do_bot(
    payload: WhatsAppBotSimulacaoRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """Mostra o que o bot responderia, SEM enviar e SEM gravar auditoria.

    Faz chamada real de LLM, portanto custa tokens. Nada e persistido em
    `whatsapp_bot_respostas`: se gravasse, a simulacao entraria nas metricas
    de aceite e contaminaria justamente o numero que autoriza o modo `auto`.
    """
    persona = str(payload.persona or "tutor").strip().lower()
    if persona not in ("tutor", "clinica"):
        raise HTTPException(status_code=422, detail="persona deve ser 'tutor' ou 'clinica'.")

    from app.services.whatsapp_bot_simulation_service import simular_resposta

    try:
        return simular_resposta(
            db,
            mensagem=payload.mensagem,
            persona=persona,
            # `montar_historico` fala o dialeto do servico de WhatsApp
            # (`body`/`from_me`); a conversao acontece aqui para o painel nao
            # ter de conhecer aquele formato.
            historico=[
                {"body": item.texto, "from_me": item.de == "nos"}
                for item in payload.historico
            ],
            solicitado_por_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


class WhatsAppBotClinicaEstadoUpdateRequest(BaseModel):
    modo: str = Field(description="off | suggest | auto")
    observacao: Optional[str] = Field(default=None, max_length=500)


@router.get("/clinicas")
def listar_participacao_das_clinicas(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """RF-P07: clinicas ativas com o estado de participacao no bot.

    Devolve tambem a postura vigente, porque o mesmo `modo` significa coisas
    diferentes em `todos` e em `piloto`: sem linha, a clinica herda o padrao
    institucional na primeira e fica de fora na segunda.
    """
    del current_user
    participacao = resolve_participacao(db)
    estados = {
        linha.clinica_id: linha
        for linha in db.query(WhatsAppBotClinicaEstado).all()
    }
    clinicas = (
        db.query(Clinica)
        .filter(Clinica.ativo.is_(True))
        .order_by(Clinica.nome.asc())
        .all()
    )
    itens = []
    for clinica in clinicas:
        linha = estados.get(clinica.id)
        itens.append(
            {
                "clinica_id": clinica.id,
                "nome": clinica.nome,
                "modo": linha.modo if linha is not None else None,
                "observacao": linha.observacao if linha is not None else None,
                "habilitado_por_id": linha.habilitado_por_id if linha is not None else None,
                "atualizado_em": (
                    linha.updated_at.isoformat() if linha is not None and linha.updated_at else None
                ),
                # Sem linha o comportamento depende da postura - por isso o
                # campo e derivado aqui, e nao inferido na tela.
                "participa": (
                    linha.modo != "off" if linha is not None else participacao == "todos"
                ),
            }
        )
    return {"participacao": participacao, "total": len(itens), "clinicas": itens}


@router.put("/clinicas/{clinica_id}")
def atualizar_participacao_da_clinica(
    clinica_id: int,
    payload: WhatsAppBotClinicaEstadoUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """RF-P07: habilita ou desabilita o bot para uma clinica parceira.

    Nao exige admin, pelo mesmo motivo do modo por conversa: e controle
    operacional do dia a dia. Quem e admin-only e a POSTURA
    (`whatsapp_bot_participacao`), que decide o alcance global.
    """
    modo = str(payload.modo or "").strip().lower()
    if modo not in MODOS_VALIDOS:
        raise HTTPException(status_code=422, detail="modo deve ser 'off', 'suggest' ou 'auto'.")

    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    if clinica is None:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada.")

    linha = (
        db.query(WhatsAppBotClinicaEstado)
        .filter(WhatsAppBotClinicaEstado.clinica_id == clinica_id)
        .first()
    )
    if linha is None:
        linha = WhatsAppBotClinicaEstado(clinica_id=clinica_id)
        db.add(linha)
    linha.modo = modo
    linha.observacao = (payload.observacao or None)
    linha.habilitado_por_id = current_user.id
    db.commit()

    registrar_auditoria(
        current_user=current_user,
        modulo="whatsapp_chatbot",
        entidade="whatsapp_bot_clinica_estado",
        entidade_id=clinica_id,
        acao="ATUALIZAR_PARTICIPACAO",
        descricao=f"Participacao do bot da clinica {clinica_id} definida como '{modo}'.",
        detalhes={"modo": modo},
    )
    return {
        "clinica_id": clinica_id,
        "modo": modo,
        "participacao": resolve_participacao(db),
    }


@router.delete("/clinicas/{clinica_id}")
def remover_participacao_da_clinica(
    clinica_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    """Remove a marcacao e devolve a clinica ao comportamento padrao.

    Existe porque "sem marcacao" e `off` NAO sao a mesma coisa em `todos`: a
    primeira herda o padrao institucional, a segunda exclui. Sem este endpoint,
    marcar uma clinica para testar era irreversivel pela interface - o admin
    ficava preso entre dois estados quando o original era um terceiro.

    Em `piloto` os dois se comportam igual (ambos ficam de fora), e e
    justamente por isso que a diferenca passa despercebida ate alguem voltar a
    postura para `todos`.
    """
    linha = (
        db.query(WhatsAppBotClinicaEstado)
        .filter(WhatsAppBotClinicaEstado.clinica_id == clinica_id)
        .first()
    )
    if linha is None:
        # Idempotente: sem marcacao ja e o estado desejado.
        return {"clinica_id": clinica_id, "modo": None, "participacao": resolve_participacao(db)}

    db.delete(linha)
    db.commit()
    registrar_auditoria(
        current_user=current_user,
        modulo="whatsapp_chatbot",
        entidade="whatsapp_bot_clinica_estado",
        entidade_id=clinica_id,
        acao="REMOVER_PARTICIPACAO",
        descricao=f"Marcacao de participacao da clinica {clinica_id} removida.",
    )
    return {"clinica_id": clinica_id, "modo": None, "participacao": resolve_participacao(db)}


class WhatsAppBotSolicitacaoUpdate(BaseModel):
    versao: int = Field(ge=1)
    acao: Literal['assumir', 'liberar', 'atualizar']
    status: Optional[Literal['aguardando_equipe', 'em_atendimento', 'aguardando_cliente', 'agendado', 'cancelado']] = None
    prazo_em: Optional[datetime] = None
    observacao: Optional[str] = Field(default=None, max_length=500)


class WhatsAppAssumirAtendimento(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64, pattern=r"^[0-9]+$")
    telefone: str = Field(min_length=8, max_length=30, pattern=r"^[0-9]+$")


@router.post('/atendimentos/assumir')
def assumir_atendimento(payload: WhatsAppAssumirAtendimento, db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS))):
    from app.services.whatsapp_bot_atendimento import assumir
    return assumir(db, payload.conversation_id, payload.telefone, current_user)


@router.get('/solicitacoes')
def listar_solicitacoes(
    filtro: Literal['abertas','atrasadas','todas','aguardando_equipe','em_atendimento','aguardando_cliente','agendado','cancelado'] = 'abertas',
    minhas: bool = False,
    page: int = Query(default=1, ge=1, le=10000),
    conversation_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    from app.services.whatsapp_bot_fila import listar
    return listar(db, current_user.id, filtro, minhas, page, conversation_id)


@router.patch('/solicitacoes/{pedido_id}')
def atualizar_solicitacao(
    pedido_id: int, payload: WhatsAppBotSolicitacaoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    from app.services.whatsapp_bot_fila import atualizar
    if payload.acao == 'assumir':
        from app.models.whatsapp_bot import WhatsAppBotSolicitacao
        from app.services.whatsapp_bot_atendimento import assumir
        row = db.get(WhatsAppBotSolicitacao, pedido_id)
        if not row:
            raise HTTPException(404, 'Solicitação não encontrada.')
        return assumir(db, row.conversation_id, row.wa_identity, current_user, row.id, payload.versao)
    return atualizar(db, pedido_id, payload, current_user)


@router.get('/solicitacoes/{pedido_id}/preparar-agendamento')
def preparar_agendamento_pedido(
    pedido_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(require_any_papel(*_WHATSAPP_BOT_PAPEIS)),
):
    from app.services.whatsapp_bot_pedido_agenda import preparar
    return preparar(db, pedido_id, current_user)
