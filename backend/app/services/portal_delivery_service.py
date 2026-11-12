from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

import httpx

from app.core.config import settings


class PortalDeliveryError(RuntimeError):
    """Erro base para falhas na entrega do desafio do portal."""


class PortalDeliveryConfigurationError(PortalDeliveryError):
    """Configuracao ausente ou invalida para provider do portal."""


@dataclass(frozen=True)
class PortalChallengeDeliveryRequest:
    challenge_id: str
    actor_type: str
    actor_id: int
    channel: str
    destination: str
    code: str
    expires_in_minutes: int
    display_name: str | None = None
    paciente_nome: str | None = None
    clinica_nome: str | None = None
    responsavel_nome: str | None = None


@dataclass(frozen=True)
class PortalDeliveryResult:
    provider: str
    channel: str


def send_portal_email_message(*, destination: str, subject: str, body: str) -> PortalDeliveryResult:
    host = str(settings.PORTAL_EMAIL_SMTP_HOST or "").strip()
    from_email = str(settings.PORTAL_EMAIL_FROM_EMAIL or "").strip()
    if not host or not from_email:
        raise PortalDeliveryConfigurationError(
            "Provider de email do portal nao configurado."
        )

    msg = EmailMessage()
    from_name = str(settings.PORTAL_EMAIL_FROM_NAME or "").strip()
    msg["Subject"] = (subject or "").strip() or _render_email_subject()
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    msg["To"] = destination
    msg.set_content(body)

    port = int(settings.PORTAL_EMAIL_SMTP_PORT or 587)
    username = str(settings.PORTAL_EMAIL_SMTP_USERNAME or "").strip()
    password = str(settings.PORTAL_EMAIL_SMTP_PASSWORD or "")
    use_ssl = bool(settings.PORTAL_EMAIL_SMTP_USE_SSL)
    use_tls = bool(settings.PORTAL_EMAIL_SMTP_USE_TLS)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
    except Exception as exc:
        raise PortalDeliveryError("Falha ao enviar mensagem por email.") from exc

    return PortalDeliveryResult(provider="smtp", channel="email")


def _render_email_subject() -> str:
    return str(settings.PORTAL_EMAIL_SUBJECT or "").strip() or "Seu codigo de acesso - Portal Fort Cordis"


def _render_email_body(payload: PortalChallengeDeliveryRequest) -> str:
    saudacao = f"Ola, {payload.display_name}." if payload.display_name else "Ola."
    contexto = ""
    if payload.actor_type == "tutor" and payload.paciente_nome:
        contexto = f"\nPet: {payload.paciente_nome}\n"
    elif payload.actor_type == "clinica" and payload.clinica_nome:
        contexto = f"\nClinica: {payload.clinica_nome}\n"

    return (
        f"{saudacao}\n\n"
        "Seu codigo temporario para acesso ao Portal Fort Cordis e:\n\n"
        f"{payload.code}\n\n"
        f"Este codigo expira em {payload.expires_in_minutes} minuto(s).\n"
        f"{contexto}\n"
        "Se voce nao solicitou este acesso, ignore esta mensagem.\n"
    )


def _render_whatsapp_message(payload: PortalChallengeDeliveryRequest) -> str:
    identificacao = payload.display_name or payload.responsavel_nome or "cliente"
    contexto = ""
    if payload.actor_type == "tutor" and payload.paciente_nome:
        contexto = f" Pet: {payload.paciente_nome}."
    elif payload.actor_type == "clinica" and payload.clinica_nome:
        contexto = f" Clinica: {payload.clinica_nome}."

    return (
        f"Fort Cordis: ola, {identificacao}. "
        f"Seu codigo de acesso e {payload.code}. "
        f"Ele expira em {payload.expires_in_minutes} minuto(s)."
        f"{contexto}"
    )


def _send_email_code(payload: PortalChallengeDeliveryRequest) -> PortalDeliveryResult:
    return send_portal_email_message(
        destination=payload.destination,
        subject=_render_email_subject(),
        body=_render_email_body(payload),
    )


def _build_whatsapp_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    header_name = str(settings.PORTAL_WHATSAPP_WEBHOOK_AUTH_HEADER or "").strip() or "Authorization"
    token = str(settings.PORTAL_WHATSAPP_WEBHOOK_AUTH_TOKEN or "").strip()
    if token:
        if header_name.lower() == "authorization" and not token.lower().startswith(("bearer ", "basic ")):
            headers[header_name] = f"Bearer {token}"
        else:
            headers[header_name] = token
    return headers


def send_portal_whatsapp_message(
    *,
    destination: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> PortalDeliveryResult:
    webhook_url = str(settings.PORTAL_WHATSAPP_WEBHOOK_URL or "").strip()
    if not webhook_url:
        raise PortalDeliveryConfigurationError(
            "Provider de WhatsApp do portal nao configurado."
        )

    body = {
        "channel": "whatsapp",
        "destination": destination,
        "message": message,
    }
    if metadata:
        body.update(metadata)

    try:
        response = httpx.request(
            str(settings.PORTAL_WHATSAPP_WEBHOOK_METHOD or "POST").strip().upper() or "POST",
            webhook_url,
            json=body,
            headers=_build_whatsapp_headers(),
            timeout=max(1, int(settings.PORTAL_WHATSAPP_WEBHOOK_TIMEOUT_SECONDS or 10)),
        )
        response.raise_for_status()
    except Exception as exc:
        raise PortalDeliveryError("Falha ao enviar codigo por WhatsApp.") from exc

    return PortalDeliveryResult(provider="whatsapp_webhook", channel="whatsapp")


def _send_whatsapp_code(payload: PortalChallengeDeliveryRequest) -> PortalDeliveryResult:
    return send_portal_whatsapp_message(
        destination=payload.destination,
        message=_render_whatsapp_message(payload),
        metadata={
            "challenge_id": payload.challenge_id,
            "actor_type": payload.actor_type,
            "actor_id": payload.actor_id,
            "code": payload.code,
            "expires_in_minutes": payload.expires_in_minutes,
            "display_name": payload.display_name,
            "paciente_nome": payload.paciente_nome,
            "clinica_nome": payload.clinica_nome,
        },
    )


def send_portal_access_code(payload: PortalChallengeDeliveryRequest) -> PortalDeliveryResult:
    if payload.channel == "email":
        return _send_email_code(payload)
    if payload.channel == "whatsapp":
        if not settings.PORTAL_WHATSAPP_ENABLED:
            raise PortalDeliveryConfigurationError(
                "Canal WhatsApp do portal ainda nao esta habilitado."
            )
        return _send_whatsapp_code(payload)
    raise PortalDeliveryConfigurationError("Canal de entrega do portal nao suportado.")
