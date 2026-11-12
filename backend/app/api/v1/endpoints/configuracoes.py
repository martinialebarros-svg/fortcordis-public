"""Endpoints para configurações do sistema"""
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, status
from sqlalchemy.orm import Session

from app.core.agenda_config import (
    DIA_SEMANA_KEYS,
    carregar_agenda_excecoes,
    carregar_agenda_feriados,
    carregar_agenda_semanal,
    normalizar_agenda_excecoes,
    normalizar_agenda_feriados,
    normalizar_agenda_semanal,
    serializar_json,
)
from app.core.agenda_route_rules import (
    carregar_agenda_rota_regras,
    normalizar_agenda_rota_regras,
)
from app.db.database import get_db
from app.models.user import User
from app.models.configuracao import Configuracao, ConfiguracaoUsuario
from app.core.security import get_current_user
from app.services.push_notifications import (
    deactivate_user_push_subscriptions,
    get_default_high_priority_push_actions,
    get_web_push_public_key,
    get_default_agenda_push_actions,
    is_web_push_enabled,
    normalize_high_priority_push_actions,
    normalize_agenda_push_actions,
    serialize_high_priority_push_actions,
    serialize_agenda_push_actions,
    upsert_user_push_subscription,
)
from app.services.push_scheduler_service import schedule_push_snooze

router = APIRouter()

# Tamanhos máximos
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "sim", "on"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "nao", "não", "off", ""}:
            return False
    return bool(value)


def get_or_create_configuracao(db: Session) -> Configuracao:
    """Obtém ou cria a configuração padrão"""
    config = db.query(Configuracao).first()
    if not config:
        config = Configuracao()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/configuracoes", response_model=dict)
def obter_configuracoes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém todas as configurações do sistema"""
    import traceback
    try:
        config = get_or_create_configuracao(db)
        agenda_semanal = carregar_agenda_semanal(getattr(config, "agenda_semanal", None))
        agenda_feriados = carregar_agenda_feriados(getattr(config, "agenda_feriados", None))
        agenda_excecoes = carregar_agenda_excecoes(getattr(config, "agenda_excecoes", None))
        agenda_rota_regras = carregar_agenda_rota_regras(getattr(config, "agenda_rota_regras", None))
        
        return {
            "id": config.id,
            "nome_empresa": config.nome_empresa,
            "endereco": config.endereco,
            "telefone": config.telefone,
            "email": config.email,
            "cidade": config.cidade,
            "estado": config.estado,
            "website": config.website,
            "tem_logomarca": config.logomarca_dados is not None,
            "tem_assinatura": config.assinatura_dados is not None,
            "texto_cabecalho_laudo": config.texto_cabecalho_laudo,
            "texto_rodape_laudo": config.texto_rodape_laudo,
            "mostrar_logomarca": config.mostrar_logomarca,
            "mostrar_assinatura": config.mostrar_assinatura,
            "fortinho_habilitado": bool(getattr(config, "fortinho_habilitado", False)),
            "whatsapp_lembrete_automatico_habilitado": bool(
                getattr(config, "whatsapp_lembrete_automatico_habilitado", False)
            ),
            "whatsapp_bot_atendimento_habilitado": bool(
                getattr(config, "whatsapp_bot_atendimento_habilitado", False)
            ),
            "whatsapp_bot_modo": getattr(config, "whatsapp_bot_modo", None) or "suggest",
            "whatsapp_bot_participacao": getattr(config, "whatsapp_bot_participacao", None) or "todos",
            "horario_comercial_inicio": config.horario_comercial_inicio,
            "horario_comercial_fim": config.horario_comercial_fim,
            "dias_trabalho": config.dias_trabalho,
            "agenda_semanal": agenda_semanal,
            "agenda_feriados": agenda_feriados,
            "agenda_excecoes": agenda_excecoes,
            "agenda_rota_regras": agenda_rota_regras,
            "created_at": config.created_at.isoformat() if config.created_at else None,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        }
    except Exception as e:
        print(f"ERRO ao obter configurações: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erro ao carregar configurações: {str(e)}")


@router.put("/configuracoes", response_model=dict)
def atualizar_configuracoes(
    dados: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza as configurações do sistema"""
    config = get_or_create_configuracao(db)
    
    campos_permitidos = [
        "nome_empresa", "endereco", "telefone", "email", "cidade", "estado",
        "website", "texto_cabecalho_laudo", "texto_rodape_laudo",
        "mostrar_logomarca", "mostrar_assinatura", "fortinho_habilitado",
        "whatsapp_lembrete_automatico_habilitado",
        "whatsapp_bot_atendimento_habilitado", "whatsapp_bot_modo",
        "whatsapp_bot_participacao",
        "horario_comercial_inicio", "horario_comercial_fim", "dias_trabalho",
        "agenda_semanal", "agenda_feriados", "agenda_excecoes", "agenda_rota_regras",
    ]

    if "fortinho_habilitado" in dados and not current_user.tem_papel("admin"):
        valor_atual = _coerce_bool(getattr(config, "fortinho_habilitado", False))
        valor_novo = _coerce_bool(dados.get("fortinho_habilitado"))
        if valor_novo != valor_atual:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas administradores podem ativar ou desativar o Fortinho.",
            )
    if "whatsapp_lembrete_automatico_habilitado" in dados and not current_user.tem_papel("admin"):
        valor_atual = _coerce_bool(getattr(config, "whatsapp_lembrete_automatico_habilitado", False))
        valor_novo = _coerce_bool(dados.get("whatsapp_lembrete_automatico_habilitado"))
        if valor_novo != valor_atual:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas administradores podem ativar ou desativar o lembrete automatico de WhatsApp.",
            )
    if "whatsapp_bot_atendimento_habilitado" in dados and not current_user.tem_papel("admin"):
        valor_atual = _coerce_bool(getattr(config, "whatsapp_bot_atendimento_habilitado", False))
        valor_novo = _coerce_bool(dados.get("whatsapp_bot_atendimento_habilitado"))
        if valor_novo != valor_atual:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas administradores podem ativar ou desativar o atendimento automatico de WhatsApp.",
            )
    if "whatsapp_bot_modo" in dados:
        modo_novo = str(dados.get("whatsapp_bot_modo") or "").strip().lower()
        if modo_novo not in {"off", "suggest", "auto"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="whatsapp_bot_modo deve ser 'off', 'suggest' ou 'auto'.",
            )
        dados["whatsapp_bot_modo"] = modo_novo
        if not current_user.tem_papel("admin") and modo_novo != str(getattr(config, "whatsapp_bot_modo", None) or "suggest"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas administradores podem alterar o modo padrao do atendimento automatico de WhatsApp.",
            )
    if "whatsapp_bot_participacao" in dados:
        # RF-P02: `piloto` restringe o atendimento a quem foi habilitado. E
        # decisao de alcance, entao segue a mesma regra dos demais
        # interruptores institucionais: admin-only.
        participacao_nova = str(dados.get("whatsapp_bot_participacao") or "").strip().lower()
        if participacao_nova not in {"todos", "piloto"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="whatsapp_bot_participacao deve ser 'todos' ou 'piloto'.",
            )
        dados["whatsapp_bot_participacao"] = participacao_nova
        atual = str(getattr(config, "whatsapp_bot_participacao", None) or "todos")
        if not current_user.tem_papel("admin") and participacao_nova != atual:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas administradores podem alterar a participacao do atendimento automatico.",
            )
    if "agenda_excecoes" in dados and not current_user.tem_papel("admin"):
        excecoes_atuais = carregar_agenda_excecoes(getattr(config, "agenda_excecoes", None))
        excecoes_novas = normalizar_agenda_excecoes(dados.get("agenda_excecoes"))
        if excecoes_novas != excecoes_atuais:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas administradores podem conceder ou alterar excecoes operacionais da agenda.",
            )
    
    agenda_semanal_normalizada = None
    for campo in campos_permitidos:
        if campo in dados:
            if campo == "agenda_semanal":
                agenda_semanal_normalizada = normalizar_agenda_semanal(dados[campo])
                setattr(config, campo, serializar_json(agenda_semanal_normalizada))
            elif campo == "agenda_feriados":
                agenda_feriados_normalizados = normalizar_agenda_feriados(dados[campo])
                setattr(config, campo, serializar_json(agenda_feriados_normalizados))
            elif campo == "agenda_excecoes":
                agenda_excecoes_normalizadas = normalizar_agenda_excecoes(dados[campo])
                setattr(config, campo, serializar_json(agenda_excecoes_normalizadas))
            elif campo == "agenda_rota_regras":
                agenda_rota_regras_normalizadas = normalizar_agenda_rota_regras(dados[campo])
                setattr(config, campo, serializar_json(agenda_rota_regras_normalizadas))
            else:
                setattr(config, campo, dados[campo])

    if agenda_semanal_normalizada:
        dias_ativos = [dia for dia in DIA_SEMANA_KEYS if agenda_semanal_normalizada[dia]["ativo"]]
        config.dias_trabalho = ",".join(dias_ativos)
        primeiro_dia_ativo = next((dia for dia in DIA_SEMANA_KEYS if agenda_semanal_normalizada[dia]["ativo"]), None)
        if primeiro_dia_ativo:
            config.horario_comercial_inicio = agenda_semanal_normalizada[primeiro_dia_ativo]["inicio"]
            config.horario_comercial_fim = agenda_semanal_normalizada[primeiro_dia_ativo]["fim"]
    
    config.updated_by_id = current_user.id
    db.commit()
    db.refresh(config)
    
    return {"message": "Configurações atualizadas com sucesso"}


@router.post("/configuracoes/logomarca", response_model=dict)
def upload_logomarca(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Faz upload da logomarca da empresa"""
    # Validar tipo
    if arquivo.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de arquivo não permitido. Use: JPEG, PNG, GIF, WebP"
        )
    
    # Ler conteúdo
    conteudo = arquivo.file.read()
    
    if len(conteudo) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo muito grande. Máximo: {MAX_IMAGE_SIZE / 1024 / 1024}MB"
        )
    
    # Salvar no banco
    config = get_or_create_configuracao(db)
    config.logomarca_nome = arquivo.filename
    config.logomarca_tipo = arquivo.content_type
    config.logomarca_dados = conteudo
    config.updated_by_id = current_user.id
    
    db.commit()
    
    return {
        "message": "Logomarca atualizada com sucesso",
        "nome_arquivo": arquivo.filename,
        "tamanho": len(conteudo)
    }


@router.get("/configuracoes/logomarca")
def obter_logomarca(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém a logomarca da empresa"""
    from fastapi.responses import Response
    
    config = db.query(Configuracao).first()
    
    if not config or not config.logomarca_dados:
        raise HTTPException(status_code=404, detail="Logomarca não encontrada")
    
    return Response(
        content=config.logomarca_dados,
        media_type=config.logomarca_tipo or "image/png"
    )


@router.delete("/configuracoes/logomarca", response_model=dict)
def remover_logomarca(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove a logomarca da empresa"""
    config = db.query(Configuracao).first()
    
    if config:
        config.logomarca_dados = None
        config.logomarca_nome = None
        config.logomarca_tipo = None
        config.updated_by_id = current_user.id
        db.commit()
    
    return {"message": "Logomarca removida com sucesso"}


@router.post("/configuracoes/assinatura", response_model=dict)
def upload_assinatura(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Faz upload da assinatura padrão do sistema"""
    # Validar tipo
    if arquivo.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de arquivo não permitido. Use: JPEG, PNG, GIF, WebP"
        )
    
    # Ler conteúdo
    conteudo = arquivo.file.read()
    
    if len(conteudo) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo muito grande. Máximo: {MAX_IMAGE_SIZE / 1024 / 1024}MB"
        )
    
    # Salvar no banco
    config = get_or_create_configuracao(db)
    config.assinatura_nome = arquivo.filename
    config.assinatura_tipo = arquivo.content_type
    config.assinatura_dados = conteudo
    config.updated_by_id = current_user.id
    
    db.commit()
    
    return {
        "message": "Assinatura atualizada com sucesso",
        "nome_arquivo": arquivo.filename,
        "tamanho": len(conteudo)
    }


@router.get("/configuracoes/assinatura")
def obter_assinatura(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém a assinatura padrão do sistema"""
    from fastapi.responses import Response
    
    config = db.query(Configuracao).first()
    
    if not config or not config.assinatura_dados:
        raise HTTPException(status_code=404, detail="Assinatura não encontrada")
    
    return Response(
        content=config.assinatura_dados,
        media_type=config.assinatura_tipo or "image/png"
    )


@router.delete("/configuracoes/assinatura", response_model=dict)
def remover_assinatura(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove a assinatura padrão do sistema"""
    config = db.query(Configuracao).first()
    
    if config:
        config.assinatura_dados = None
        config.assinatura_nome = None
        config.assinatura_tipo = None
        config.updated_by_id = current_user.id
        db.commit()
    
    return {"message": "Assinatura removida com sucesso"}


# Configurações do usuário
@router.get("/configuracoes/usuario", response_model=dict)
def obter_configuracoes_usuario(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém as configurações do usuário atual"""
    config = db.query(ConfiguracaoUsuario).filter(
        ConfiguracaoUsuario.user_id == current_user.id
    ).first()
    
    if not config:
        return {
            "user_id": current_user.id,
            "tema": "light",
            "idioma": "pt-BR",
            "notificacoes_email": True,
            "notificacoes_push": True,
            "notificacoes_push_tipos": get_default_agenda_push_actions(),
            "notificacoes_push_prioridade_alta_tipos": get_default_high_priority_push_actions(),
            "notificacoes_push_agrupar": True,
            "notificacoes_push_lembrete_pendencias": True,
            "notificacoes_push_lembrete_horas": 6,
            "notificacoes_push_perfil": "custom",
            "tem_assinatura": False,
            "crmv": None,
            "especialidade": None
        }
    
    tipos_push = normalize_agenda_push_actions(config.notificacoes_push_tipos)
    if config.notificacoes_push_tipos is None:
        tipos_push = get_default_agenda_push_actions()
    tipos_prioridade_alta = normalize_high_priority_push_actions(
        config.notificacoes_push_prioridade_alta_tipos
    )
    if config.notificacoes_push_prioridade_alta_tipos is None:
        tipos_prioridade_alta = get_default_high_priority_push_actions()
    lembrete_horas = int(config.notificacoes_push_lembrete_horas or 6)
    if lembrete_horas < 1:
        lembrete_horas = 1
    if lembrete_horas > 168:
        lembrete_horas = 168

    return {
        "user_id": config.user_id,
        "tema": config.tema,
        "idioma": config.idioma,
        "notificacoes_email": config.notificacoes_email,
        "notificacoes_push": config.notificacoes_push,
        "notificacoes_push_tipos": tipos_push,
        "notificacoes_push_prioridade_alta_tipos": tipos_prioridade_alta,
        "notificacoes_push_agrupar": bool(
            True if config.notificacoes_push_agrupar is None else config.notificacoes_push_agrupar
        ),
        "notificacoes_push_lembrete_pendencias": bool(
            True
            if config.notificacoes_push_lembrete_pendencias is None
            else config.notificacoes_push_lembrete_pendencias
        ),
        "notificacoes_push_lembrete_horas": lembrete_horas,
        "notificacoes_push_perfil": str(config.notificacoes_push_perfil or "custom"),
        "tem_assinatura": config.assinatura_dados is not None,
        "crmv": config.crmv,
        "especialidade": config.especialidade
    }


@router.put("/configuracoes/usuario", response_model=dict)
def atualizar_configuracoes_usuario(
    dados: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza as configurações do usuário"""
    config = db.query(ConfiguracaoUsuario).filter(
        ConfiguracaoUsuario.user_id == current_user.id
    ).first()
    
    if not config:
        config = ConfiguracaoUsuario(user_id=current_user.id)
        db.add(config)
    
    campos_permitidos = [
        "tema", "idioma", "notificacoes_email", "notificacoes_push", "notificacoes_push_tipos",
        "notificacoes_push_prioridade_alta_tipos",
        "notificacoes_push_agrupar",
        "notificacoes_push_lembrete_pendencias",
        "notificacoes_push_lembrete_horas",
        "notificacoes_push_perfil",
        "crmv", "especialidade"
    ]

    preferencia_push_desabilitada = False
    for campo in campos_permitidos:
        if campo in dados:
            valor = dados[campo]
            if campo in {"notificacoes_email", "notificacoes_push"}:
                valor = _coerce_bool(valor)
            if campo == "notificacoes_push_tipos":
                valor = serialize_agenda_push_actions(valor)
            if campo == "notificacoes_push_prioridade_alta_tipos":
                valor = serialize_high_priority_push_actions(valor)
            if campo in {"notificacoes_push_agrupar", "notificacoes_push_lembrete_pendencias"}:
                valor = _coerce_bool(valor)
            if campo == "notificacoes_push_lembrete_horas":
                try:
                    valor = int(valor)
                except Exception:
                    valor = 6
                if valor < 1:
                    valor = 1
                if valor > 168:
                    valor = 168
            if campo == "notificacoes_push_perfil":
                valor = str(valor or "custom").strip().lower() or "custom"
            setattr(config, campo, valor)
            if campo == "notificacoes_push":
                preferencia_push_desabilitada = not bool(valor)

    if preferencia_push_desabilitada:
        deactivate_user_push_subscriptions(
            db,
            user_id=current_user.id,
            commit=False,
        )

    db.commit()
    db.refresh(config)
    
    return {"message": "Configurações do usuário atualizadas com sucesso"}


@router.get("/configuracoes/usuario/push/public-key", response_model=dict)
def obter_chave_publica_push(
    current_user: User = Depends(get_current_user),
):
    """Retorna a chave publica VAPID para inscricao push no navegador."""
    _ = current_user
    enabled = is_web_push_enabled()
    return {
        "enabled": enabled,
        "public_key": get_web_push_public_key() if enabled else None,
    }


@router.post("/configuracoes/usuario/push/subscribe", response_model=dict)
def registrar_inscricao_push(
    dados: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Registra ou atualiza a inscricao push do dispositivo atual."""
    if not is_web_push_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push web indisponivel no servidor (VAPID nao configurado).",
        )

    subscription = dados.get("subscription")
    if not isinstance(subscription, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload de inscricao push invalido.",
        )

    try:
        upsert_user_push_subscription(
            db,
            user_id=current_user.id,
            subscription_payload=subscription,
            user_agent=request.headers.get("user-agent"),
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {"message": "Inscricao push registrada com sucesso"}


@router.post("/configuracoes/usuario/push/unsubscribe", response_model=dict)
def remover_inscricao_push(
    dados: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Desativa inscricao push do dispositivo atual."""
    endpoint = str(dados.get("endpoint") or "").strip()
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Endpoint da inscricao push nao informado.",
        )

    total_desativadas = deactivate_user_push_subscriptions(
        db,
        user_id=current_user.id,
        endpoint=endpoint,
        commit=True,
    )
    return {
        "message": "Inscricao push removida com sucesso",
        "desativadas": int(total_desativadas),
    }


@router.post("/configuracoes/usuario/push/snooze", response_model=dict)
def adiar_notificacao_push(
    dados: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agenda reenvio da notificacao push para o usuario atual (soneca)."""
    minutos = dados.get("minutes")
    try:
        minutos = int(minutos)
    except Exception:
        minutos = 15
    if minutos not in {15, 30, 60}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Soneca invalida. Use 15, 30 ou 60 minutos.",
        )

    resource_id_raw = dados.get("resource_id")
    resource_id: Optional[int] = None
    if resource_id_raw is not None and str(resource_id_raw).strip() != "":
        try:
            resource_id = int(resource_id_raw)
        except Exception:
            resource_id = None

    row = schedule_push_snooze(
        db,
        user_id=current_user.id,
        minutes=minutos,
        title=str(dados.get("title") or "").strip(),
        body=str(dados.get("body") or "").strip(),
        url=str(dados.get("url") or "").strip() or "/financeiro",
        module=str(dados.get("module") or "").strip() or "financeiro",
        action=str(dados.get("action") or "").strip() or "payment_pending",
        resource_type=str(dados.get("resource_type") or "").strip() or None,
        resource_id=resource_id,
        priority=str(dados.get("priority") or "").strip() or None,
        source_notification_id=str(dados.get("notification_id") or "").strip() or None,
        commit=True,
    )
    send_at = row.send_at.isoformat() if row.send_at else None
    return {
        "message": "Notificacao adiada com sucesso.",
        "id": int(row.id),
        "minutes": int(row.snooze_minutes or minutos),
        "send_at": send_at,
    }


@router.post("/configuracoes/usuario/assinatura", response_model=dict)
def upload_assinatura_usuario(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Faz upload da assinatura do usuário (veterinário)"""
    # Validar tipo
    if arquivo.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de arquivo não permitido. Use: JPEG, PNG, GIF, WebP"
        )
    
    # Ler conteúdo
    conteudo = arquivo.file.read()
    
    if len(conteudo) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo muito grande. Máximo: {MAX_IMAGE_SIZE / 1024 / 1024}MB"
        )
    
    # Buscar ou criar configuração do usuário
    config = db.query(ConfiguracaoUsuario).filter(
        ConfiguracaoUsuario.user_id == current_user.id
    ).first()
    
    if not config:
        config = ConfiguracaoUsuario(user_id=current_user.id)
        db.add(config)
    
    config.assinatura_nome = arquivo.filename
    config.assinatura_tipo = arquivo.content_type
    config.assinatura_dados = conteudo
    
    db.commit()
    
    return {
        "message": "Assinatura pessoal atualizada com sucesso",
        "nome_arquivo": arquivo.filename,
        "tamanho": len(conteudo)
    }


@router.get("/configuracoes/usuario/assinatura")
def obter_assinatura_usuario(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém a assinatura do usuário"""
    from fastapi.responses import Response
    
    config = db.query(ConfiguracaoUsuario).filter(
        ConfiguracaoUsuario.user_id == current_user.id
    ).first()
    
    if not config or not config.assinatura_dados:
        raise HTTPException(status_code=404, detail="Assinatura não encontrada")
    
    return Response(
        content=config.assinatura_dados,
        media_type=config.assinatura_tipo or "image/png"
    )
