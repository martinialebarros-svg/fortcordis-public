from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.whatsapp_agenda_resposta import WhatsappAgendaResposta
from app.services.alerta_interno_service import criar_alerta_interno
from app.services.laudo_agilidade_service import resolver_servico_nome
from app.services.whatsapp_template_delivery_service import (
    WhatsAppTemplateDeliveryError,
    WhatsAppTemplatePendingApproval,
    send_approved_utility_template,
)


Action = Literal["confirmar", "confirmar_presenca", "solicitar_alteracao", "falar_equipe"]
RecipientType = Literal["clinica", "tutor"]
AgendaUtilityTemplateKey = Literal[
    "appointmentReminder",
    "appointmentReminderService",
    "appointmentChange",
    "appointmentCancellation",
    "appointmentMissingData",
    "appointmentFormalized",
]
LOCAL_TZ = timezone(timedelta(hours=-3))


class WhatsAppAgendaDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class WhatsAppReservationTemplate:
    destination: str
    recipient_name: str
    pet_name: str
    appointment_date: str
    appointment_time: str
    confirmation_deadline: str


@dataclass(frozen=True)
class WhatsAppAgendaUtilityTemplate:
    template_key: AgendaUtilityTemplateKey
    destination: str
    parameters: tuple[str, ...]


def normalize_whatsapp_number(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or "")).lstrip("0")
    if len(digits) in {10, 11}:
        digits = f"55{digits}"
    if not 12 <= len(digits) <= 15:
        raise HTTPException(status_code=422, detail="Numero de WhatsApp invalido.")
    return digits


def _as_local_display(value: datetime | None, *, include_date: bool) -> str:
    if value is None:
        raise HTTPException(status_code=409, detail="A reserva nao possui data ou prazo valido.")
    local_value = value.astimezone(LOCAL_TZ) if value.tzinfo else value
    if include_date:
        return f"{local_value.strftime('%d/%m/%Y')} às {local_value.strftime('%H:%M')}"
    return local_value.strftime("%H:%M")


def _allowed_numbers(values: list[Any]) -> set[str]:
    allowed: set[str] = set()
    for value in values:
        candidates = value if isinstance(value, (list, tuple)) else [value]
        for candidate in candidates:
            try:
                allowed.add(normalize_whatsapp_number(candidate))
            except HTTPException:
                continue
    return allowed


PLACEHOLDER_PET_NAME = "seu pet"


def _resolver_paciente_tutor_opcionais(
    db: Session, agendamento: Agendamento
) -> tuple[Optional[Paciente], Optional[Tutor]]:
    """Busca paciente/tutor vinculados a reserva, sem exigir que existam.

    Uma reserva pode (e normalmente comeca assim) nao ter paciente/tutor
    ainda vinculados - essa e a razao dela ser uma reserva e nao um
    agendamento direto. So gera erro se o vinculo APONTA para um registro
    inexistente (dado corrompido/orfao) ou se paciente e tutor vinculados
    sao inconsistentes entre si - nunca por simples ausencia.
    """
    paciente: Optional[Paciente] = None
    if agendamento.paciente_id:
        paciente = db.query(Paciente).filter(Paciente.id == agendamento.paciente_id).first()
        if paciente is None:
            raise HTTPException(status_code=409, detail="Paciente vinculado a reserva nao foi encontrado.")

    tutor: Optional[Tutor] = None
    if agendamento.tutor_id:
        tutor = db.query(Tutor).filter(Tutor.id == agendamento.tutor_id).first()
        if tutor is None:
            raise HTTPException(status_code=409, detail="Tutor vinculado a reserva nao foi encontrado.")

    if paciente is not None and tutor is not None and int(paciente.tutor_id or 0) != int(tutor.id):
        raise HTTPException(status_code=409, detail="Paciente e tutor vinculados a reserva sao inconsistentes.")

    return paciente, tutor


def build_reservation_template(
    db: Session,
    *,
    agendamento: Agendamento,
    destination: str,
    recipient_type: RecipientType,
) -> WhatsAppReservationTemplate:
    if str(agendamento.status or "").strip() != "Reservado":
        raise HTTPException(status_code=409, detail="Somente reservas ativas podem usar este modelo.")

    now = datetime.now(timezone.utc)
    deadline = agendamento.reserva_expira_em
    deadline_utc = deadline.astimezone(timezone.utc) if deadline and deadline.tzinfo else deadline
    if deadline_utc is None or deadline_utc <= now.replace(tzinfo=None if deadline_utc.tzinfo is None else timezone.utc):
        raise HTTPException(status_code=409, detail="A reserva expirou e nao pode ser enviada automaticamente.")

    paciente, tutor = _resolver_paciente_tutor_opcionais(db, agendamento)
    if recipient_type == "tutor" and tutor is None:
        raise HTTPException(
            status_code=409,
            detail="Vincule o tutor antes de enviar a reserva diretamente para ele pelo WhatsApp.",
        )

    normalized_destination = normalize_whatsapp_number(destination)
    if recipient_type == "clinica":
        clinica = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first()
        if clinica is None:
            raise HTTPException(status_code=409, detail="Clinica da reserva nao encontrada.")
        allowed = _allowed_numbers([clinica.whatsapps, clinica.telefone])
        recipient_name = str(clinica.nome or "Clinica").strip()
    else:
        allowed = _allowed_numbers([tutor.whatsapp, tutor.telefone])
        recipient_name = str(tutor.nome or "Tutor").strip()

    if normalized_destination not in allowed:
        raise HTTPException(
            status_code=422,
            detail="O numero escolhido nao pertence ao destinatario cadastrado nesta reserva.",
        )

    appointment = agendamento.inicio
    if appointment is None:
        raise HTTPException(status_code=409, detail="A reserva nao possui horario valido.")
    appointment_local = appointment.astimezone(LOCAL_TZ) if appointment.tzinfo else appointment

    return WhatsAppReservationTemplate(
        destination=normalized_destination,
        recipient_name=recipient_name[:120],
        pet_name=(str(paciente.nome).strip()[:120] if paciente and paciente.nome else PLACEHOLDER_PET_NAME),
        appointment_date=appointment_local.strftime("%d/%m/%Y"),
        appointment_time=appointment_local.strftime("%H:%M"),
        confirmation_deadline=_as_local_display(deadline, include_date=True),
    )


def build_agenda_utility_template(
    db: Session,
    *,
    agendamento: Agendamento,
    destination: str,
    recipient_type: RecipientType,
    template_key: AgendaUtilityTemplateKey,
) -> WhatsAppAgendaUtilityTemplate:
    status_registrado = str(agendamento.status or "").strip()
    status = status_registrado or "Agendado"
    if template_key == "appointmentReminderService" and status_registrado not in {"Agendado", "Confirmado"}:
        raise HTTPException(
            status_code=409,
            detail="O lembrete com serviço exige um agendamento Agendado ou Confirmado; reservas usam o modelo de reserva.",
        )
    if template_key == "appointmentCancellation":
        if status != "Cancelado":
            raise HTTPException(
                status_code=409,
                detail="O modelo de cancelamento exige um agendamento cancelado.",
            )
    elif status not in {"Agendado", "Reservado", "Confirmado"}:
        raise HTTPException(
            status_code=409,
            detail="Este modelo so pode ser enviado para um agendamento ativo.",
        )

    if template_key == "appointmentMissingData":
        # E exatamente o modelo usado para pedir esses dados - nao faz
        # sentido exigir que eles ja existam para poder enviar o pedido.
        paciente, tutor = _resolver_paciente_tutor_opcionais(db, agendamento)
        if recipient_type == "tutor" and tutor is None:
            raise HTTPException(
                status_code=409,
                detail="Vincule o tutor antes de enviar este modelo diretamente para ele pelo WhatsApp.",
            )
    else:
        paciente = db.query(Paciente).filter(Paciente.id == agendamento.paciente_id).first()
        tutor = db.query(Tutor).filter(Tutor.id == agendamento.tutor_id).first()
        if paciente is None or tutor is None or int(paciente.tutor_id or 0) != int(tutor.id):
            raise HTTPException(
                status_code=409,
                detail="Vincule o animal e o tutor antes de enviar este modelo pelo WhatsApp.",
            )

    normalized_destination = normalize_whatsapp_number(destination)
    if recipient_type == "clinica":
        clinica = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first()
        if clinica is None:
            raise HTTPException(status_code=409, detail="Clinica do agendamento nao encontrada.")
        allowed = _allowed_numbers([clinica.whatsapps, clinica.telefone])
        recipient_name = str(clinica.nome or "Clinica").strip()
    else:
        allowed = _allowed_numbers([tutor.whatsapp, tutor.telefone])
        recipient_name = str(tutor.nome or "Tutor").strip()

    if normalized_destination not in allowed:
        raise HTTPException(
            status_code=422,
            detail="O numero escolhido nao pertence ao destinatario cadastrado neste agendamento.",
        )

    appointment = agendamento.inicio
    if appointment is None:
        raise HTTPException(status_code=409, detail="O agendamento nao possui horario valido.")
    appointment_local = appointment.astimezone(LOCAL_TZ) if appointment.tzinfo else appointment
    pet_name = str(paciente.nome).strip()[:120] if paciente and paciente.nome else PLACEHOLDER_PET_NAME

    if template_key == "appointmentFormalized":
        clinica_registro = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first()
        unidade_nome = str((clinica_registro.nome if clinica_registro else None) or agendamento.clinica or "").strip()
        servico_nome = str(agendamento.servico or "").strip() or "atendimento"
        tutor_nome = str(tutor.nome).strip()[:120] if tutor and tutor.nome else "seu tutor"
        parameters: tuple[str, ...] = (
            recipient_name[:120],
            servico_nome[:120],
            pet_name,
            tutor_nome,
            appointment_local.strftime("%d/%m/%Y"),
            appointment_local.strftime("%H:%M"),
            unidade_nome[:120] or "Fort Cordis",
        )
    else:
        parameters = (
            recipient_name[:120],
            pet_name,
            appointment_local.strftime("%d/%m/%Y"),
            appointment_local.strftime("%H:%M"),
        )
        if template_key == "appointmentReminderService":
            servico_nome = " ".join(str(resolver_servico_nome(
                db, agendamento.servico_id, agendamento.servico,
            ) or "").split())
            if not servico_nome:
                servico_nome = " ".join(str(agendamento.servico or "").split())
            if not servico_nome:
                raise HTTPException(
                    status_code=409,
                    detail="Informe o serviço do agendamento antes de enviar o lembrete pelo WhatsApp.",
                )
            if len(servico_nome) > 300:
                # Mesmo limite de parâmetro do serviço Node; preservar o
                # nome inteiro evita esconder parte de um combo agendado.
                raise HTTPException(
                    status_code=409,
                    detail="Revise o nome do serviço agendado: ele excede o limite do modelo de WhatsApp.",
                )
            parameters += (servico_nome,)

    return WhatsAppAgendaUtilityTemplate(
        template_key=template_key,
        destination=normalized_destination,
        parameters=parameters,
    )


def send_reservation_template(
    *,
    agendamento_id: int,
    template: WhatsAppReservationTemplate,
    idempotency_key: str,
) -> dict[str, Any]:
    if not settings.WHATSAPP_AGENDA_ENABLED:
        raise HTTPException(status_code=503, detail="Envio automatico do WhatsApp ainda nao esta habilitado.")

    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Integracao interna do WhatsApp nao configurada.")

    base_url = str(settings.WHATSAPP_AGENDA_SERVICE_URL or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="Servico interno do WhatsApp nao configurado.")

    body = {
        "reservation_id": agendamento_id,
        "destination": template.destination,
        "idempotency_key": idempotency_key,
        "parameters": {
            "recipient_name": template.recipient_name,
            "pet_name": template.pet_name,
            "appointment_date": template.appointment_date,
            "appointment_time": template.appointment_time,
            "confirmation_deadline": template.confirmation_deadline,
        },
    }
    try:
        response = httpx.post(
            f"{base_url}/automation/agenda/reservations",
            json=body,
            headers={"X-WhatsApp-Internal-Token": token},
            timeout=max(1, int(settings.WHATSAPP_AGENDA_TIMEOUT_SECONDS or 15)),
        )
    except httpx.HTTPError as exc:
        raise WhatsAppAgendaDeliveryError("Servico do WhatsApp indisponivel.") from exc

    if response.status_code >= 400:
        try:
            provider_detail = response.json().get("error")
        except Exception:
            provider_detail = None
        raise WhatsAppAgendaDeliveryError(str(provider_detail or "Falha ao enviar a reserva pelo WhatsApp."))

    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("message_id"):
        raise WhatsAppAgendaDeliveryError("Resposta invalida do servico do WhatsApp.")
    return payload


def send_agenda_utility_template(
    *,
    agendamento_id: int,
    template: WhatsAppAgendaUtilityTemplate,
    idempotency_key: str,
) -> dict[str, Any]:
    try:
        return send_approved_utility_template(
            template_key=template.template_key,
            subject_type="agendamento",
            subject_id=agendamento_id,
            destination=template.destination,
            parameters=template.parameters,
            idempotency_key=idempotency_key,
        )
    except WhatsAppTemplatePendingApproval as exc:
        if template.template_key == "appointmentReminderService":
            raise HTTPException(
                status_code=409, detail="O lembrete com serviço aguarda aprovação da Meta.",
            ) from exc
        raise WhatsAppAgendaDeliveryError(str(exc)) from exc
    except WhatsAppTemplateDeliveryError as exc:
        raise WhatsAppAgendaDeliveryError(str(exc)) from exc


def _result_payload(record: WhatsappAgendaResposta) -> dict[str, Any]:
    try:
        parsed = json.loads(record.result_json or "{}")
    except Exception:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def process_button_response(
    db: Session,
    *,
    provider_message_id: str,
    outbound_message_id: str | None,
    agendamento_id: int,
    action: Action,
    from_phone: str,
) -> tuple[dict[str, Any], bool]:
    existing = (
        db.query(WhatsappAgendaResposta)
        .filter(WhatsappAgendaResposta.provider_message_id == provider_message_id)
        .first()
    )
    if existing is not None:
        return _result_payload(existing), True

    agendamento = (
        db.query(Agendamento)
        .filter(Agendamento.id == agendamento_id)
        .with_for_update()
        .first()
    )
    result = "agendamento_nao_encontrado"
    status_final: str | None = None

    if agendamento is not None:
        status_atual = str(agendamento.status or "").strip()
        status_final = status_atual
        if action == "solicitar_alteracao":
            criar_alerta_interno(
                db,
                tipo="whatsapp_reserva_solicitar_alteracao",
                nivel="aviso",
                titulo="Cliente solicitou alteracao do agendamento",
                mensagem=(
                    f"O destinatario {from_phone} pediu alteracao do agendamento #{agendamento.id}. "
                    "Revise o servico e o horario solicitados e entre em contato antes de modificar a agenda."
                ),
                entidade_tipo="agendamento",
                entidade_id=agendamento.id,
                clinica_id=agendamento.clinica_id,
            )
            result = "alteracao_solicitada"
        elif action == "falar_equipe":
            criar_alerta_interno(
                db,
                tipo="whatsapp_agenda_falar_equipe",
                nivel="aviso",
                titulo="Cliente pediu para falar com a equipe",
                mensagem=(
                    f"O destinatario {from_phone} pediu contato da equipe sobre o "
                    f"agendamento #{agendamento.id}."
                ),
                entidade_tipo="agendamento",
                entidade_id=agendamento.id,
                clinica_id=agendamento.clinica_id,
            )
            result = "falar_equipe_solicitado"
        elif action == "confirmar_presenca" and status_atual in {"Agendado", "Confirmado"}:
            # Confirmação de presença registra a resposta ao lembrete; não é
            # confirmação operacional de uma reserva nem alteração da agenda.
            result = "presenca_confirmada"
        elif status_atual == "Confirmado":
            result = "ja_confirmado"
        elif action == "confirmar_presenca" or status_atual != "Reservado":
            criar_alerta_interno(
                db,
                tipo="whatsapp_reserva_resposta_revisao",
                nivel="aviso",
                titulo="Resposta de WhatsApp exige revisao",
                mensagem=(
                    f"Foi recebida uma confirmacao para o agendamento #{agendamento.id}, "
                    f"mas o status atual e {status_atual or 'indefinido'}."
                ),
                entidade_tipo="agendamento",
                entidade_id=agendamento.id,
                clinica_id=agendamento.clinica_id,
            )
            result = "revisao_manual"
        else:
            deadline = agendamento.reserva_expira_em
            deadline_utc = deadline.astimezone(timezone.utc) if deadline and deadline.tzinfo else deadline
            now = datetime.now(timezone.utc)
            expired = deadline_utc is not None and deadline_utc <= now.replace(
                tzinfo=None if deadline_utc.tzinfo is None else timezone.utc
            )
            paciente = db.query(Paciente).filter(Paciente.id == agendamento.paciente_id).first()
            tutor = db.query(Tutor).filter(Tutor.id == agendamento.tutor_id).first()
            has_complete_registration = (
                paciente is not None
                and tutor is not None
                and int(paciente.tutor_id or 0) == int(tutor.id)
            )
            if expired:
                agendamento.status = "Expirado"
                status_final = "Expirado"
                criar_alerta_interno(
                    db,
                    tipo="whatsapp_reserva_confirmacao_atrasada",
                    nivel="critico",
                    titulo="Confirmacao recebida apos o prazo",
                    mensagem=(
                        f"O destinatario {from_phone} confirmou o agendamento #{agendamento.id} "
                        "depois do prazo. O horario nao foi reativado automaticamente."
                    ),
                    entidade_tipo="agendamento",
                    entidade_id=agendamento.id,
                    clinica_id=agendamento.clinica_id,
                )
                result = "confirmacao_apos_prazo"
            elif not has_complete_registration:
                criar_alerta_interno(
                    db,
                    tipo="whatsapp_reserva_confirmacao_dados_pendentes",
                    nivel="aviso",
                    titulo="Confirmacao recebida com cadastro pendente",
                    mensagem=(
                        f"O destinatario {from_phone} confirmou o agendamento #{agendamento.id}, "
                        "mas animal e tutor ainda precisam ser vinculados antes da confirmacao operacional."
                    ),
                    entidade_tipo="agendamento",
                    entidade_id=agendamento.id,
                    clinica_id=agendamento.clinica_id,
                )
                result = "confirmacao_dados_pendentes"
            else:
                confirmed_at = datetime.now(timezone.utc)
                agendamento.status = "Confirmado"
                agendamento.confirmado_por_id = None
                agendamento.confirmado_por_nome = "WhatsApp Fort Cordis"
                agendamento.confirmado_em = confirmed_at
                agendamento.updated_at = confirmed_at
                agendamento.atualizado_em = confirmed_at
                status_final = "Confirmado"
                result = "confirmado"

    response_payload = {
        "agendamento_id": agendamento_id,
        "action": action,
        "result": result,
        "status": status_final,
    }
    db.add(
        WhatsappAgendaResposta(
            provider_message_id=provider_message_id,
            outbound_message_id=outbound_message_id,
            agendamento_id=agendamento_id,
            action=action,
            from_phone=from_phone,
            result=result,
            result_json=json.dumps(response_payload, ensure_ascii=False),
        )
    )
    db.commit()
    return response_payload, False
