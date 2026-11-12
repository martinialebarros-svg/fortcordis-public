from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from openai import APIConnectionError, APIStatusError, BadRequestError, OpenAI, RateLimitError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.assistente_ia import (
    AssistenteIAAcaoPendente,
    AssistenteIAConversa,
    AssistenteIAMensagem,
)
from app.models.user import User
from app.services.assistente_ia_tools import (
    AssistenteIAToolContext,
    TOOL_DEFINITIONS,
    execute_tool,
    serialize_pending_action,
    tool_result_for_model,
    tool_result_summary,
)
from app.services.assistente_ia_management import approved_memory_context
from app.services.auditoria_service import registrar_auditoria
from app.services.google_maps_cost_control import GoogleMapsCostBlocked

logger = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("America/Fortaleza")


class AssistenteIAProviderError(RuntimeError):
    pass


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def ensure_assistant_available() -> None:
    if not settings.ASSISTENTE_IA_ENABLED:
        raise HTTPException(status_code=503, detail="O assistente IA esta desabilitado neste ambiente.")
    if not str(settings.OPENAI_API_KEY or "").strip():
        raise HTTPException(
            status_code=503,
            detail="O assistente IA ainda nao possui credencial configurada no backend.",
        )


def create_conversation(db: Session, current_user: User, *, title: str = "Nova conversa") -> AssistenteIAConversa:
    conversation = AssistenteIAConversa(
        id=str(uuid.uuid4()),
        usuario_id=int(current_user.id),
        titulo=(str(title or "Nova conversa").strip() or "Nova conversa")[:160],
        ativa=True,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_owned_conversation(
    db: Session,
    current_user: User,
    conversation_id: str,
) -> AssistenteIAConversa:
    conversation = (
        db.query(AssistenteIAConversa)
        .filter(
            AssistenteIAConversa.id == conversation_id,
            AssistenteIAConversa.usuario_id == current_user.id,
            AssistenteIAConversa.ativa.is_(True),
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada.")
    return conversation


def serialize_message(message: AssistenteIAMensagem) -> dict[str, Any]:
    return {
        "id": int(message.id),
        "conversation_id": str(message.conversa_id),
        "role": str(message.papel),
        "content": str(message.conteudo),
        "tools": _json_loads(message.ferramentas_json, []),
        "pending_action_id": message.acao_pendente_id,
        "telemetry": {
            "input_tokens": message.input_tokens,
            "output_tokens": message.output_tokens,
            "total_tokens": message.total_tokens,
            "latency_ms": message.latency_ms,
            "status": message.provider_status,
        } if message.papel == "assistant" else None,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def serialize_conversation(
    conversation: AssistenteIAConversa,
    *,
    messages: Optional[list[AssistenteIAMensagem]] = None,
    pending_actions: Optional[list[AssistenteIAAcaoPendente]] = None,
) -> dict[str, Any]:
    payload = {
        "id": str(conversation.id),
        "title": str(conversation.titulo),
        "active": bool(conversation.ativa),
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }
    if messages is not None:
        payload["messages"] = [serialize_message(message) for message in messages]
    if pending_actions is not None:
        payload["pending_actions"] = [serialize_pending_action(action) for action in pending_actions]
    return payload


def list_conversations(db: Session, current_user: User, *, limit: int = 40) -> list[dict[str, Any]]:
    rows = (
        db.query(AssistenteIAConversa)
        .filter(
            AssistenteIAConversa.usuario_id == current_user.id,
            AssistenteIAConversa.ativa.is_(True),
        )
        .order_by(AssistenteIAConversa.updated_at.desc(), AssistenteIAConversa.created_at.desc())
        .limit(max(1, min(100, int(limit))))
        .all()
    )
    return [serialize_conversation(row) for row in rows]


def conversation_detail(
    db: Session,
    current_user: User,
    conversation_id: str,
) -> dict[str, Any]:
    conversation = get_owned_conversation(db, current_user, conversation_id)
    messages = (
        db.query(AssistenteIAMensagem)
        .filter(
            AssistenteIAMensagem.conversa_id == conversation.id,
            AssistenteIAMensagem.usuario_id == current_user.id,
        )
        .order_by(AssistenteIAMensagem.created_at.asc(), AssistenteIAMensagem.id.asc())
        .all()
    )
    actions = (
        db.query(AssistenteIAAcaoPendente)
        .filter(
            AssistenteIAAcaoPendente.conversa_id == conversation.id,
            AssistenteIAAcaoPendente.usuario_id == current_user.id,
        )
        .order_by(AssistenteIAAcaoPendente.created_at.asc())
        .all()
    )
    return serialize_conversation(conversation, messages=messages, pending_actions=actions)


def _assistant_instructions(current_user: User, memory_context: str) -> str:
    today = _local_today().isoformat()
    return f"""
Role: Voce e a mente de gestao do FortCordis, trabalhando exclusivamente com o administrador autenticado.

Goal: Entender a solicitacao, consultar as ferramentas do FortCordis e entregar uma resposta correta, pratica e baseada nos dados retornados.

Current context:
- data atual: {today}
- administrador: {str(current_user.nome or 'Admin')}
- idioma padrao: portugues do Brasil

Memoria supervisionada aprovada pelo administrador:
{memory_context}

Success criteria:
- use uma ferramenta sempre que a pergunta depender de dados atuais do sistema;
- apresente numeros, periodo e clinica usados na consulta;
- diferencie fato retornado pela ferramenta de interpretacao gerencial;
- aceite pequenas diferencas de digitacao em nomes de clinicas quando a ferramenta resolver um unico cadastro com alta confianca;
- quando a ferramenta corrigir um nome de clinica, diga brevemente qual cadastro foi interpretado;
- quando houver ambiguidade real de clinica, servico ou agendamento, mostre as opcoes e peca o menor esclarecimento necessario;
- conclua em linguagem direta, com achados principais e proximo passo util.

Safety and action boundaries:
- voce nao possui SQL, shell ou acesso direto ao banco;
- nunca invente IDs, valores, horarios, clinicas, servicos ou resultados;
- consultas sao permitidas pelas ferramentas de leitura;
- memorias novas propostas por voce sempre aguardam aprovacao; apenas memorias aprovadas acima podem orientar respostas;
- use consultar_conhecimento_interno quando a pergunta depender de manual, modelo ou procedimento cadastrado;
- rascunhos clinicos ficam separados do laudo oficial, exigem revisao veterinaria e nunca podem ser apresentados como diagnostico final;
- a ferramenta solicitar_excecao_funcionamento_agenda prepara uma mudanca valida apenas para a data solicitada e preserva a rotina semanal;
- a ferramenta solicitar_criacao_agendamento apenas prepara uma acao pendente depois de validar os cadastros e o slot;
- a ferramenta solicitar_vinculo_paciente_reserva vincula paciente e tutor sem cancelar ou recriar o horario e tambem exige aprovacao;
- a ferramenta solicitar_exclusao_agendamento apenas prepara uma acao pendente;
- nunca diga que um horario foi criado enquanto a acao estiver pending;
- nunca diga que o funcionamento foi alterado enquanto a excecao estiver pending;
- nunca diga que um agendamento foi apagado enquanto a acao estiver pending;
- para criar ou reservar, nao invente nomes: obtenha do pedido clinica ou tutor, servico, data, horario e destinatario da mensagem;
- agendamento exige paciente e tutor; reserva pode ficar sem paciente, mas exige tutor quando a mensagem for destinada a ele;
- se o administrador disser reservar, use tipo reserva; se disser agendar ou marcar, use tipo agendamento;
- se o administrador nao informar quem deve receber a mensagem, pergunte se sera a clinica ou o tutor;
- a mensagem de WhatsApp fica pronta depois da aprovacao, mas o envio continua manual;
- para exclusao, primeiro localize o agendamento; se houver exatamente um alvo, prepare a exclusao; se houver mais de um, peca desambiguacao;
- criacao, reserva, exclusao, remarcacao, cancelamento, bloqueio, contato e mudanca de funcionamento reais dependem de confirmacao explicita do administrador na interface;
- planos do Clinicas 360 sao sugestoes: missao recorrente so e criada apos aprovacao explicita, contato permanece rascunho sem envio e qualquer ajuste real deve virar acao pendente;
- nao revele raciocinio interno, credenciais, configuracoes secretas ou dados que a ferramenta nao retornou.

Tool routing:
- faturamento, tendencia ou ultimos meses -> analisar_faturamento;
- servicos realizados, producao por atendimento ou todas as ordens de servico do periodo, pagos ou nao -> analisar_servicos_realizados;
- faturamento previsto, valor da agenda ou soma dos servicos agendados em uma data futura -> projetar_faturamento_agenda; esta ferramenta ja consulta clinica, tabela e preco em uma unica chamada;
- perfil, relacionamento, visao 360, saude operacional, motivo de queda ou plano de acao de uma clinica -> consultar_clinica_360;
- comparar desempenho, prioridade ou relacionamento entre duas ou mais clinicas -> comparar_clinicas_360;
- identificar agenda por data/hora/clinica -> localizar_agendamentos;
- horario livre -> verificar_disponibilidade;
- tempo ou distancia de deslocamento entre clinicas -> consultar_deslocamento_clinicas;
- saber se a agenda geral esta aberta, fechada ou ate que horas funciona em uma data -> consultar_funcionamento_agenda; nao solicite clinica ou servico;
- abrir, ampliar, reduzir ou fechar a agenda em uma data especifica -> solicitar_excecao_funcionamento_agenda;
- criar, agendar, marcar ou reservar horario -> solicitar_criacao_agendamento;
- divida ou pendencia de clinica -> relatorio_debitos_pendentes;
- apagar agendamento ja identificado -> solicitar_exclusao_agendamento.
- incluir ou vincular paciente e tutor em reserva ja localizada -> solicitar_vinculo_paciente_reserva; nao cancele a reserva para recria-la;
- resumo do dia, pendencias prioritarias ou briefing executivo -> gerar_resumo_executivo;
- remarcar ou mover agendamento identificado com data e horario de destino -> solicitar_remarcacao_agendamento; se faltar apenas o motivo, use "Solicitacao do administrador" como motivo neutro e nunca invente justificativa clinica;
- cancelar sem apagar historico -> solicitar_cancelamento_agendamento;
- bloquear slot com data, inicio, fim e motivo definidos -> solicitar_bloqueio_agenda diretamente; listar_bloqueios_agenda fica para consulta ou para identificar qual bloqueio deve ser liberado;
- liberar slot ja bloqueado -> listar_bloqueios_agenda e solicitar_liberacao_bloqueio_agenda;
- trocar WhatsApps de clinica -> solicitar_atualizacao_whatsapps_clinica;
- lembrar preferencia ou regra de trabalho -> propor_memoria_operacional;
- manual, procedimento ou modelo interno -> consultar_conhecimento_interno;
- comparar ou ajudar em laudo sem texto clinico suficiente -> obter_contexto_laudo primeiro;
- salvar rascunho com conteudo fornecido ou ja obtido -> salvar_rascunho_clinico; se o pedido solicitar preparar e salvar sem fornecer conteudo, carregue o contexto e depois salve o rascunho no mesmo atendimento.

Output:
- comece pela conclusao;
- use listas curtas ou tabela textual apenas quando melhorarem a leitura;
- para relatorios, inclua totais, principais itens, ressalvas e uma recomendacao objetiva;
- preserve todos os fatos relevantes e evite introducoes genericas.

Stop rules:
- encerre quando a solicitacao estiver respondida com evidencia suficiente;
- nao repita uma ferramenta sem nova informacao;
- se faltar um dado obrigatorio, solicite apenas esse dado.
""".strip()


def _safety_identifier(current_user: User) -> str:
    raw = f"fortcordis-admin:{int(current_user.id)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_intent_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return " ".join(
        "".join(char for char in normalized if not unicodedata.combining(char)).split()
    )


def _is_agenda_revenue_forecast_request(message: str) -> bool:
    text = _normalize_intent_text(message)
    financial = any(
        token in text
        for token in ("fatur", "valor", "dinheiro", "somar", "soma")
    )
    scheduled = any(
        token in text
        for token in ("agendad", "agenda", "previst", "previs")
    )
    dated = (
        any(token in text for token in ("amanha", "hoje", "depois de amanha"))
        or bool(re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", text))
    )
    pricing_follow_up = (
        "tabela" in text
        and "servic" in text
        and any(token in text for token in ("previst", "executad", "agendad"))
    )
    return bool(financial and ((scheduled and dated) or pricing_follow_up))


def _local_today() -> date:
    return datetime.now(LOCAL_TZ).date()


def _absolute_date_from_text(message: str, *, reference: date) -> Optional[date]:
    raw = str(message or "")
    iso_match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", raw)
    if iso_match:
        try:
            return date(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
            )
        except ValueError:
            return None
    br_match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", raw)
    if not br_match:
        return None
    year = int(br_match.group(3) or reference.year)
    if year < 100:
        year += 2000
    try:
        return date(year, int(br_match.group(2)), int(br_match.group(1)))
    except ValueError:
        return None


def _relative_date_from_text(message: str, *, reference: date) -> Optional[date]:
    text = _normalize_intent_text(message)
    if "depois de amanha" in text:
        return reference + timedelta(days=2)
    if "amanha" in text:
        return reference + timedelta(days=1)
    if "hoje" in text:
        return reference
    return None


def _resolve_forecast_date(
    db: Session,
    conversation: AssistenteIAConversa,
    *,
    message: str,
    current_message_id: int,
) -> Optional[date]:
    reference = _local_today()
    direct = (
        _absolute_date_from_text(message, reference=reference)
        or _relative_date_from_text(message, reference=reference)
    )
    if direct is not None:
        return direct

    history = (
        db.query(AssistenteIAMensagem)
        .filter(
            AssistenteIAMensagem.conversa_id == conversation.id,
            AssistenteIAMensagem.id != current_message_id,
        )
        .order_by(AssistenteIAMensagem.created_at.desc(), AssistenteIAMensagem.id.desc())
        .limit(8)
        .all()
    )
    for row in history:
        resolved = _absolute_date_from_text(str(row.conteudo), reference=reference)
        if resolved is not None:
            return resolved
    return None


def _local_history_for_fallback(
    db: Session,
    conversation: AssistenteIAConversa,
    current_user: User,
) -> list[dict[str, str]]:
    rows = (
        db.query(AssistenteIAMensagem)
        .filter(
            AssistenteIAMensagem.conversa_id == conversation.id,
            AssistenteIAMensagem.usuario_id == current_user.id,
            AssistenteIAMensagem.papel.in_(["user", "assistant"]),
        )
        .order_by(AssistenteIAMensagem.created_at.desc(), AssistenteIAMensagem.id.desc())
        .limit(20)
        .all()
    )
    return [
        {"role": str(row.papel), "content": str(row.conteudo)}
        for row in reversed(rows)
    ]


def _provider_request(
    client: OpenAI,
    *,
    current_user: User,
    memory_context: str,
    input_items: Any,
    previous_response_id: Optional[str],
    tool_definitions: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[dict[str, str] | str] = None,
) -> Any:
    selected_tools = TOOL_DEFINITIONS if tool_definitions is None else tool_definitions
    payload: dict[str, Any] = {
        "model": str(settings.ASSISTENTE_IA_MODEL or "gpt-5.6-sol"),
        "instructions": _assistant_instructions(current_user, memory_context),
        "input": input_items,
        "reasoning": {"effort": "medium"},
        "text": {"verbosity": "medium"},
        "max_output_tokens": 4000,
        "store": True,
        "safety_identifier": _safety_identifier(current_user),
    }
    if selected_tools:
        payload["tools"] = selected_tools
        payload["parallel_tool_calls"] = False
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    return client.responses.create(**payload)


def _safe_provider_error(exc: Exception) -> AssistenteIAProviderError:
    if isinstance(exc, RateLimitError):
        return AssistenteIAProviderError("A OpenAI esta com limite temporario. Tente novamente em instantes.")
    if isinstance(exc, APIConnectionError):
        return AssistenteIAProviderError("Nao foi possivel conectar ao servico de IA.")
    if isinstance(exc, APIStatusError):
        if exc.status_code in {401, 403}:
            return AssistenteIAProviderError("A credencial da OpenAI nao esta autorizada para esta operacao.")
        if exc.status_code == 404:
            return AssistenteIAProviderError("O modelo de IA configurado nao esta disponivel para esta conta.")
        return AssistenteIAProviderError(f"A OpenAI retornou uma falha operacional ({exc.status_code}).")
    return AssistenteIAProviderError("O assistente nao conseguiu concluir esta solicitacao.")


def run_assistant_turn(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    message: str,
    conversation: AssistenteIAConversa,
) -> dict[str, Any]:
    ensure_assistant_available()
    clean_message = str(message or "").strip()
    if not clean_message:
        raise HTTPException(status_code=422, detail="Informe uma mensagem para o assistente.")

    last_message = (
        db.query(AssistenteIAMensagem)
        .filter(
            AssistenteIAMensagem.conversa_id == conversation.id,
            AssistenteIAMensagem.usuario_id == current_user.id,
        )
        .order_by(AssistenteIAMensagem.created_at.desc(), AssistenteIAMensagem.id.desc())
        .first()
    )
    retrying_unanswered_message = bool(
        last_message is not None
        and str(last_message.papel) == "user"
        and str(last_message.conteudo).strip() == clean_message
    )
    if retrying_unanswered_message:
        user_message = last_message
        user_message.provider_status = "retrying"
    else:
        user_message = AssistenteIAMensagem(
            conversa_id=conversation.id,
            usuario_id=int(current_user.id),
            papel="user",
            conteudo=clean_message,
        )
        db.add(user_message)
    if conversation.titulo == "Nova conversa":
        conversation.titulo = clean_message.replace("\n", " ")[:90]
    conversation.updated_at = datetime.now(timezone.utc)
    db.add(conversation)
    db.commit()
    db.refresh(user_message)

    client = OpenAI(
        api_key=str(settings.OPENAI_API_KEY).strip(),
        timeout=90.0,
        max_retries=1,
    )
    memory_context = approved_memory_context(db)
    started_at = time.monotonic()
    input_tokens = 0
    output_tokens = 0
    forecast_route = _is_agenda_revenue_forecast_request(clean_message)
    forecast_date = (
        _resolve_forecast_date(
            db,
            conversation,
            message=clean_message,
            current_message_id=int(user_message.id),
        )
        if forecast_route
        else None
    )
    forecast_tools = (
        [
            definition
            for definition in TOOL_DEFINITIONS
            if definition.get("name") == "projetar_faturamento_agenda"
        ]
        if forecast_route
        else None
    )
    forecast_tool_choice = (
        {"type": "function", "name": "projetar_faturamento_agenda"}
        if forecast_route
        else None
    )

    def collect_usage(provider_response: Any) -> None:
        nonlocal input_tokens, output_tokens
        usage = getattr(provider_response, "usage", None)
        input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

    try:
        try:
            response = _provider_request(
                client,
                current_user=current_user,
                memory_context=memory_context,
                input_items=(
                    f"Data operacional resolvida pelo backend: {forecast_date.isoformat()}.\n"
                    f"Solicitacao do administrador: {clean_message}"
                    if forecast_date is not None
                    else clean_message
                ),
                previous_response_id=conversation.previous_response_id,
                tool_definitions=forecast_tools,
                tool_choice=forecast_tool_choice,
            )
            collect_usage(response)
        except BadRequestError as exc:
            if conversation.previous_response_id and "previous_response" in str(exc).lower():
                conversation.previous_response_id = None
                db.add(conversation)
                db.commit()
                response = _provider_request(
                    client,
                    current_user=current_user,
                    memory_context=memory_context,
                    input_items=_local_history_for_fallback(db, conversation, current_user),
                    previous_response_id=None,
                    tool_definitions=forecast_tools,
                    tool_choice=forecast_tool_choice,
                )
                collect_usage(response)
            else:
                raise

        tool_trace: list[dict[str, Any]] = []
        pending_action_ids: list[str] = []
        max_loops = max(1, min(10, int(settings.ASSISTENTE_IA_MAX_TOOL_LOOPS)))
        for loop_index in range(max_loops + 1):
            function_calls = [
                item
                for item in list(response.output or [])
                if getattr(item, "type", None) == "function_call"
            ]
            if not function_calls:
                break
            if loop_index >= max_loops:
                raise AssistenteIAProviderError(
                    "O assistente atingiu o limite seguro de ferramentas para uma unica mensagem."
                )

            outputs: list[dict[str, Any]] = []
            for call in function_calls:
                name = str(getattr(call, "name", ""))
                try:
                    arguments = json.loads(str(getattr(call, "arguments", "{}")) or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("argumentos invalidos")
                    if name == "projetar_faturamento_agenda" and forecast_date is not None:
                        arguments["data"] = forecast_date.isoformat()
                    result = execute_tool(
                        AssistenteIAToolContext(
                            db=db,
                            current_user=current_user,
                            conversa=conversation,
                            request=request,
                        ),
                        name=name,
                        arguments=arguments,
                    )
                except GoogleMapsCostBlocked:
                    raise
                except Exception as exc:
                    logger.exception("Falha ao executar ferramenta do assistente IA: %s", name)
                    result = {"ok": False, "error": f"Falha controlada na ferramenta {name}."}
                    if isinstance(exc, (KeyError, TypeError, ValueError)):
                        result["detail"] = "Os argumentos fornecidos nao passaram na validacao local."

                action_payload = result.get("pending_action") if isinstance(result, dict) else None
                if isinstance(action_payload, dict) and action_payload.get("id"):
                    pending_action_ids.append(str(action_payload["id"]))
                tool_trace.append(
                    {
                        "name": name,
                        "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
                        "summary": tool_result_summary(name, result if isinstance(result, dict) else {}),
                    }
                )
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(getattr(call, "call_id", "")),
                        "output": _json_dumps(tool_result_for_model(name, result)),
                    }
                )

            response = _provider_request(
                client,
                current_user=current_user,
                memory_context=memory_context,
                input_items=outputs,
                previous_response_id=str(response.id),
                tool_definitions=(
                    []
                    if forecast_route
                    and any(str(getattr(call, "name", "")) == "projetar_faturamento_agenda" for call in function_calls)
                    else None
                ),
            )
            collect_usage(response)

        final_text = str(response.output_text or "").strip()
        if not final_text:
            raise AssistenteIAProviderError("O assistente nao produziu uma resposta final.")

    except GoogleMapsCostBlocked:
        # A failed Maps validation must not commit pending business mutations
        # while recording the assistant's failed response.
        db.rollback()
        user_message.provider_status = "failed"
        db.add(user_message)
        db.commit()
        raise
    except AssistenteIAProviderError:
        user_message.provider_status = "failed"
        db.add(user_message)
        db.commit()
        raise
    except Exception as exc:
        user_message.provider_status = "failed"
        db.add(user_message)
        db.commit()
        logger.exception("Falha na chamada do assistente IA")
        raise _safe_provider_error(exc) from exc

    pending_actions = []
    if pending_action_ids:
        pending_actions = (
            db.query(AssistenteIAAcaoPendente)
            .filter(
                AssistenteIAAcaoPendente.id.in_(pending_action_ids),
                AssistenteIAAcaoPendente.usuario_id == current_user.id,
            )
            .all()
        )
    pending_action_id = pending_actions[-1].id if pending_actions else None
    assistant_message = AssistenteIAMensagem(
        conversa_id=conversation.id,
        usuario_id=int(current_user.id),
        papel="assistant",
        conteudo=final_text,
        ferramentas_json=_json_dumps(tool_trace),
        acao_pendente_id=pending_action_id,
        provider_response_id=str(response.id),
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        total_tokens=(input_tokens + output_tokens) or None,
        latency_ms=max(0, round((time.monotonic() - started_at) * 1000)),
        provider_status=str(getattr(response, "status", None) or "completed")[:32],
    )
    user_message.provider_status = "completed"
    conversation.previous_response_id = str(response.id)
    conversation.updated_at = datetime.now(timezone.utc)
    db.add_all([assistant_message, conversation])
    db.commit()
    db.refresh(assistant_message)
    db.refresh(conversation)

    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="conversa",
        entidade_id=conversation.id,
        acao="ASSISTENTE_IA_RESPOSTA_GERADA",
        descricao="Assistente IA respondeu a uma solicitacao administrativa.",
        detalhes={
            "modelo": str(settings.ASSISTENTE_IA_MODEL),
            "ferramentas": [item["name"] for item in tool_trace],
            "acoes_pendentes": pending_action_ids,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": assistant_message.latency_ms,
        },
        request=request,
    )

    return {
        "conversation": serialize_conversation(conversation),
        "user_message": serialize_message(user_message),
        "assistant_message": serialize_message(assistant_message),
        "tools": tool_trace,
        "pending_actions": [serialize_pending_action(action) for action in pending_actions],
    }
