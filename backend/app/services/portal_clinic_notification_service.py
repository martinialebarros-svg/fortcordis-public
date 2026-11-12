from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.clinica import Clinica
from app.models.portal_clinic_auth import PortalClinicInvite
from app.services.portal_clinic_auth_service import (
    get_active_accounts_by_clinica,
    mask_email,
    normalize_email,
)
from app.services.portal_delivery_service import PortalDeliveryError, send_portal_email_message

LOCAL_TZ = timezone(timedelta(hours=-3))


@dataclass(frozen=True)
class PortalClinicReleaseNotificationResult:
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


def _build_clinic_portal_url(request: Request | None) -> str:
    if request is None:
        return "/clinica-parceira"
    return f"{str(request.base_url).rstrip('/')}/clinica-parceira"


def resolve_clinic_release_notification_emails(db: Session, clinica_id: int) -> list[str]:
    """Retorna o email de cada gestor com conta ativa na clinica; sem nenhum, cai para o ultimo convite/contato."""
    account_emails: list[str] = []
    seen: set[str] = set()
    for account in get_active_accounts_by_clinica(db, clinica_id):
        account_email = normalize_email(account.email_normalized)
        if account_email and account_email not in seen:
            seen.add(account_email)
            account_emails.append(account_email)
    if account_emails:
        return account_emails

    invite = (
        db.query(PortalClinicInvite)
        .filter(PortalClinicInvite.clinica_id == clinica_id)
        .order_by(PortalClinicInvite.id.desc())
        .first()
    )
    if invite and invite.contexto_json:
        try:
            context = invite.contexto_json if isinstance(invite.contexto_json, dict) else {}
        except Exception:
            context = {}
        if not context and isinstance(invite.contexto_json, str):
            import json

            try:
                parsed = json.loads(invite.contexto_json or "{}")
            except Exception:
                parsed = {}
            context = parsed if isinstance(parsed, dict) else {}
        invite_email = normalize_email(context.get("account_email"))
        if invite_email:
            return [invite_email]

    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    fallback_email = normalize_email(getattr(clinica, "email", None))
    return [fallback_email] if fallback_email else []


def notify_clinic_device_trusted(
    *,
    db: Session,
    request: Request | None,
    clinica_id: int,
    clinica_nome: str | None,
    device_label: str | None,
    trusted_until: datetime | None,
) -> PortalClinicReleaseNotificationResult:
    """Avisa os gestores que um computador da unidade foi conectado sem senha.

    E supervisao, nao autorizacao: a conexao ja aconteceu quando este aviso sai, e
    de proposito - exigir aprovacao do gestor reintroduziria exatamente o gargalo
    que a feature existe para eliminar. Falha de envio e devolvida no resultado;
    quem chama e responsavel por nao deixar isso derrubar a conexao.
    """
    destinations = resolve_clinic_release_notification_emails(db, clinica_id)
    if not destinations:
        return PortalClinicReleaseNotificationResult(status="skipped", reason="no_recipient")

    subject = "Um computador foi conectado ao portal da clinica"
    body = "\n".join(
        [
            f"Ola, equipe {clinica_nome or 'parceira'}.",
            "",
            "Um computador da unidade foi conectado ao Portal Fort Cordis para consultar",
            "laudos sem precisar digitar senha a cada acesso.",
            f"Identificacao: {device_label or 'computador da recepcao'}",
            f"Conectado em: {_format_datetime(datetime.utcnow())}",
            f"Acesso valido ate (sem uso): {_format_datetime(trusted_until)}",
            "",
            "Esse acesso mostra apenas exames e laudos da unidade. Financeiro, agenda e",
            "recibos continuam exigindo login com e-mail e senha.",
            "",
            "Se voce nao reconhece esse acesso, encerre em 'Sair deste computador' na",
            f"propria maquina, ou responda este email: {_build_clinic_portal_url(request)}",
        ]
    )

    sent_masked: list[str] = []
    provider: str | None = None
    last_failure_reason: str | None = None
    for destination in destinations:
        try:
            result = send_portal_email_message(destination=destination, subject=subject, body=body)
        except PortalDeliveryError as exc:
            last_failure_reason = exc.__class__.__name__
            continue
        provider = result.provider
        sent_masked.append(mask_email(destination))

    return PortalClinicReleaseNotificationResult(
        status="sent" if sent_masked else "failed",
        destination_masked=", ".join(sent_masked) or None,
        provider=provider,
        reason=last_failure_reason if not sent_masked else None,
    )


def notify_clinic_report_released(
    *,
    db: Session,
    request: Request | None,
    clinica_id: int,
    clinica_nome: str | None,
    tipo_exame: str,
    paciente_nome: str | None,
    tutor_nome: str | None = None,
    released_at: datetime | None = None,
) -> PortalClinicReleaseNotificationResult:
    destinations = resolve_clinic_release_notification_emails(db, clinica_id)
    if not destinations:
        return PortalClinicReleaseNotificationResult(status="skipped", reason="no_recipient")

    subject = f"Novo laudo liberado no portal - {tipo_exame}"
    body_lines = [
        f"Ola, equipe {clinica_nome or 'parceira'}.",
        "",
        "A Fort Cordis liberou um novo laudo no portal da clinica parceira.",
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
            _build_clinic_portal_url(request),
            "",
            "Se a unidade ainda nao tiver acesso configurado, responda este email ou fale com a Fort Cordis.",
        ]
    )
    body = "\n".join(body_lines)

    sent_masked: list[str] = []
    failed_masked: list[str] = []
    provider: str | None = None
    last_failure_reason: str | None = None
    for destination in destinations:
        try:
            result = send_portal_email_message(destination=destination, subject=subject, body=body)
        except PortalDeliveryError as exc:
            failed_masked.append(mask_email(destination))
            last_failure_reason = exc.__class__.__name__
            continue
        provider = result.provider
        sent_masked.append(mask_email(destination))

    if sent_masked and not failed_masked:
        status_value = "sent"
    elif sent_masked and failed_masked:
        status_value = "partially_sent"
    else:
        status_value = "failed"

    return PortalClinicReleaseNotificationResult(
        status=status_value,
        destination_masked=", ".join(sent_masked or failed_masked),
        provider=provider,
        reason=last_failure_reason if not sent_masked else None,
    )
