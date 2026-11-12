from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.user import User
from app.services.auditoria_service import registrar_auditoria
from app.services.whatsapp_agenda_service import (
    AgendaUtilityTemplateKey,
    WhatsAppAgendaDeliveryError,
    build_agenda_utility_template,
    build_reservation_template,
    process_button_response,
    send_agenda_utility_template,
    send_reservation_template,
)
from app.services.whatsapp_bot_queue_service import enqueue_job_for_inbound_message
from app.services.whatsapp_reminder_scheduler_service import (
    is_reminder_scheduler_enabled_in_db,
    list_clinicas_prontidao_whatsapp_lembrete,
    list_eligible_agendamentos_preview,
)
from app.services.push_notifications import send_whatsapp_message_push_notification
from app.services.agenda_formalizacao_service import (
    build_formalizacao_url,
    criar_ou_reutilizar_convite,
    obter_contexto_publico,
    obter_convite_valido,
    processar_submissao,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ReservationSendRequest(BaseModel):
    destination: str = Field(..., min_length=10, max_length=32)
    recipient_type: Literal["clinica", "tutor"]
    idempotency_key: str = Field(..., min_length=8, max_length=128)


class ReservationButtonResponseRequest(BaseModel):
    provider_message_id: str = Field(..., min_length=8, max_length=160)
    outbound_message_id: str | None = Field(default=None, max_length=160)
    agendamento_id: int = Field(..., gt=0)
    action: Literal["confirmar", "confirmar_presenca", "solicitar_alteracao", "falar_equipe"]
    from_phone: str = Field(..., min_length=10, max_length=32)


class AgendaUtilityTemplateSendRequest(BaseModel):
    destination: str = Field(..., min_length=10, max_length=32)
    recipient_type: Literal["clinica", "tutor"]
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    template_key: AgendaUtilityTemplateKey


class AgendaFormalizacaoSubmitRequest(BaseModel):
    nome_paciente: str = Field(..., min_length=1, max_length=200)
    nome_tutor: str = Field(..., min_length=1, max_length=200)
    telefone_tutor: str = Field(default="", max_length=32)


class WhatsAppInboundMessageNotificationRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)
    contact_label: str = Field(default="", max_length=160)
    body_preview: str = Field(default="", max_length=500)
    # Opcionais (RF-001): os dois servicos tem deploys independentes, entao um
    # Node antigo (sem esses campos) ou um Python antigo (que os ignora)
    # precisam continuar funcionando - a reconciliacao (RF-006) cobre o caso
    # de o gatilho nao trazer esses dados.
    wa_phone_number: Optional[str] = Field(default=None, max_length=32)
    wa_message_id: Optional[str] = Field(default=None, max_length=160)
    message_type: Optional[str] = Field(default=None, max_length=32)
    message_timestamp: Optional[datetime] = None


def _require_internal_token(
    x_fortcordis_whatsapp_token: str | None = Header(default=None),
) -> None:
    configured = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "").strip()
    supplied = str(x_fortcordis_whatsapp_token or "").strip()
    if not configured or not supplied or not secrets.compare_digest(configured, supplied):
        raise HTTPException(status_code=401, detail="Credencial interna do WhatsApp invalida.")


@router.post("/agenda/{agendamento_id}/whatsapp/reserva")
def send_reservation(
    agendamento_id: int,
    payload: ReservationSendRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if agendamento is None:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")

    template = build_reservation_template(
        db,
        agendamento=agendamento,
        destination=payload.destination,
        recipient_type=payload.recipient_type,
    )
    try:
        result = send_reservation_template(
            agendamento_id=agendamento.id,
            template=template,
            idempotency_key=payload.idempotency_key,
        )
    except WhatsAppAgendaDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=agendamento.id,
        acao="RESERVA_WHATSAPP_TEMPLATE_ENVIADO",
        descricao="Modelo de reserva enviado pela WhatsApp Cloud API.",
        detalhes={
            "recipient_type": payload.recipient_type,
            "destination_suffix": template.destination[-4:],
            "provider_message_id": result.get("message_id"),
            "idempotent": bool(result.get("idempotent")),
        },
        request=request,
    )
    return result


@router.post("/agenda/{agendamento_id}/whatsapp/modelo")
def send_agenda_utility(
    agendamento_id: int,
    payload: AgendaUtilityTemplateSendRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if agendamento is None:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")

    template = build_agenda_utility_template(
        db,
        agendamento=agendamento,
        destination=payload.destination,
        recipient_type=payload.recipient_type,
        template_key=payload.template_key,
    )
    try:
        result = send_agenda_utility_template(
            agendamento_id=agendamento.id,
            template=template,
            idempotency_key=payload.idempotency_key,
        )
    except WhatsAppAgendaDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    registrar_auditoria(
        current_user=current_user,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=agendamento.id,
        acao="AGENDA_WHATSAPP_MODELO_ENVIADO",
        descricao="Modelo aprovado da Agenda enviado pela WhatsApp Cloud API.",
        detalhes={
            "template_key": payload.template_key,
            "recipient_type": payload.recipient_type,
            "destination_suffix": template.destination[-4:],
            "provider_message_id": result.get("message_id"),
            "idempotent": bool(result.get("idempotent")),
        },
        request=request,
    )
    return result


@router.post("/integracoes/whatsapp/agenda/respostas")
def receive_button_response(
    payload: ReservationButtonResponseRequest,
    request: Request,
    _authenticated: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
):
    result, idempotent = process_button_response(
        db,
        provider_message_id=payload.provider_message_id,
        outbound_message_id=payload.outbound_message_id,
        agendamento_id=payload.agendamento_id,
        action=payload.action,
        from_phone=payload.from_phone,
    )
    result = {**result, "idempotent": idempotent}

    registrar_auditoria(
        current_user=None,
        modulo="agenda",
        entidade="agendamento",
        entidade_id=payload.agendamento_id,
        acao="RESERVA_WHATSAPP_RESPOSTA_PROCESSADA",
        descricao="Resposta de botao do WhatsApp processada.",
        detalhes={
            "provider_message_id": payload.provider_message_id,
            "action": payload.action,
            "result": result.get("result"),
            "idempotent": idempotent,
        },
        request=request,
    )

    if not idempotent:
        try:
            from app.api.v1.endpoints.agenda import _notificar_agenda_update

            _notificar_agenda_update(
                db,
                action="whatsapp_reserva_resposta",
                agendamento_id=payload.agendamento_id,
                data=result,
            )
        except Exception:
            pass
    return result


@router.get("/agenda/whatsapp/lembrete-preview")
def preview_whatsapp_reminder_eligibility(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista os agendamentos elegiveis para o lembrete automatico agora,
    sem enviar nenhuma mensagem. Serve para inspecionar o alcance real antes
    de habilitar o lembrete automatico em Configuracoes.
    """
    now = datetime.now(timezone.utc)
    agendamentos = list_eligible_agendamentos_preview(db, now=now)
    return {
        "checked_at": now.isoformat(),
        "reminder_scheduler_enabled": is_reminder_scheduler_enabled_in_db(),
        "whatsapp_agenda_enabled": bool(settings.WHATSAPP_AGENDA_ENABLED),
        "window_hours": settings.WHATSAPP_REMINDER_WINDOW_HOURS,
        "min_lead_minutes": settings.WHATSAPP_REMINDER_MIN_LEAD_MINUTES,
        "recipient_type": settings.WHATSAPP_REMINDER_RECIPIENT_TYPE,
        "count": len(agendamentos),
        "agendamentos": agendamentos,
    }


@router.get("/agenda/whatsapp/lembrete-clinicas-prontidao")
def preview_whatsapp_reminder_clinicas_prontidao(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Audita todas as clinicas parceiras ativas quanto ao numero de
    WhatsApp que o lembrete automatico usaria, sem enviar nada. Serve para
    revisar e corrigir cadastros antes de habilitar o lembrete automatico
    em Configuracoes.
    """
    return list_clinicas_prontidao_whatsapp_lembrete(db)


@router.get("/agenda/formalizacao/{token}")
def get_formalizacao_context(token: str, db: Session = Depends(get_db)):
    """Contexto publico (sem autenticacao) para a clinica conferir o

    agendamento antes de preencher os dados do paciente/tutor - acesso
    protegido apenas pelo token opaco do link.
    """
    invite = obter_convite_valido(db, token)
    return obter_contexto_publico(db, invite)


@router.post("/agenda/formalizacao/{token}")
def submit_formalizacao(
    token: str,
    payload: AgendaFormalizacaoSubmitRequest,
    db: Session = Depends(get_db),
):
    invite = obter_convite_valido(db, token)
    agendamento = processar_submissao(
        db,
        invite=invite,
        nome_paciente=payload.nome_paciente,
        nome_tutor=payload.nome_tutor,
        telefone_tutor=payload.telefone_tutor,
    )
    return {"agendamento_id": agendamento.id, "status": agendamento.status}


@router.post("/integracoes/whatsapp/agenda/{agendamento_id}/link-formalizacao")
def gerar_link_formalizacao(
    agendamento_id: int,
    _authenticated: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
):
    """Chamado pelo whatsapp-stage-backend quando a clinica clica em

    "Enviar dados" no modelo de dados pendentes - gera um convite novo e
    devolve o link publico para ser enviado como texto livre na conversa.
    """
    agendamento = db.query(Agendamento).filter(Agendamento.id == agendamento_id).first()
    if agendamento is None:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")

    invite, raw_token = criar_ou_reutilizar_convite(db, agendamento)
    return {
        "link": build_formalizacao_url(raw_token),
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
    }


@router.post("/integracoes/whatsapp/notificacoes/mensagem-recebida")
def notify_whatsapp_inbound_message(
    payload: WhatsAppInboundMessageNotificationRequest,
    _authenticated: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
):
    """Dispara push (broadcast, todo mundo com preferencia habilitada) para

    cada mensagem nova recebida no WhatsApp. Chamado pelo whatsapp-stage-backend
    a cada mensagem inbound persistida - nunca deve bloquear o webhook, por
    isso so retorna as contagens de envio, sem side effect alem do push.

    Tambem enfileira um job do bot de atendimento (RF-002), isolado em seu
    proprio try/except: falha ao enfileirar nunca pode alterar a resposta do
    push nem propagar erro para o Node, que usa timeout de 5s e engole
    excecoes.
    """
    result = send_whatsapp_message_push_notification(
        db,
        conversation_id=payload.conversation_id,
        contact_label=payload.contact_label,
        body_preview=payload.body_preview,
    )

    bot_job_enqueued = False
    try:
        if payload.wa_phone_number and payload.wa_message_id:
            bot_job_enqueued = enqueue_job_for_inbound_message(
                db,
                wa_identity=payload.wa_phone_number,
                conversation_id=payload.conversation_id,
                wa_message_id=payload.wa_message_id,
                message_type=payload.message_type,
            )
    except Exception:
        logger.exception(
            "Falha ao enfileirar job do bot de atendimento WhatsApp para conversation_id=%s",
            payload.conversation_id,
        )

    result["bot_job_enqueued"] = bot_job_enqueued
    return result
