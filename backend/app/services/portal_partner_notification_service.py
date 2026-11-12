from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_VETERINARIO,
    PortalPartnerProfile,
)
from app.models.portal_partner_auth import PortalPartnerAccount
from app.services.portal_clinic_auth_service import mask_email, normalize_email
from app.services.portal_delivery_service import PortalDeliveryError, send_portal_email_message

LOCAL_TZ = timezone(timedelta(hours=-3))


@dataclass(frozen=True)
class PortalPartnerReleaseNotificationResult:
    status: str
    destination_masked: str | None = None
    provider: str | None = None
    reason: str | None = None


def _as_local_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _format_datetime(value: datetime | None) -> str:
    local_value = _as_local_datetime(value)
    if local_value is None:
        return "agora"
    return local_value.strftime("%d/%m/%Y às %H:%M")


def _build_partner_portal_url(request: Request | None) -> str:
    if request is None:
        return "/veterinario-parceiro"
    return f"{str(request.base_url).rstrip('/')}/veterinario-parceiro"


def resolve_partner_release_notification_email(db: Session, partner_id: int) -> str | None:
    account = (
        db.query(PortalPartnerAccount)
        .filter(
            PortalPartnerAccount.partner_id == partner_id,
            PortalPartnerAccount.revoked_at.is_(None),
        )
        .order_by(PortalPartnerAccount.id.desc())
        .first()
    )
    account_email = normalize_email(getattr(account, "email_normalized", None))
    if account_email:
        return account_email

    partner = (
        db.query(PortalPartnerProfile)
        .filter(
            PortalPartnerProfile.id == partner_id,
            PortalPartnerProfile.tipo == PORTAL_PARTNER_TYPE_VETERINARIO,
        )
        .first()
    )
    fallback_email = normalize_email(getattr(partner, "email_login", None))
    return fallback_email or None


def notify_partner_report_released(
    *,
    db: Session,
    request: Request | None,
    partner_id: int,
    partner_nome: str | None,
    tipo_exame: str,
    paciente_nome: str | None,
    tutor_nome: str | None = None,
    released_at: datetime | None = None,
) -> PortalPartnerReleaseNotificationResult:
    destination = resolve_partner_release_notification_email(db, partner_id)
    if not destination:
        return PortalPartnerReleaseNotificationResult(status="skipped", reason="no_recipient")

    subject = f"Novo laudo liberado no portal - {tipo_exame}"
    body_lines = [
        f"Ola, {partner_nome or 'parceiro(a)'}.",
        "",
        "A Fort Cordis liberou um novo laudo no portal do veterinario parceiro.",
        f"Exame: {tipo_exame}",
    ]
    if paciente_nome:
        body_lines.append(f"Pet: {paciente_nome}")
    if tutor_nome:
        body_lines.append(f"Tutor: {tutor_nome}")
    body_lines.extend(
        [
            f"Liberado em: {_format_datetime(released_at)}",
            "",
            "Acesse o portal para consultar o resultado e baixar o PDF:",
            _build_partner_portal_url(request),
            "",
            "Se precisar ajustar o acesso, fale com a Fort Cordis.",
        ]
    )

    try:
        result = send_portal_email_message(
            destination=destination,
            subject=subject,
            body="\n".join(body_lines),
        )
    except PortalDeliveryError as exc:
        return PortalPartnerReleaseNotificationResult(
            status="failed",
            destination_masked=mask_email(destination),
            reason=exc.__class__.__name__,
        )

    return PortalPartnerReleaseNotificationResult(
        status="sent",
        destination_masked=mask_email(destination),
        provider=result.provider,
    )
