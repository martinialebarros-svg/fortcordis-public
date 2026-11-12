from __future__ import annotations

import json
import re
from typing import Any, Literal, Sequence

import httpx
from fastapi import HTTPException

from app.core.config import settings


ApprovedUtilityTemplateKey = Literal[
    "appointmentReminder",
    "appointmentReminderService",
    "appointmentChange",
    "appointmentCancellation",
    "appointmentMissingData",
    "appointmentFormalized",
    "portalReportAvailable",
    "portalReportLink",
    "homeReportPdf",
    "receiptAvailable",
    "receiptPdf",
    "receiptPdfBulk",
    "pendingPaymentReminder",
    "pendingPaymentReminderBulk",
    "portalClinicInviteActivation",
    "portalClinicInviteLoginAccess",
    "portalClinicInviteTemporaryPassword",
]
ApprovedTemplateSubject = Literal["agendamento", "exame", "laudo", "ordem_servico", "clinica"]


class WhatsAppTemplateDeliveryError(RuntimeError):
    pass


class WhatsAppCustomerWindowClosed(WhatsAppTemplateDeliveryError):
    pass


class WhatsAppTemplatePendingApproval(WhatsAppTemplateDeliveryError):
    pass


def send_approved_utility_template(
    *,
    template_key: ApprovedUtilityTemplateKey,
    subject_type: ApprovedTemplateSubject,
    subject_id: int,
    destination: str,
    parameters: Sequence[str],
    idempotency_key: str,
    subject_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    if not settings.WHATSAPP_AGENDA_ENABLED:
        raise HTTPException(status_code=503, detail="Envio automatico do WhatsApp ainda nao esta habilitado.")

    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "").strip()
    base_url = str(settings.WHATSAPP_AGENDA_SERVICE_URL or "").strip().rstrip("/")
    if not token or not base_url:
        raise HTTPException(status_code=503, detail="Integracao interna do WhatsApp nao configurada.")

    body = {
        "template_key": template_key,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_ids": list(subject_ids or [subject_id]),
        "destination": destination,
        "idempotency_key": idempotency_key,
        "parameters": list(parameters),
    }
    try:
        response = httpx.post(
            f"{base_url}/automation/templates",
            json=body,
            headers={"X-WhatsApp-Internal-Token": token},
            timeout=max(1, int(settings.WHATSAPP_AGENDA_TIMEOUT_SECONDS or 15)),
        )
    except httpx.HTTPError as exc:
        raise WhatsAppTemplateDeliveryError("Servico do WhatsApp indisponivel.") from exc

    if response.status_code >= 400:
        try:
            provider_payload = response.json()
            provider_detail = provider_payload.get("error")
        except Exception:
            provider_payload = {}
            provider_detail = None
        if (template_key == "appointmentReminderService" and response.status_code == 409
                and isinstance(provider_payload, dict)
                and provider_payload.get("code") == "WHATSAPP_TEMPLATE_APPROVAL_PENDING"):
            raise WhatsAppTemplatePendingApproval(
                str(provider_detail or "O lembrete com serviço aguarda aprovação da Meta.")
            )
        raise WhatsAppTemplateDeliveryError(str(provider_detail or "Falha ao enviar o modelo pelo WhatsApp."))

    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("message_id"):
        raise WhatsAppTemplateDeliveryError("Resposta invalida do servico do WhatsApp.")
    return payload


def send_approved_document_template(
    *,
    template_key: Literal["receiptPdf", "receiptPdfBulk", "homeReportPdf"],
    subject_type: Literal["ordem_servico", "laudo"] = "ordem_servico",
    subject_id: int,
    subject_ids: Sequence[int],
    destination: str,
    parameters: Sequence[str],
    idempotency_key: str,
    document_bytes: bytes,
    filename: str,
) -> dict[str, Any]:
    if not settings.WHATSAPP_AGENDA_ENABLED:
        raise HTTPException(status_code=503, detail="Envio automatico do WhatsApp ainda nao esta habilitado.")

    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "").strip()
    base_url = str(settings.WHATSAPP_AGENDA_SERVICE_URL or "").strip().rstrip("/")
    if not token or not base_url:
        raise HTTPException(status_code=503, detail="Integracao interna do WhatsApp nao configurada.")

    normalized_ids = list(dict.fromkeys(int(item) for item in subject_ids))
    if not normalized_ids or subject_id not in normalized_ids:
        raise WhatsAppTemplateDeliveryError("Referencia invalida para o PDF.")
    if (template_key == "homeReportPdf") != (subject_type == "laudo"):
        raise WhatsAppTemplateDeliveryError("Modelo de documento incompatível com o tipo de registro.")
    if not document_bytes or len(document_bytes) > 8 * 1024 * 1024 or not document_bytes.startswith(b"%PDF"):
        raise WhatsAppTemplateDeliveryError("O documento precisa ser um PDF valido de ate 8 MiB.")

    safe_filename = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(filename or "").strip()).lstrip(".")
    if not safe_filename or not safe_filename.lower().endswith(".pdf"):
        raise WhatsAppTemplateDeliveryError("Nome de arquivo PDF invalido.")

    form = {
        "template_key": template_key,
        "subject_type": subject_type,
        "subject_id": str(subject_id),
        "subject_ids": json.dumps(normalized_ids),
        "destination": destination,
        "idempotency_key": idempotency_key,
        "parameters": json.dumps(list(parameters), ensure_ascii=False),
        "filename": safe_filename,
    }
    try:
        response = httpx.post(
            f"{base_url}/automation/document-templates",
            data=form,
            files={"document": (safe_filename, document_bytes, "application/pdf")},
            headers={"X-WhatsApp-Internal-Token": token},
            timeout=max(30, int(settings.WHATSAPP_AGENDA_TIMEOUT_SECONDS or 15)),
        )
    except httpx.HTTPError as exc:
        raise WhatsAppTemplateDeliveryError("Servico do WhatsApp indisponivel para enviar o PDF.") from exc

    if response.status_code >= 400:
        try:
            error_payload = response.json()
            provider_detail = error_payload.get("error")
        except Exception:
            error_payload = {}
            provider_detail = None
        if error_payload.get("code") == "TEMPLATE_PENDING_APPROVAL":
            raise WhatsAppTemplatePendingApproval(str(provider_detail or "Modelo aguarda aprovacao da Meta."))
        raise WhatsAppTemplateDeliveryError(str(provider_detail or "Falha ao enviar o PDF pelo WhatsApp."))

    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("message_id") or not payload.get("media_id"):
        raise WhatsAppTemplateDeliveryError("Resposta invalida do servico do WhatsApp para o PDF.")
    return payload


def send_report_pdf_in_customer_window(
    *, laudo_id: int, destination: str, idempotency_key: str,
    document_bytes: bytes, filename: str,
) -> dict[str, Any]:
    """Send a report PDF only while the recipient's 24-hour service window is open."""
    if not settings.WHATSAPP_AGENDA_ENABLED:
        raise HTTPException(status_code=503, detail="WhatsApp nao esta habilitado.")
    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "").strip()
    base_url = str(settings.WHATSAPP_AGENDA_SERVICE_URL or "").strip().rstrip("/")
    if not token or not base_url:
        raise HTTPException(status_code=503, detail="Integracao interna do WhatsApp nao configurada.")
    if not document_bytes or len(document_bytes) > 8 * 1024 * 1024 or not document_bytes.startswith(b"%PDF"):
        raise WhatsAppTemplateDeliveryError("O laudo precisa ser um PDF valido de ate 8 MiB.")
    safe_filename = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename).lstrip(".")
    if not safe_filename or not safe_filename.lower().endswith(".pdf"):
        raise WhatsAppTemplateDeliveryError("Nome de arquivo PDF invalido.")
    try:
        response = httpx.post(
            f"{base_url}/automation/report-pdf",
            data={"laudo_id": str(laudo_id), "destination": destination,
                  "idempotency_key": idempotency_key, "filename": safe_filename},
            files={"document": (safe_filename, document_bytes, "application/pdf")},
            headers={"X-WhatsApp-Internal-Token": token},
            timeout=max(30, int(settings.WHATSAPP_AGENDA_TIMEOUT_SECONDS or 15)),
        )
    except httpx.HTTPError as exc:
        raise WhatsAppTemplateDeliveryError("Servico do WhatsApp indisponivel para enviar o laudo.") from exc
    if response.status_code >= 400:
        try:
            error_payload = response.json()
            detail = error_payload.get("error")
        except Exception:
            error_payload = {}
            detail = None
        if response.status_code == 409 and error_payload.get("code") == "CUSTOMER_WINDOW_CLOSED":
            raise WhatsAppCustomerWindowClosed(str(detail or "Janela de atendimento encerrada."))
        if response.status_code == 409:
            raise HTTPException(status_code=409, detail=str(detail or "Envio indisponivel nesta conversa."))
        raise WhatsAppTemplateDeliveryError(str(detail or "Falha ao enviar o laudo pelo WhatsApp."))
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("message_id"):
        raise WhatsAppTemplateDeliveryError("Resposta invalida do servico do WhatsApp.")
    return payload
