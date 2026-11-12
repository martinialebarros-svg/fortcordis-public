from __future__ import annotations

import json
import logging
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.endpoints import portal as portal_endpoints
from app.core.config import settings
from app.core.portal_security import PortalSessionContext, get_current_portal_session
from app.core.security import require_any_papel, require_papel
from app.db.database import get_db
from app.models.atendimento_clinico import AnexoAtendimento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.portal_clinic_auth import (
    PortalAuthChallenge,
    PortalClinicAccount,
    PortalClinicInvite,
    PortalClinicSession,
)
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.models.tutor import Tutor
from app.models.user import User
from app.schemas.portal import (
    PortalAdminClinicAccessOverviewItem,
    PortalAdminClinicAccessOverviewMetrics,
    PortalAdminClinicAccessOverviewResponse,
    PortalAdminClinicAccessSummaryResponse,
    PortalAdminClinicAccountRevokeRequest,
    PortalAdminClinicAccountRevokeResponse,
    PortalAdminClinicDownloadEventResponse,
    PortalAdminClinicInviteCreateRequest,
    PortalAdminClinicInviteRevokeRequest,
    PortalAdminClinicInviteRevokeResponse,
    PortalAdminClinicInviteResponse,
    PortalAdminClinicInviteSnapshot,
    PortalAdminClinicAccountSnapshot,
    PortalAdminClinicTimelineEventResponse,
    PortalAdminClinicSessionSnapshot,
    PortalAdminClinicSessionsRevokeRequest,
    PortalAdminClinicSessionsRevokeResponse,
    PortalAdminClinicTrustedDeviceSnapshot,
    PortalAdminDeviceRevokeRequest,
    PortalAdminDeviceRevokeResponse,
    PortalChallengeResponse,
    PortalClinicActivationRequest,
    PortalClinicActivationResponse,
    PortalClinicAuthResponse,
    PortalClinicInviteStatusResponse,
    PortalClinicLoginRequest,
    PortalClinicMfaVerifyRequest,
    PortalClinicPasswordChangeRequest,
    PortalCodeVerifyRequest,
    PortalDownloadUrlResponse,
    PortalExamListResponse,
    PortalPasswordResetConfirmRequest,
    PortalPasswordResetRequest,
    PortalSimpleAcceptedResponse,
)
from app.services.auditoria_service import registrar_auditoria
from app.services.portal_clinic_device_trust_service import (
    TRUST_STATUS_ACTIVE,
    revoke_trust,
    revoke_trusts_for_clinica,
)
from app.services.portal_clinic_auth_service import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_LOCKED,
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_REVOKED,
    CHALLENGE_TYPE_EMAIL_VERIFICATION,
    CHALLENGE_TYPE_LOGIN_MFA,
    INVITE_STATUS_PENDING,
    INVITE_STATUS_REVOKED,
    INVITE_STATUS_USED,
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_LOGGED_OUT,
    MAX_ACTIVE_CLINIC_MANAGERS,
    build_activation_url,
    build_clinic_portal_url,
    build_password_reset_url,
    clear_portal_refresh_cookie,
    count_active_clinic_manager_slots,
    create_auth_challenge,
    create_clinic_invite,
    create_or_replace_pending_account,
    create_password_reset_token,
    expire_invite_if_needed,
    gerar_senha_temporaria,
    get_account_by_email,
    get_active_clinica_or_404,
    get_invite_by_raw_token,
    get_password_reset_token,
    get_portal_refresh_cookie,
    get_session_by_refresh_token,
    generate_opaque_token,
    hash_password,
    hash_secret,
    issue_clinic_session,
    json_load_dict,
    mask_email,
    mask_phone,
    maybe_require_mfa,
    normalize_email,
    request_user_agent_hash,
    revoke_session,
    revoke_sessions_for_account,
    revoke_sessions_for_clinica,
    send_login_mfa_code,
    send_password_reset_email,
    send_whatsapp_invite,
    send_whatsapp_login_access,
    send_whatsapp_temporary_password,
    set_portal_refresh_cookie,
    utcnow,
    validate_password_reset_token_or_401,
    verify_auth_challenge_code,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter()
PORTAL_DOWNLOAD_AUDIT_ACTION = "PORTAL_DOWNLOAD_ARQUIVO"
PORTAL_RECENT_DOWNLOADS_LIMIT = 20
PORTAL_TIMELINE_LIMIT_PER_CLINICA = 8
PORTAL_TIMELINE_DOWNLOAD_LIMIT_PER_CLINICA = 6
PORTAL_INVITE_OPERATOR_ROLES = (
    "admin",
    "secretaria",
    "secretária",
    "recepcao",
    "recepção",
)


def _require_portal_admin(current_user: User = Depends(require_papel("admin"))) -> User:
    return current_user


def _require_portal_invite_operator(
    current_user: User = Depends(require_any_papel(*PORTAL_INVITE_OPERATOR_ROLES)),
) -> User:
    """Permite à operação enviar convites sem conceder poderes de revogação."""
    return current_user


def _assert_invite_auth_enabled() -> None:
    if not settings.PORTAL_CLINIC_INVITE_AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Fluxo de convite da clinica indisponivel.")


def _build_admin_preview_portal_session(*, clinica_id: int, clinica_nome: str) -> PortalSessionContext:
    return PortalSessionContext(
        actor_type="clinica",
        actor_id=clinica_id,
        paciente_id=None,
        clinica_id=clinica_id,
        challenge_id="admin-preview",
        display_name=f"Preview administrativo - {clinica_nome}",
        channel="admin",
        scope=tuple(portal_endpoints.PORTAL_SCOPE_CLINICA),
        expires_at=utcnow() + timedelta(minutes=30),
        auth_method="admin_preview",
    )


def _assert_password_login_enabled() -> None:
    _assert_invite_auth_enabled()
    if not settings.PORTAL_CLINIC_PASSWORD_LOGIN_ENABLED:
        raise HTTPException(status_code=404, detail="Login de clinica por senha indisponivel.")


def _generic_reset_response() -> PortalSimpleAcceptedResponse:
    return PortalSimpleAcceptedResponse(
        message="Se existir uma conta ativa para este email, enviaremos as instrucoes de redefinicao.",
    )


def _invite_snapshot(invite: PortalClinicInvite | None) -> PortalAdminClinicInviteSnapshot | None:
    if invite is None:
        return None
    return PortalAdminClinicInviteSnapshot(
        id=invite.id,
        status=invite.status,
        delivery_channel=invite.delivery_channel,
        delivery_target_masked=invite.delivery_target_masked,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        delivered_at=invite.delivered_at,
        used_at=invite.used_at,
        revoked_at=invite.revoked_at,
    )


def _account_snapshot(account: PortalClinicAccount | None) -> PortalAdminClinicAccountSnapshot | None:
    if account is None:
        return None
    return PortalAdminClinicAccountSnapshot(
        id=account.id,
        status=account.status,
        email_masked=mask_email(account.email_normalized),
        responsavel_nome=account.responsavel_nome,
        email_verified_at=account.email_verified_at,
        activated_at=account.activated_at,
        last_login_at=account.last_login_at,
        force_mfa_on_next_login=bool(account.force_mfa_on_next_login),
        revoked_at=account.revoked_at,
    )


def _trusted_device_snapshot(device: PortalClinicTrustedDevice) -> PortalAdminClinicTrustedDeviceSnapshot:
    return PortalAdminClinicTrustedDeviceSnapshot(
        id=device.id,
        status=device.status,
        device_label=device.device_label,
        origin=device.origin,
        origin_exam_link_id=device.origin_exam_link_id,
        expires_at=device.expires_at,
        last_seen_at=device.last_seen_at,
        created_at=device.created_at,
        revoked_at=device.revoked_at,
        revoked_reason=device.revoked_reason,
    )


def _session_snapshot(session: PortalClinicSession) -> PortalAdminClinicSessionSnapshot:
    return PortalAdminClinicSessionSnapshot(
        id=session.id,
        account_id=session.account_id,
        status=session.status,
        trusted_until=session.trusted_until,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        revoked_at=session.revoked_at,
        device_label=session.device_label,
    )


def _safe_json_dict(value: str | None) -> dict:
    try:
        loaded = json.loads(value or "{}")
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _first_clinic_whatsapp(clinica: Clinica) -> str | None:
    valores = getattr(clinica, "whatsapps", None)
    if isinstance(valores, list):
        for valor in valores:
            texto = str(valor or "").strip()
            if texto:
                return texto
    telefone = str(getattr(clinica, "telefone", "") or "").strip()
    return telefone or None


def _normalized_invite_account_email(invite: PortalClinicInvite | None) -> str:
    if invite is None:
        return ""
    return normalize_email(json_load_dict(invite.contexto_json).get("account_email"))


def _preferred_login_email(
    clinica: Clinica,
    invite: PortalClinicInvite | None,
    account: PortalClinicAccount | None,
) -> str | None:
    if account and normalize_email(account.email_normalized):
        return normalize_email(account.email_normalized)
    invite_email = _normalized_invite_account_email(invite)
    if invite_email:
        return invite_email
    return normalize_email(getattr(clinica, "email", None)) or None


def _needs_email_definition(clinica: Clinica, invite: PortalClinicInvite | None, account: PortalClinicAccount | None) -> bool:
    if account and account.status in {ACCOUNT_STATUS_PENDING, ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_LOCKED}:
        return False
    if _normalized_invite_account_email(invite):
        return False
    return not normalize_email(getattr(clinica, "email", None))


def _status_for_clinic_overview(
    clinica: Clinica,
    invite: PortalClinicInvite | None,
    account: PortalClinicAccount | None,
) -> tuple[str, str]:
    if account is not None:
        if account.status == ACCOUNT_STATUS_ACTIVE:
            return "active", "Cadastro concluido"
        if account.status == ACCOUNT_STATUS_LOCKED:
            return "locked", "Conta bloqueada"
        if account.status == ACCOUNT_STATUS_PENDING:
            return "pending_verification", "Cadastro pendente"
        if account.status == ACCOUNT_STATUS_REVOKED:
            return "account_revoked", "Conta revogada"

    if invite is not None:
        if invite.status == INVITE_STATUS_PENDING:
            if _needs_email_definition(clinica, invite, account):
                return "needs_email", "Precisa informar email"
            return "invited_pending", "Convite pendente"
        if invite.status == "expired":
            return "invite_expired", "Convite expirado"
        if invite.status == INVITE_STATUS_REVOKED:
            return "invite_revoked", "Convite revogado"
        if invite.status == INVITE_STATUS_USED:
            return "invite_used", "Convite utilizado"

    if _needs_email_definition(clinica, invite, account):
        return "needs_email", "Precisa informar email"

    return "not_invited", "Sem convite ativo"


def _refresh_latest_invites_if_needed(db: Session, invites: list[PortalClinicInvite]) -> None:
    dirty = False
    now = utcnow()
    for invite in invites:
        if (
            invite.status == INVITE_STATUS_PENDING
            and invite.expires_at
            and invite.expires_at <= now
        ):
            invite.status = "expired"
            dirty = True
    if dirty:
        db.commit()
        for invite in invites:
            db.refresh(invite)


def _max_datetime(*values: datetime | None) -> datetime | None:
    valid = [_normalize_utc_naive_datetime(value) for value in values if value is not None]
    return max(valid) if valid else None


def _days_since(reference: datetime | None, now: datetime) -> int | None:
    if reference is None:
        return None
    normalized_reference = _normalize_utc_naive_datetime(reference)
    normalized_now = _normalize_utc_naive_datetime(now)
    if normalized_reference is None or normalized_now is None:
        return None
    delta = normalized_now.date() - normalized_reference.date()
    return max(delta.days, 0)


def _normalize_utc_naive_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _load_portal_download_analytics(
    db: Session,
    *,
    clinicas_by_id: dict[int, Clinica],
    accounts_by_id: dict[int, PortalClinicAccount],
) -> tuple[
    dict[int, int],
    dict[int, datetime],
    dict[int, datetime],
    int,
    list[PortalAdminClinicDownloadEventResponse],
    dict[int, list[PortalAdminClinicDownloadEventResponse]],
]:
    rows = (
        db.query(AuditoriaEvento)
        .filter(
            AuditoriaEvento.modulo == "portal",
            AuditoriaEvento.acao == PORTAL_DOWNLOAD_AUDIT_ACTION,
        )
        .order_by(AuditoriaEvento.created_at.desc(), AuditoriaEvento.id.desc())
        .all()
    )

    cutoff_30d = _normalize_utc_naive_datetime(utcnow() - timedelta(days=30))
    download_count_by_clinica: dict[int, int] = {}
    last_download_at_by_clinica: dict[int, datetime] = {}
    first_download_at_by_clinica: dict[int, datetime] = {}
    downloads_30d = 0
    recent_rows: list[tuple[AuditoriaEvento, dict]] = []
    timeline_rows_by_clinica: dict[int, list[tuple[AuditoriaEvento, dict]]] = {}

    for row in rows:
        details = _safe_json_dict(row.detalhes_json)
        if str(details.get("actor_type") or "").strip().lower() != "clinica":
            continue
        clinica_id_raw = details.get("clinica_id")
        try:
            clinica_id = int(clinica_id_raw)
        except (TypeError, ValueError):
            continue
        if clinica_id not in clinicas_by_id:
            continue

        created_at = _normalize_utc_naive_datetime(row.created_at)
        if created_at is None:
            continue

        download_count_by_clinica[clinica_id] = download_count_by_clinica.get(clinica_id, 0) + 1
        if clinica_id not in last_download_at_by_clinica:
            last_download_at_by_clinica[clinica_id] = created_at
        first_download_at_by_clinica[clinica_id] = created_at
        if cutoff_30d is not None and created_at >= cutoff_30d:
            downloads_30d += 1
        if len(recent_rows) < PORTAL_RECENT_DOWNLOADS_LIMIT:
            recent_rows.append((row, details))
        clinic_timeline_rows = timeline_rows_by_clinica.setdefault(clinica_id, [])
        if len(clinic_timeline_rows) < PORTAL_TIMELINE_DOWNLOAD_LIMIT_PER_CLINICA:
            clinic_timeline_rows.append((row, details))

    selected_rows_by_audit_id: dict[int, tuple[AuditoriaEvento, dict]] = {}
    for row, details in recent_rows:
        selected_rows_by_audit_id[row.id] = (row, details)
    for clinic_rows in timeline_rows_by_clinica.values():
        for row, details in clinic_rows:
            selected_rows_by_audit_id.setdefault(row.id, (row, details))

    selected_rows = list(selected_rows_by_audit_id.values())

    exam_ids = {
        int(details["exame_id"])
        for _, details in selected_rows
        if isinstance(details.get("exame_id"), (int, str)) and str(details.get("exame_id")).isdigit()
    }
    attachment_ids = {
        int(row.entidade_id)
        for row, _ in selected_rows
        if str(row.entidade_id or "").isdigit()
    }
    patient_ids: set[int] = set()
    tutor_ids: set[int] = set()

    exams = (
        db.query(Exame)
        .filter(Exame.id.in_(exam_ids))
        .all()
        if exam_ids
        else []
    )
    exams_by_id = {exam.id: exam for exam in exams}
    for exam in exams:
        if exam.paciente_id:
            patient_ids.add(int(exam.paciente_id))

    attachments = (
        db.query(AnexoAtendimento)
        .filter(AnexoAtendimento.id.in_(attachment_ids))
        .all()
        if attachment_ids
        else []
    )
    attachments_by_id = {attachment.id: attachment for attachment in attachments}

    patients = (
        db.query(Paciente)
        .filter(Paciente.id.in_(patient_ids))
        .all()
        if patient_ids
        else []
    )
    patients_by_id = {patient.id: patient for patient in patients}
    for patient in patients:
        if patient.tutor_id:
            tutor_ids.add(int(patient.tutor_id))

    tutors = (
        db.query(Tutor)
        .filter(Tutor.id.in_(tutor_ids))
        .all()
        if tutor_ids
        else []
    )
    tutors_by_id = {tutor.id: tutor for tutor in tutors}

    download_events_by_audit_id: dict[int, PortalAdminClinicDownloadEventResponse] = {}
    for row, details in selected_rows:
        clinica_id = int(details["clinica_id"])
        created_at = _normalize_utc_naive_datetime(row.created_at)
        if created_at is None:
            continue
        exam = exams_by_id.get(int(details["exame_id"])) if str(details.get("exame_id") or "").isdigit() else None
        attachment = attachments_by_id.get(int(row.entidade_id)) if str(row.entidade_id or "").isdigit() else None
        patient = patients_by_id.get(exam.paciente_id) if exam and exam.paciente_id else None
        tutor = tutors_by_id.get(patient.tutor_id) if patient and patient.tutor_id else None
        account = accounts_by_id.get(int(details["account_id"])) if str(details.get("account_id") or "").isdigit() else None

        download_events_by_audit_id[row.id] = (
            PortalAdminClinicDownloadEventResponse(
                audit_event_id=row.id,
                clinica_id=clinica_id,
                clinica_nome=clinicas_by_id[clinica_id].nome,
                account_email_masked=mask_email(account.email_normalized) if account else None,
                exame_id=exam.id if exam else None,
                paciente_nome=getattr(patient, "nome", None),
                tutor_nome=getattr(tutor, "nome", None),
                tipo_exame=getattr(exam, "tipo_exame", None),
                anexo_nome=getattr(attachment, "nome_original", None),
                downloaded_at=created_at,
                is_first_download=first_download_at_by_clinica.get(clinica_id) == created_at,
            )
        )

    recent_downloads = [download_events_by_audit_id[row.id] for row, _ in recent_rows if row.id in download_events_by_audit_id]
    timeline_downloads_by_clinica = {
        clinica_id: [
            download_events_by_audit_id[row.id]
            for row, _ in clinic_rows
            if row.id in download_events_by_audit_id
        ]
        for clinica_id, clinic_rows in timeline_rows_by_clinica.items()
    }

    return (
        download_count_by_clinica,
        last_download_at_by_clinica,
        first_download_at_by_clinica,
        downloads_30d,
        recent_downloads,
        timeline_downloads_by_clinica,
    )


def _build_clinic_timeline(
    *,
    clinica: Clinica,
    invites: list[PortalClinicInvite],
    accounts: list[PortalClinicAccount],
    timeline_downloads: list[PortalAdminClinicDownloadEventResponse],
) -> list[PortalAdminClinicTimelineEventResponse]:
    events: list[PortalAdminClinicTimelineEventResponse] = []

    for invite in invites:
        invite_email = mask_email(_normalized_invite_account_email(invite)) if _normalized_invite_account_email(invite) else None
        invite_target = invite.delivery_target_masked or "destino nao identificado"
        invite_desc_parts = [f"Canal {invite.delivery_channel}", invite_target]
        if invite_email:
            invite_desc_parts.append(f"login {invite_email}")

        events.append(
            PortalAdminClinicTimelineEventResponse(
                event_id=f"invite-created-{invite.id}",
                event_type="invite_created",
                title="Convite gerado",
                description=" • ".join(invite_desc_parts),
                occurred_at=_normalize_utc_naive_datetime(invite.created_at),
                tone="neutral",
            )
        )

        if invite.delivered_at and invite.delivered_at != invite.created_at:
            events.append(
                PortalAdminClinicTimelineEventResponse(
                    event_id=f"invite-delivered-{invite.id}",
                    event_type="invite_delivered",
                    title="Convite enviado",
                    description=invite_target,
                    occurred_at=_normalize_utc_naive_datetime(invite.delivered_at),
                    tone="success",
                )
            )

        if invite.used_at:
            events.append(
                PortalAdminClinicTimelineEventResponse(
                    event_id=f"invite-used-{invite.id}",
                    event_type="invite_used",
                    title="Convite aceito",
                    description=invite_email or "Ativacao concluida pela unidade.",
                    occurred_at=_normalize_utc_naive_datetime(invite.used_at),
                    tone="success",
                )
            )

        if invite.revoked_at:
            events.append(
                PortalAdminClinicTimelineEventResponse(
                    event_id=f"invite-revoked-{invite.id}",
                    event_type="invite_revoked",
                    title="Convite revogado",
                    description=invite_target,
                    occurred_at=_normalize_utc_naive_datetime(invite.revoked_at),
                    tone="danger",
                )
            )

    for account in accounts:
        account_email = mask_email(account.email_normalized) if account.email_normalized else None
        account_desc = account_email or account.responsavel_nome or clinica.nome

        if account.activated_at:
            events.append(
                PortalAdminClinicTimelineEventResponse(
                    event_id=f"account-activated-{account.id}",
                    event_type="account_activated",
                    title="Cadastro concluido",
                    description=account_desc,
                    occurred_at=_normalize_utc_naive_datetime(account.activated_at),
                    tone="success",
                )
            )

        if account.revoked_at:
            events.append(
                PortalAdminClinicTimelineEventResponse(
                    event_id=f"account-revoked-{account.id}",
                    event_type="account_revoked",
                    title="Conta revogada",
                    description=account_desc,
                    occurred_at=_normalize_utc_naive_datetime(account.revoked_at),
                    tone="danger",
                )
            )

    for download_event in timeline_downloads:
        download_title = "Primeiro laudo baixado" if download_event.is_first_download else "Laudo baixado"
        download_desc_parts = []
        if download_event.tipo_exame:
            download_desc_parts.append(download_event.tipo_exame)
        if download_event.paciente_nome:
            download_desc_parts.append(download_event.paciente_nome)
        if download_event.account_email_masked:
            download_desc_parts.append(download_event.account_email_masked)

        events.append(
            PortalAdminClinicTimelineEventResponse(
                event_id=f"download-{download_event.audit_event_id}",
                event_type="download",
                title=download_title,
                description=" • ".join(download_desc_parts) or "Arquivo do portal baixado pela unidade.",
                occurred_at=download_event.downloaded_at,
                tone="success" if download_event.is_first_download else "neutral",
            )
        )

    events.sort(
        key=lambda item: (_normalize_utc_naive_datetime(item.occurred_at) or datetime.min, item.event_id),
        reverse=True,
    )
    return events[:PORTAL_TIMELINE_LIMIT_PER_CLINICA]


def _login_result_response(result, *, message: str | None = None) -> PortalClinicAuthResponse:
    return PortalClinicAuthResponse(
        access_token=result.access_token,
        expires_at=result.expires_at,
        actor_type="clinica",
        actor_id=result.clinica_id,
        clinica_id=result.clinica_id,
        account_id=result.account_id,
        auth_method=result.auth_method,
        trusted_session_expires_at=result.trusted_session_expires_at,
        scope=result.scope,
        message=message,
    )


@router.get("/admin/clinicas/{clinica_id}/acesso", response_model=PortalAdminClinicAccessSummaryResponse)
def consultar_acesso_clinica_admin(
    clinica_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_invite_operator),
):
    _assert_invite_auth_enabled()
    clinica = get_active_clinica_or_404(db, clinica_id)

    invites = (
        db.query(PortalClinicInvite)
        .filter(PortalClinicInvite.clinica_id == clinica.id)
        .order_by(PortalClinicInvite.id.desc())
        .all()
    )
    for invite in invites:
        expire_invite_if_needed(db, invite)

    accounts = (
        db.query(PortalClinicAccount)
        .filter(PortalClinicAccount.clinica_id == clinica.id)
        .order_by(PortalClinicAccount.id.desc())
        .all()
    )
    active_sessions = (
        db.query(PortalClinicSession)
        .filter(
            PortalClinicSession.clinica_id == clinica.id,
            PortalClinicSession.status == SESSION_STATUS_ACTIVE,
        )
        .order_by(PortalClinicSession.trusted_until.desc(), PortalClinicSession.id.desc())
        .all()
    )

    trusted_devices = (
        db.query(PortalClinicTrustedDevice)
        .filter(PortalClinicTrustedDevice.clinica_id == clinica.id)
        .order_by(PortalClinicTrustedDevice.id.desc())
        .all()
    )

    return PortalAdminClinicAccessSummaryResponse(
        clinica_id=clinica.id,
        clinica_nome=clinica.nome,
        invite=_invite_snapshot(invites[0] if invites else None),
        account=_account_snapshot(accounts[0] if accounts else None),
        invites=[_invite_snapshot(invite) for invite in invites],
        accounts=[_account_snapshot(account) for account in accounts],
        active_session_count=len(active_sessions),
        active_sessions=[_session_snapshot(session) for session in active_sessions],
        trusted_devices=[_trusted_device_snapshot(device) for device in trusted_devices],
    )


@router.post(
    "/admin/clinica-dispositivos/revogar",
    response_model=PortalAdminDeviceRevokeResponse,
)
def revogar_dispositivos_confiaveis_admin(
    payload: PortalAdminDeviceRevokeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_invite_operator),
):
    """Corta o acesso de um computador da recepcao, ou de todos os de uma unidade.

    Existe porque a confianca nao expira por tempo, so por inatividade: revogar e
    o unico jeito de encerrar um acesso que nao deveria mais valer - maquina
    trocada, vendida, ou unidade que encerrou a parceria.
    """
    motivo = str(payload.motivo or "").strip() or "revogado_pelo_admin"

    if payload.device_id is not None:
        device = (
            db.query(PortalClinicTrustedDevice)
            .filter(PortalClinicTrustedDevice.id == payload.device_id)
            .first()
        )
        if device is None:
            raise HTTPException(status_code=404, detail="Dispositivo nao encontrado.")
        revogados = 0
        if device.status == TRUST_STATUS_ACTIVE:
            revoke_trust(db, device, motivo=motivo)
            revogados = 1
        clinica_id = device.clinica_id
    elif payload.clinica_id is not None:
        revogados = revoke_trusts_for_clinica(db, payload.clinica_id, motivo=motivo)
        clinica_id = payload.clinica_id
    else:
        raise HTTPException(status_code=422, detail="Informe device_id ou clinica_id.")

    registrar_auditoria(
        current_user=current_user,
        modulo="portal",
        entidade="portal_clinic_trusted_device",
        acao="PORTAL_CLINIC_DEVICE_REVOKED",
        descricao="Confianca de dispositivo revogada pela equipe Fort Cordis.",
        entidade_id=str(payload.device_id or payload.clinica_id),
        detalhes={"clinica_id": clinica_id, "revogados": revogados, "motivo": motivo},
        request=request,
    )
    return PortalAdminDeviceRevokeResponse(revogados=revogados)


@router.get("/admin/clinicas/{clinica_id}/espelho", response_model=PortalExamListResponse)
def consultar_espelho_portal_clinica_admin(
    clinica_id: int,
    q: str | None = Query(default=None, max_length=120),
    pet: str | None = Query(default=None, max_length=120),
    tutor: str | None = Query(default=None, max_length=120),
    especie: str | None = Query(default=None, max_length=80),
    tipo_exame: str | None = Query(default=None, max_length=120),
    status_exame: str | None = Query(default=None, max_length=80),
    data_inicio: date | None = None,
    data_fim: date | None = None,
    sort_by: str = Query(default="data", pattern="^(data|tipo_exame|especie|pet|tutor|status)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    del current_user
    _assert_invite_auth_enabled()
    clinica = get_active_clinica_or_404(db, clinica_id)
    preview_session = _build_admin_preview_portal_session(clinica_id=clinica.id, clinica_nome=clinica.nome)
    return portal_endpoints.listar_exames_clinica_portal(
        q=q,
        pet=pet,
        tutor=tutor,
        especie=especie,
        tipo_exame=tipo_exame,
        status_exame=status_exame,
        data_inicio=data_inicio,
        data_fim=data_fim,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        db=db,
        portal_session=preview_session,
    )


@router.post(
    "/admin/clinicas/{clinica_id}/exames/{exame_id}/download-url",
    response_model=PortalDownloadUrlResponse,
)
def gerar_download_espelho_portal_clinica_admin(
    clinica_id: int,
    exame_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    del current_user
    _assert_invite_auth_enabled()
    clinica = get_active_clinica_or_404(db, clinica_id)
    preview_session = _build_admin_preview_portal_session(clinica_id=clinica.id, clinica_nome=clinica.nome)
    return portal_endpoints.gerar_download_url_exame_portal(
        exame_id=exame_id,
        db=db,
        portal_session=preview_session,
    )


@router.get("/admin/clinicas/acessos/painel", response_model=PortalAdminClinicAccessOverviewResponse)
def consultar_painel_acessos_clinicas(
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_invite_operator),
):
    del current_user
    _assert_invite_auth_enabled()

    clinicas = (
        db.query(Clinica)
        .filter(Clinica.ativo.is_(True))
        .order_by(func.lower(Clinica.nome), Clinica.id.asc())
        .all()
    )
    if not clinicas:
        return PortalAdminClinicAccessOverviewResponse(
            generated_at=utcnow(),
            metrics=PortalAdminClinicAccessOverviewMetrics(),
            items=[],
            recent_downloads=[],
        )

    clinica_ids = [clinica.id for clinica in clinicas]
    clinicas_by_id = {clinica.id: clinica for clinica in clinicas}

    invites = (
        db.query(PortalClinicInvite)
        .filter(PortalClinicInvite.clinica_id.in_(clinica_ids))
        .order_by(PortalClinicInvite.clinica_id.asc(), PortalClinicInvite.id.desc())
        .all()
    )
    latest_invites_by_clinica: dict[int, PortalClinicInvite] = {}
    invite_history_by_clinica: dict[int, list[PortalClinicInvite]] = {}
    for invite in invites:
        latest_invites_by_clinica.setdefault(invite.clinica_id, invite)
        invite_history_by_clinica.setdefault(invite.clinica_id, []).append(invite)
    _refresh_latest_invites_if_needed(db, list(latest_invites_by_clinica.values()))

    accounts = (
        db.query(PortalClinicAccount)
        .filter(PortalClinicAccount.clinica_id.in_(clinica_ids))
        .order_by(PortalClinicAccount.clinica_id.asc(), PortalClinicAccount.id.desc())
        .all()
    )
    latest_accounts_by_clinica: dict[int, PortalClinicAccount] = {}
    accounts_by_id: dict[int, PortalClinicAccount] = {}
    account_history_by_clinica: dict[int, list[PortalClinicAccount]] = {}
    for account in accounts:
        latest_accounts_by_clinica.setdefault(account.clinica_id, account)
        accounts_by_id[account.id] = account
        account_history_by_clinica.setdefault(account.clinica_id, []).append(account)

    active_session_rows = (
        db.query(
            PortalClinicSession.clinica_id,
            func.count(PortalClinicSession.id),
        )
        .filter(
            PortalClinicSession.clinica_id.in_(clinica_ids),
            PortalClinicSession.status == SESSION_STATUS_ACTIVE,
        )
        .group_by(PortalClinicSession.clinica_id)
        .all()
    )
    active_session_count_by_clinica = {
        int(clinica_id): int(total or 0)
        for clinica_id, total in active_session_rows
    }

    (
        download_count_by_clinica,
        last_download_at_by_clinica,
        first_download_at_by_clinica,
        downloads_30d,
        recent_downloads,
        timeline_downloads_by_clinica,
    ) = _load_portal_download_analytics(
        db,
        clinicas_by_id=clinicas_by_id,
        accounts_by_id=accounts_by_id,
    )

    items: list[PortalAdminClinicAccessOverviewItem] = []
    metrics = PortalAdminClinicAccessOverviewMetrics(total_clinicas=len(clinicas))
    now = utcnow()

    for clinica in clinicas:
        invite = latest_invites_by_clinica.get(clinica.id)
        account = latest_accounts_by_clinica.get(clinica.id)
        needs_email_definition = _needs_email_definition(clinica, invite, account)
        status_key, status_label = _status_for_clinic_overview(clinica, invite, account)
        active_session_count = active_session_count_by_clinica.get(clinica.id, 0)
        active_accounts_count = sum(
            1
            for clinica_account in account_history_by_clinica.get(clinica.id, [])
            if clinica_account.status in {ACCOUNT_STATUS_PENDING, ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_LOCKED}
        )
        download_count = download_count_by_clinica.get(clinica.id, 0)
        last_access_at = _max_datetime(
            account.last_login_at if account else None,
            last_download_at_by_clinica.get(clinica.id),
        )

        if invite and invite.status == INVITE_STATUS_PENDING:
            metrics.convites_pendentes += 1
        if account and account.status == ACCOUNT_STATUS_ACTIVE:
            metrics.contas_ativas += 1
        if needs_email_definition:
            metrics.clinicas_precisam_email += 1
        if not invite and not account:
            metrics.clinicas_sem_convite += 1
        metrics.sessoes_ativas += active_session_count
        metrics.downloads_total += download_count
        if download_count > 0:
            metrics.clinicas_com_downloads += 1

        items.append(
            PortalAdminClinicAccessOverviewItem(
                clinica_id=clinica.id,
                clinica_nome=clinica.nome,
                cidade=clinica.cidade,
                estado=clinica.estado,
                contato_email=normalize_email(clinica.email) or None,
                contato_whatsapp=_first_clinic_whatsapp(clinica),
                login_email=_preferred_login_email(clinica, invite, account),
                invite=_invite_snapshot(invite),
                invite_account_email_masked=mask_email(_normalized_invite_account_email(invite))
                if _normalized_invite_account_email(invite)
                else None,
                account=_account_snapshot(account),
                active_session_count=active_session_count,
                active_accounts_count=active_accounts_count,
                status_key=status_key,
                status_label=status_label,
                needs_email_definition=needs_email_definition,
                download_count=download_count,
                last_download_at=last_download_at_by_clinica.get(clinica.id),
                first_download_at=first_download_at_by_clinica.get(clinica.id),
                last_access_at=last_access_at,
                days_since_last_activity=_days_since(last_access_at, now),
                timeline=_build_clinic_timeline(
                    clinica=clinica,
                    invites=invite_history_by_clinica.get(clinica.id, []),
                    accounts=account_history_by_clinica.get(clinica.id, []),
                    timeline_downloads=timeline_downloads_by_clinica.get(clinica.id, []),
                ),
            )
        )

    metrics.downloads_ultimos_30_dias = downloads_30d

    return PortalAdminClinicAccessOverviewResponse(
        generated_at=utcnow(),
        metrics=metrics,
        items=items,
        recent_downloads=recent_downloads,
    )


@router.post("/admin/clinicas/{clinica_id}/convites", response_model=PortalAdminClinicInviteResponse)
def criar_convite_clinica(
    clinica_id: int,
    payload: PortalAdminClinicInviteCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_invite_operator),
):
    _assert_invite_auth_enabled()
    clinica = get_active_clinica_or_404(db, clinica_id)
    normalized_payload_email = normalize_email(payload.account_email)

    existing_account = get_account_by_email(db, normalized_payload_email) if normalized_payload_email else None
    if (
        existing_account is not None
        and existing_account.clinica_id != clinica.id
        and existing_account.status != ACCOUNT_STATUS_REVOKED
    ):
        raise HTTPException(
            status_code=409,
            detail="Este email institucional ja esta em uso por outra clinica.",
        )

    account_allows_login_reminder = (
        existing_account is not None
        and existing_account.clinica_id == clinica.id
        and existing_account.status in {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_LOCKED}
    )

    invite = None
    access_mode: str = "activation"
    access_url: str
    account_email_masked: str | None
    senha_temporaria_gerada: str | None = None
    temp_password_account_id: int | None = None

    if account_allows_login_reminder:
        access_mode = "login"
        access_url = build_clinic_portal_url(request)
        account_email_masked = mask_email(existing_account.email_normalized)
    else:
        if count_active_clinic_manager_slots(db, clinica.id) >= MAX_ACTIVE_CLINIC_MANAGERS:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Limite de {MAX_ACTIVE_CLINIC_MANAGERS} gestores com acesso ativo por clinica foi atingido. "
                    "Revogue um acesso existente antes de convidar outro gestor."
                ),
            )
        if payload.senha_temporaria:
            if not normalized_payload_email:
                raise HTTPException(status_code=422, detail="Informe o email institucional do gestor.")
            senha_temporaria_gerada = gerar_senha_temporaria()
            account = create_or_replace_pending_account(
                db,
                clinica_id=clinica.id,
                email=payload.account_email,
                responsavel_nome=payload.responsavel_nome or "Gestor da clinica",
                password=senha_temporaria_gerada,
            )
            now = utcnow()
            account.status = ACCOUNT_STATUS_ACTIVE
            account.email_verified_at = now
            account.activated_at = now
            account.must_change_password = True
            db.commit()

            access_mode = "temporary_password"
            access_url = build_clinic_portal_url(request)
            account_email_masked = mask_email(account.email_normalized)
            temp_password_account_id = account.id
        else:
            invite, raw_token = create_clinic_invite(
                db,
                clinica_id=clinica.id,
                delivery_channel=payload.delivery_channel,
                delivery_target=payload.delivery_target,
                account_email=payload.account_email,
                expires_in_hours=payload.expires_in_hours,
                created_by_user_id=current_user.id,
            )
            access_url = build_activation_url(request, raw_token)
            account_email_masked = mask_email(payload.account_email) if payload.account_email else None

    delivery_status = "manual_copy"
    delivery_provider = None

    if settings.WHATSAPP_AGENDA_ENABLED:
        try:
            if access_mode == "login":
                result = send_whatsapp_login_access(
                    destination=payload.delivery_target,
                    clinica_id=clinica.id,
                    clinica_nome=clinica.nome,
                    portal_url=access_url,
                    account_email=normalize_email(existing_account.email_normalized),
                    idempotency_key=f"portal-clinic-login-{existing_account.id}-{secrets.token_hex(6)}",
                )
            elif access_mode == "temporary_password":
                result = send_whatsapp_temporary_password(
                    destination=payload.delivery_target,
                    clinica_id=clinica.id,
                    clinica_nome=clinica.nome,
                    portal_url=access_url,
                    account_email=normalized_payload_email,
                    senha_temporaria=senha_temporaria_gerada or "",
                    idempotency_key=f"portal-clinic-temp-password-{temp_password_account_id}-{secrets.token_hex(6)}",
                )
            else:
                result = send_whatsapp_invite(
                    destination=payload.delivery_target,
                    clinica_id=clinica.id,
                    clinica_nome=clinica.nome,
                    activation_url=access_url,
                    expires_in_hours=payload.expires_in_hours,
                    idempotency_key=f"portal-clinic-invite-{invite.id if invite is not None else secrets.token_hex(6)}",
                )
            if invite is not None:
                invite.delivered_at = utcnow()
                db.commit()
            delivery_status = "sent"
            delivery_provider = result.provider
        except HTTPException as exc:
            # O servico de entrega usa HTTPException para condicao de ambiente
            # (integracao nao configurada, envio desabilitado). O `detail` dele
            # e a informacao util -- sem isso, a falha vira "nao chegou e
            # ninguem sabe por que".
            motivo = str(exc.detail or "").strip() or "Falha ao enviar o convite por WhatsApp."
            logger.warning(
                "Convite da clinica %s nao foi enviado por WhatsApp: %s",
                clinica.id,
                motivo,
            )
            if not payload.allow_manual_copy:
                raise HTTPException(status_code=502, detail=motivo) from exc
        except Exception as exc:
            motivo = str(exc).strip() or exc.__class__.__name__
            logger.warning(
                "Convite da clinica %s nao foi enviado por WhatsApp: %s",
                clinica.id,
                motivo,
                exc_info=True,
            )
            if not payload.allow_manual_copy:
                raise HTTPException(
                    status_code=502,
                    detail=f"Nao foi possivel enviar o convite por WhatsApp: {motivo}",
                ) from exc
    elif not payload.allow_manual_copy:
        raise HTTPException(
            status_code=400,
            detail="Envio automatico por WhatsApp indisponivel neste ambiente.",
        )

    audit_entidade = "portal_clinic_invite"
    audit_acao = "PORTAL_CLINIC_INVITE_CREATED"
    audit_descricao = "Convite da clinica parceira criado."
    audit_entidade_id = invite.id if invite is not None else None
    if access_mode == "login":
        audit_entidade = "portal_clinic_account"
        audit_acao = "PORTAL_CLINIC_ACCESS_REMINDER_SENT"
        audit_descricao = "Acesso da clinica parceira reenviado."
        audit_entidade_id = existing_account.id
    elif access_mode == "temporary_password":
        audit_entidade = "portal_clinic_account"
        audit_acao = "PORTAL_CLINIC_ACCOUNT_CREATED_WITH_TEMP_PASSWORD"
        audit_descricao = "Conta da clinica parceira criada com senha temporaria pelo admin."
        audit_entidade_id = temp_password_account_id

    registrar_auditoria(
        current_user=current_user,
        modulo="portal",
        entidade=audit_entidade,
        acao=audit_acao,
        descricao=audit_descricao,
        entidade_id=audit_entidade_id,
        detalhes={
            "clinica_id": clinica.id,
            "delivery_channel": payload.delivery_channel,
            "delivery_status": delivery_status,
            "access_mode": access_mode,
        },
        request=request,
    )

    invite_status: str
    invite_expires_at = invite.expires_at if invite is not None else None
    if access_mode == "login":
        invite_status = existing_account.status
    elif access_mode == "temporary_password":
        invite_status = ACCOUNT_STATUS_ACTIVE
    else:
        invite_status = invite.status if invite is not None else "pending"

    return PortalAdminClinicInviteResponse(
        invite_id=invite.id if invite is not None else None,
        status=invite_status,
        expires_at=invite_expires_at,
        activation_url=access_url,
        access_mode=access_mode,
        delivery_channel=payload.delivery_channel,
        delivery_target_masked=mask_phone(payload.delivery_target)
        if payload.delivery_channel == "whatsapp"
        else mask_email(payload.delivery_target),
        account_email_masked=account_email_masked,
        delivery_status=delivery_status,
        senha_temporaria=senha_temporaria_gerada,
        delivery_provider=delivery_provider,
    )


@router.post(
    "/admin/clinicas/{clinica_id}/convites/{invite_id}/revogar",
    response_model=PortalAdminClinicInviteRevokeResponse,
)
def revogar_convite_clinica(
    clinica_id: int,
    invite_id: int,
    payload: PortalAdminClinicInviteRevokeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    _assert_invite_auth_enabled()
    clinica = get_active_clinica_or_404(db, clinica_id)
    invite = (
        db.query(PortalClinicInvite)
        .filter(
            PortalClinicInvite.id == invite_id,
            PortalClinicInvite.clinica_id == clinica.id,
        )
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Convite da clinica nao encontrado.")
    expire_invite_if_needed(db, invite)
    if invite.status != INVITE_STATUS_PENDING:
        raise HTTPException(status_code=409, detail="Convite da clinica nao pode mais ser revogado.")

    invite.status = INVITE_STATUS_REVOKED
    invite.revoked_at = utcnow()
    db.commit()
    db.refresh(invite)

    registrar_auditoria(
        current_user=current_user,
        modulo="portal",
        entidade="portal_clinic_invite",
        acao="PORTAL_CLINIC_INVITE_REVOKED",
        descricao="Convite da clinica revogado pela operacao.",
        entidade_id=invite.id,
        detalhes={
            "clinica_id": clinica.id,
            "reason": payload.reason,
        },
        request=request,
    )
    return PortalAdminClinicInviteRevokeResponse(
        status=invite.status,
        revoked_at=invite.revoked_at or utcnow(),
    )


@router.post("/admin/clinica-accounts/{account_id}/revogar", response_model=PortalAdminClinicAccountRevokeResponse)
def revogar_conta_clinica(
    account_id: int,
    payload: PortalAdminClinicAccountRevokeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    _assert_invite_auth_enabled()
    account = db.query(PortalClinicAccount).filter(PortalClinicAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Conta da clinica nao encontrada.")

    account.status = ACCOUNT_STATUS_REVOKED
    account.revoked_at = utcnow()
    db.commit()
    if payload.revoke_sessions:
        revoke_sessions_for_account(
            db,
            account_id=account.id,
            reason=payload.reason,
        )

    registrar_auditoria(
        current_user=current_user,
        modulo="portal",
        entidade="portal_clinic_account",
        acao="PORTAL_CLINIC_ACCOUNT_REVOKED",
        descricao="Conta da clinica revogada pela operacao.",
        entidade_id=account.id,
        detalhes={
            "clinica_id": account.clinica_id,
            "revoke_sessions": payload.revoke_sessions,
        },
        request=request,
    )
    return PortalAdminClinicAccountRevokeResponse(
        status=account.status,
        revoked_at=account.revoked_at or utcnow(),
    )


@router.post("/admin/clinica-sessions/revogar", response_model=PortalAdminClinicSessionsRevokeResponse)
def revogar_sessoes_clinica(
    payload: PortalAdminClinicSessionsRevokeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    _assert_invite_auth_enabled()
    revoked_count = revoke_sessions_for_clinica(
        db,
        clinica_id=payload.clinica_id,
        session_id=payload.session_id,
        reason=payload.reason,
    )
    registrar_auditoria(
        current_user=current_user,
        modulo="portal",
        entidade="portal_clinic_session",
        acao="PORTAL_CLINIC_SESSION_REVOKED",
        descricao="Sessao(oes) da clinica revogada(s) pela operacao.",
        entidade_id=payload.session_id or payload.clinica_id,
        detalhes={
            "clinica_id": payload.clinica_id,
            "session_id": payload.session_id,
            "revoked_count": revoked_count,
        },
        request=request,
    )
    return PortalAdminClinicSessionsRevokeResponse(revoked_count=revoked_count)


@router.get("/clinicas/convites/{invite_token}", response_model=PortalClinicInviteStatusResponse)
def consultar_convite_clinica(
    invite_token: str,
    db: Session = Depends(get_db),
):
    _assert_invite_auth_enabled()
    invite = get_invite_by_raw_token(db, invite_token)
    if not invite:
        raise HTTPException(status_code=404, detail="Convite da clinica nao encontrado.")
    clinica = get_active_clinica_or_404(db, invite.clinica_id)
    invite_context = json_load_dict(invite.contexto_json)
    invite_account_email = invite_context.get("account_email")

    # O hint precisa vir da conta ligada ao email deste convite especifico: com varios
    # gestores possiveis por clinica, nao ha como adivinhar "a" conta sem esse vinculo.
    account = get_account_by_email(db, invite_account_email) if invite_account_email else None
    if account is not None and (
        account.clinica_id != clinica.id or account.status not in {ACCOUNT_STATUS_PENDING, ACCOUNT_STATUS_ACTIVE}
    ):
        account = None
    if account:
        email_hint = mask_email(account.email_normalized)
    elif invite_account_email:
        email_hint = mask_email(invite_account_email)
    else:
        email_hint = None
    return PortalClinicInviteStatusResponse(
        status=invite.status,
        clinica_id=clinica.id,
        clinica_nome=clinica.nome,
        unidade_nome=clinica.nome,
        expires_at=invite.expires_at,
        can_activate=invite.status == INVITE_STATUS_PENDING and not expire_invite_if_needed(db, invite),
        email_hint=email_hint,
    )


@router.post("/clinicas/ativacao", response_model=PortalClinicActivationResponse)
def ativar_conta_clinica(
    payload: PortalClinicActivationRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_invite_auth_enabled()
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=422, detail="A confirmacao de senha nao confere.")

    invite = get_invite_by_raw_token(db, payload.invite_token)
    if not invite:
        raise HTTPException(status_code=404, detail="Convite da clinica nao encontrado.")
    if expire_invite_if_needed(db, invite) or invite.status != INVITE_STATUS_PENDING:
        raise HTTPException(status_code=409, detail="Convite da clinica indisponivel para ativacao.")

    clinica = get_active_clinica_or_404(db, invite.clinica_id)
    invite_context = json_load_dict(invite.contexto_json)
    invite_email = normalize_email(invite_context.get("account_email"))
    requested_email = normalize_email(payload.email)
    account_email = invite_email or requested_email
    if not account_email:
        raise HTTPException(status_code=422, detail="Informe o email institucional da clinica.")
    if invite_email and requested_email and requested_email != invite_email:
        raise HTTPException(status_code=422, detail="Email institucional diferente do convite.")

    account = create_or_replace_pending_account(
        db,
        clinica_id=clinica.id,
        email=account_email,
        responsavel_nome=payload.responsavel_nome,
        password=payload.password,
    )
    now = utcnow()
    account.status = ACCOUNT_STATUS_ACTIVE
    account.email_verified_at = now
    account.activated_at = now
    account.force_mfa_on_next_login = False
    invite.status = INVITE_STATUS_USED
    invite.used_at = now
    db.commit()

    result = issue_clinic_session(
        db,
        account=account,
        request=request,
        remember_device_until_shift_end=True,
        auth_reference=f"invite:{invite.id}:{account.id}:{int(datetime.utcnow().timestamp())}",
        auth_method="invite_activation",
    )
    if result.refresh_token and result.trusted_session_expires_at:
        set_portal_refresh_cookie(
            response,
            result.refresh_token,
            expires_at=result.trusted_session_expires_at,
            request=request,
        )
    account.last_login_at = utcnow()
    db.commit()

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_account",
        acao="PORTAL_CLINIC_ACCOUNT_ACTIVATED_BY_INVITE",
        descricao="Conta da clinica ativada por convite seguro.",
        entidade_id=account.id,
        detalhes={
            "clinica_id": clinica.id,
            "invite_id": invite.id,
            "auto_session": True,
        },
        request=request,
    )
    return PortalClinicActivationResponse(
        activation_id=account.id,
        access_token=result.access_token,
        expires_at=result.expires_at,
        actor_type="clinica",
        actor_id=result.clinica_id,
        clinica_id=result.clinica_id,
        account_id=result.account_id,
        auth_method=result.auth_method,
        trusted_session_expires_at=result.trusted_session_expires_at,
        scope=result.scope,
        message="Conta da clinica criada com sucesso. Acesso liberado neste computador.",
    )


@router.post("/auth/email/verificar", response_model=PortalChallengeResponse)
def verificar_email_conta_clinica(
    payload: PortalCodeVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _assert_invite_auth_enabled()
    challenge = (
        db.query(PortalAuthChallenge)
        .filter(PortalAuthChallenge.challenge_id == payload.challenge_id)
        .first()
    )
    if not challenge or challenge.challenge_type != CHALLENGE_TYPE_EMAIL_VERIFICATION:
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    verify_auth_challenge_code(db, challenge=challenge, code=payload.codigo)
    account = db.query(PortalClinicAccount).filter(PortalClinicAccount.id == challenge.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Conta da clinica nao encontrada.")
    account.status = ACCOUNT_STATUS_ACTIVE
    account.email_verified_at = utcnow()
    account.activated_at = utcnow()
    account.force_mfa_on_next_login = False
    db.commit()

    invite_id = json_load_dict(challenge.contexto_json).get("invite_id")
    if invite_id:
        from app.models.portal_clinic_auth import PortalClinicInvite

        invite = db.query(PortalClinicInvite).filter(PortalClinicInvite.id == int(invite_id)).first()
        if invite and invite.status == INVITE_STATUS_PENDING:
            invite.status = INVITE_STATUS_USED
            invite.used_at = utcnow()
            db.commit()

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_account",
        acao="PORTAL_CLINIC_EMAIL_VERIFIED",
        descricao="Email institucional da clinica verificado com sucesso.",
        entidade_id=account.id,
        detalhes={"clinica_id": account.clinica_id},
        request=request,
    )
    return PortalChallengeResponse(
        challenge_id=challenge.challenge_id,
        message="Email institucional verificado com sucesso.",
        expires_in_seconds=0,
        debug_code=None,
    )


@router.post("/auth/login", response_model=PortalClinicAuthResponse)
def login_clinica_com_senha(
    payload: PortalClinicLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_password_login_enabled()
    account = get_account_by_email(db, payload.email)
    if not account or account.status not in {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_LOCKED}:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos.")
    if account.status == ACCOUNT_STATUS_REVOKED:
        raise HTTPException(status_code=403, detail="Conta da clinica indisponivel.")
    if account.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Email institucional ainda nao verificado.")
    if not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos.")

    clinica = get_active_clinica_or_404(db, account.clinica_id)
    if maybe_require_mfa(account, remember_device_until_shift_end=payload.remember_device_until_shift_end):
        challenge, raw_code = create_auth_challenge(
            db,
            account_id=account.id,
            clinica_id=clinica.id,
            challenge_type=CHALLENGE_TYPE_LOGIN_MFA,
            context={"remember_device_until_shift_end": payload.remember_device_until_shift_end},
            expires_minutes=settings.PORTAL_CLINIC_MFA_EXPIRE_MINUTES,
        )
        try:
            send_login_mfa_code(
                destination=account.email_normalized,
                responsavel_nome=account.responsavel_nome,
                clinica_nome=clinica.nome,
                code=raw_code,
                expires_in_minutes=settings.PORTAL_CLINIC_MFA_EXPIRE_MINUTES,
            )
        except Exception:
            challenge.status = "expired"
            db.commit()
            raise HTTPException(
                status_code=502,
                detail="Nao foi possivel enviar o codigo adicional de acesso.",
            )

        registrar_auditoria(
            current_user=None,
            modulo="portal",
            entidade="portal_auth_challenge",
            acao="PORTAL_CLINIC_MFA_CHALLENGE_CREATED",
            descricao="Codigo adicional de login da clinica emitido.",
            entidade_id=challenge.challenge_id,
            detalhes={"clinica_id": clinica.id, "account_id": account.id},
            request=request,
        )
        clear_portal_refresh_cookie(response, request)
        return PortalClinicAuthResponse(
            mfa_required=True,
            challenge_id=challenge.challenge_id,
            message="Enviamos um codigo adicional para confirmar o acesso da clinica.",
        )

    result = issue_clinic_session(
        db,
        account=account,
        request=request,
        remember_device_until_shift_end=payload.remember_device_until_shift_end,
        auth_reference=f"login:{account.id}:{int(datetime.utcnow().timestamp())}",
        auth_method="password",
    )
    if result.refresh_token and result.trusted_session_expires_at:
        set_portal_refresh_cookie(
            response,
            result.refresh_token,
            expires_at=result.trusted_session_expires_at,
            request=request,
        )
    else:
        clear_portal_refresh_cookie(response, request)
    account.last_login_at = utcnow()
    db.commit()
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_account",
        acao="PORTAL_CLINIC_PASSWORD_LOGIN_SUCCEEDED",
        descricao="Login da clinica por email e senha concluido.",
        entidade_id=account.id,
        detalhes={"clinica_id": clinica.id},
        request=request,
    )
    return _login_result_response(result, message="Sessao da clinica iniciada com sucesso.")


@router.post("/auth/mfa/verificar", response_model=PortalClinicAuthResponse)
def verificar_mfa_clinica(
    payload: PortalClinicMfaVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_password_login_enabled()
    challenge = (
        db.query(PortalAuthChallenge)
        .filter(PortalAuthChallenge.challenge_id == payload.challenge_id)
        .first()
    )
    if not challenge or challenge.challenge_type != CHALLENGE_TYPE_LOGIN_MFA:
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    verify_auth_challenge_code(db, challenge=challenge, code=payload.codigo)
    account = db.query(PortalClinicAccount).filter(PortalClinicAccount.id == challenge.account_id).first()
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="Conta da clinica indisponivel.")

    result = issue_clinic_session(
        db,
        account=account,
        request=request,
        remember_device_until_shift_end=payload.remember_device_until_shift_end,
        auth_reference=challenge.challenge_id,
        auth_method="password_mfa",
    )
    if result.refresh_token and result.trusted_session_expires_at:
        set_portal_refresh_cookie(
            response,
            result.refresh_token,
            expires_at=result.trusted_session_expires_at,
            request=request,
        )

    account.last_login_at = utcnow()
    account.force_mfa_on_next_login = False
    db.commit()
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_account",
        acao="PORTAL_CLINIC_MFA_LOGIN_VERIFIED",
        descricao="Login da clinica confirmado por MFA.",
        entidade_id=account.id,
        detalhes={"clinica_id": account.clinica_id, "trusted_session": bool(result.refresh_token)},
        request=request,
    )
    return _login_result_response(result, message="Sessao da clinica iniciada com sucesso.")


@router.post("/auth/refresh", response_model=PortalClinicAuthResponse)
def refresh_login_clinica(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_password_login_enabled()
    raw_refresh_token = get_portal_refresh_cookie(request)
    session = get_session_by_refresh_token(db, raw_refresh_token)
    if not session or session.status != SESSION_STATUS_ACTIVE:
        clear_portal_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="Sessao da clinica expirada.")

    current_user_agent_hash = request_user_agent_hash(request)
    if session.user_agent_hash and current_user_agent_hash and session.user_agent_hash != current_user_agent_hash:
        revoke_session(db, session, reason="mudanca-de-dispositivo")
        clear_portal_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="Sessao da clinica expirada.")

    account = db.query(PortalClinicAccount).filter(PortalClinicAccount.id == session.account_id).first()
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        revoke_session(db, session, reason="conta-inativa")
        clear_portal_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="Sessao da clinica expirada.")

    new_raw_refresh_token = generate_opaque_token()
    session.refresh_token_hash = hash_secret("portal_clinic_refresh", new_raw_refresh_token)
    session.last_seen_at = utcnow()
    db.commit()

    result = issue_clinic_session(
        db,
        account=account,
        request=request,
        remember_device_until_shift_end=False,
        auth_reference=f"session:{session.id}",
        auth_method="refresh",
    )
    set_portal_refresh_cookie(
        response,
        new_raw_refresh_token,
        expires_at=session.trusted_until,
        request=request,
    )
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_session",
        acao="PORTAL_CLINIC_SESSION_REFRESHED",
        descricao="Sessao da clinica renovada via refresh seguro.",
        entidade_id=session.id,
        detalhes={"clinica_id": session.clinica_id, "account_id": session.account_id},
        request=request,
    )
    return _login_result_response(result, message="Sessao da clinica renovada.")


@router.post("/auth/logout", response_model=PortalSimpleAcceptedResponse)
def logout_clinica(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_password_login_enabled()
    raw_refresh_token = get_portal_refresh_cookie(request)
    if raw_refresh_token:
        session = get_session_by_refresh_token(db, raw_refresh_token)
        if session and session.status == SESSION_STATUS_ACTIVE:
            revoke_session(db, session, reason="logout-manual", status_value=SESSION_STATUS_LOGGED_OUT)
    clear_portal_refresh_cookie(response, request)
    return PortalSimpleAcceptedResponse(message="Sessao da clinica encerrada neste dispositivo.")


@router.post("/auth/esqueci-senha", response_model=PortalSimpleAcceptedResponse)
def esqueci_senha_clinica(
    payload: PortalPasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _assert_password_login_enabled()
    account = get_account_by_email(db, payload.email)
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        return _generic_reset_response()

    clinica = get_active_clinica_or_404(db, account.clinica_id)
    _, raw_reset_token = create_password_reset_token(db, account_id=account.id)
    reset_url = build_password_reset_url(request, raw_reset_token)
    try:
        send_password_reset_email(
            destination=account.email_normalized,
            responsavel_nome=account.responsavel_nome,
            clinica_nome=clinica.nome,
            reset_url=reset_url,
            expires_in_minutes=settings.PORTAL_CLINIC_PASSWORD_RESET_EXPIRE_MINUTES,
        )
    except Exception:
        return _generic_reset_response()

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_password_reset",
        acao="PORTAL_CLINIC_PASSWORD_RESET_REQUESTED",
        descricao="Pedido de redefinicao de senha da clinica registrado.",
        entidade_id=account.id,
        detalhes={"clinica_id": account.clinica_id},
        request=request,
    )
    return _generic_reset_response()


@router.post("/auth/redefinir-senha", response_model=PortalSimpleAcceptedResponse)
def redefinir_senha_clinica(
    payload: PortalPasswordResetConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _assert_password_login_enabled()
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=422, detail="A confirmacao de senha nao confere.")

    reset_token = validate_password_reset_token_or_401(get_password_reset_token(db, payload.reset_token))
    account = db.query(PortalClinicAccount).filter(PortalClinicAccount.id == reset_token.account_id).first()
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="Conta da clinica indisponivel.")

    account.password_hash = hash_password(payload.password)
    account.password_changed_at = utcnow()
    account.force_mfa_on_next_login = True
    reset_token.used_at = utcnow()
    db.commit()
    revoke_sessions_for_account(
        db,
        account_id=account.id,
        reason="password-reset",
    )

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_account",
        acao="PORTAL_CLINIC_PASSWORD_RESET_COMPLETED",
        descricao="Senha da clinica redefinida com sucesso.",
        entidade_id=account.id,
        detalhes={"clinica_id": account.clinica_id},
        request=request,
    )
    return PortalSimpleAcceptedResponse(message="Senha redefinida com sucesso.")


@router.post("/auth/trocar-senha", response_model=PortalSimpleAcceptedResponse)
def trocar_senha_clinica(
    payload: PortalClinicPasswordChangeRequest,
    request: Request,
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    _assert_password_login_enabled()
    if portal_session.actor_type != "clinica" or not portal_session.account_id:
        raise HTTPException(status_code=403, detail="Sessao do portal sem acesso para clinica.")
    if payload.nova_senha != payload.nova_senha_confirmacao:
        raise HTTPException(status_code=422, detail="A confirmacao de senha nao confere.")

    account = (
        db.query(PortalClinicAccount)
        .filter(PortalClinicAccount.id == portal_session.account_id)
        .first()
    )
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="Conta da clinica indisponivel.")
    if not verify_password(payload.senha_atual, account.password_hash):
        raise HTTPException(status_code=401, detail="Senha atual incorreta.")

    account.password_hash = hash_password(payload.nova_senha)
    account.password_changed_at = utcnow()
    account.must_change_password = False
    account.force_mfa_on_next_login = False
    db.commit()

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_account",
        acao="PORTAL_CLINIC_PASSWORD_CHANGED_BY_USER",
        descricao="Senha da clinica trocada pelo proprio usuario autenticado.",
        entidade_id=account.id,
        detalhes={"clinica_id": account.clinica_id},
        request=request,
    )
    return PortalSimpleAcceptedResponse(message="Senha atualizada com sucesso.")
