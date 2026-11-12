from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.portal_security import create_portal_session_token
from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_CLINICA,
    PORTAL_PARTNER_TYPE_VETERINARIO,
    PortalPartnerProfile,
)
from app.models.portal_partner_auth import (
    PortalPartnerAccount,
    PortalPartnerAuthChallenge,
    PortalPartnerInvite,
    PortalPartnerPasswordResetToken,
    PortalPartnerSession,
)
from app.services.portal_clinic_auth_service import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_LOCKED,
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_REVOKED,
    CHALLENGE_STATUS_CONSUMED,
    CHALLENGE_STATUS_EXPIRED,
    CHALLENGE_STATUS_LOCKED,
    CHALLENGE_STATUS_PENDING,
    CHALLENGE_TYPE_LOGIN_MFA,
    INVITE_STATUS_EXPIRED,
    INVITE_STATUS_PENDING,
    INVITE_STATUS_REVOKED,
    INVITE_STATUS_USED,
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_EXPIRED,
    SESSION_STATUS_LOGGED_OUT,
    SESSION_STATUS_REVOKED,
    challenge_expires_at,
    hash_password,
    hash_secret,
    is_portal_refresh_cookie_secure,
    json_dump,
    json_load_dict,
    mask_email,
    mask_phone,
    normalize_email,
    password_reset_expires_at,
    request_user_agent_hash,
    trusted_session_expires_at,
    utcnow,
    verify_password,
)
from app.services.portal_delivery_service import (
    PortalDeliveryResult,
    send_portal_email_message,
    send_portal_whatsapp_message,
)


def partner_type_label(tipo: str) -> str:
    if tipo == PORTAL_PARTNER_TYPE_VETERINARIO:
        return "Veterinario parceiro"
    return "Clinica parceira"


@dataclass(frozen=True)
class PortalPartnerAuthSessionResult:
    access_token: str
    expires_at: datetime
    scope: list[str]
    account_id: int
    partner_id: int
    partner_nome: str
    partner_tipo: str
    partner_tipo_label: str
    auth_method: str
    clinica_id: int | None = None
    refresh_token: str | None = None
    trusted_session_expires_at: datetime | None = None
    session_id: int | None = None
    session_reference: str | None = None


def build_partner_activation_url(request: Request, invite_token: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/veterinario-parceiro/ativar/{invite_token}"


def build_partner_portal_url(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/veterinario-parceiro"


def build_partner_password_reset_url(request: Request, reset_token: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/veterinario-parceiro/redefinir-senha?token={reset_token}"


def get_active_partner_or_404(
    db: Session,
    partner_id: int,
    *,
    allowed_types: set[str] | None = None,
) -> PortalPartnerProfile:
    partner = db.query(PortalPartnerProfile).filter(PortalPartnerProfile.id == partner_id).first()
    if partner is None or not bool(partner.ativo):
        raise HTTPException(status_code=404, detail="Parceiro externo nao encontrado.")
    if allowed_types and partner.tipo not in allowed_types:
        raise HTTPException(status_code=409, detail="Este parceiro nao usa este fluxo de acesso.")
    return partner


def expire_partner_invite_if_needed(db: Session, invite: PortalPartnerInvite) -> bool:
    if invite.expires_at and invite.expires_at <= utcnow():
        if invite.status == INVITE_STATUS_PENDING:
            invite.status = INVITE_STATUS_EXPIRED
            db.commit()
        return True
    return False


def expire_partner_auth_challenge_if_needed(db: Session, challenge: PortalPartnerAuthChallenge) -> bool:
    if challenge.expires_at and challenge.expires_at <= utcnow():
        if challenge.status == CHALLENGE_STATUS_PENDING:
            challenge.status = CHALLENGE_STATUS_EXPIRED
            db.commit()
        return True
    return False


def expire_partner_session_if_needed(db: Session, session: PortalPartnerSession) -> bool:
    if session.trusted_until and session.trusted_until <= utcnow():
        if session.status == SESSION_STATUS_ACTIVE:
            session.status = SESSION_STATUS_EXPIRED
            db.commit()
        return True
    return False


def revoke_active_invites_for_partner(db: Session, partner_id: int) -> int:
    invites = (
        db.query(PortalPartnerInvite)
        .filter(
            PortalPartnerInvite.partner_id == partner_id,
            PortalPartnerInvite.status == INVITE_STATUS_PENDING,
        )
        .all()
    )
    count = 0
    now = utcnow()
    for invite in invites:
        invite.status = INVITE_STATUS_REVOKED
        invite.revoked_at = now
        count += 1
    if count:
        db.commit()
    return count


def create_partner_invite(
    db: Session,
    *,
    partner_id: int,
    delivery_channel: str,
    delivery_target: str,
    expires_in_hours: int,
    created_by_user_id: int | None,
) -> tuple[PortalPartnerInvite, str]:
    revoke_active_invites_for_partner(db, partner_id)
    raw_token = secrets.token_urlsafe(32)
    invite = PortalPartnerInvite(
        partner_id=partner_id,
        token_hash=hash_secret("portal_partner_invite", raw_token),
        status=INVITE_STATUS_PENDING,
        delivery_channel=(delivery_channel or "whatsapp").strip().lower() or "whatsapp",
        delivery_target_masked=mask_phone(delivery_target) if delivery_channel == "whatsapp" else mask_email(delivery_target),
        expires_at=utcnow() + timedelta(hours=max(1, int(expires_in_hours))),
        created_by_user_id=created_by_user_id,
        contexto_json=json_dump({"delivery_target": delivery_target}),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, raw_token


def get_partner_invite_by_raw_token(db: Session, raw_token: str) -> PortalPartnerInvite | None:
    invite = (
        db.query(PortalPartnerInvite)
        .filter(PortalPartnerInvite.token_hash == hash_secret("portal_partner_invite", raw_token))
        .first()
    )
    if invite:
        expire_partner_invite_if_needed(db, invite)
    return invite


def get_partner_account_by_email(db: Session, email: str) -> PortalPartnerAccount | None:
    return (
        db.query(PortalPartnerAccount)
        .filter(PortalPartnerAccount.email_normalized == normalize_email(email))
        .first()
    )


def get_active_partner_account(db: Session, partner_id: int) -> PortalPartnerAccount | None:
    return (
        db.query(PortalPartnerAccount)
        .filter(
            PortalPartnerAccount.partner_id == partner_id,
            PortalPartnerAccount.status.in_([ACCOUNT_STATUS_PENDING, ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_LOCKED]),
            PortalPartnerAccount.revoked_at.is_(None),
        )
        .order_by(PortalPartnerAccount.id.desc())
        .first()
    )


def create_or_replace_pending_partner_account(
    db: Session,
    *,
    partner_id: int,
    email: str,
    responsavel_nome: str,
    password: str,
) -> PortalPartnerAccount:
    normalized_email = normalize_email(email)
    existing_by_email = get_partner_account_by_email(db, normalized_email)
    if existing_by_email and existing_by_email.status != ACCOUNT_STATUS_REVOKED:
        if existing_by_email.status == ACCOUNT_STATUS_PENDING and existing_by_email.partner_id == partner_id:
            existing_by_email.status = ACCOUNT_STATUS_REVOKED
            existing_by_email.revoked_at = utcnow()
        else:
            raise HTTPException(status_code=409, detail="Ja existe uma conta de parceiro para este email.")

    existing_for_partner = get_active_partner_account(db, partner_id)
    if existing_for_partner and existing_for_partner.status == ACCOUNT_STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="Este parceiro ja possui conta ativa.")
    if existing_for_partner and existing_for_partner.status == ACCOUNT_STATUS_PENDING:
        existing_for_partner.status = ACCOUNT_STATUS_REVOKED
        existing_for_partner.revoked_at = utcnow()

    if existing_by_email and existing_by_email.status == ACCOUNT_STATUS_REVOKED:
        account = existing_by_email
        account.partner_id = partner_id
        account.email_normalized = normalized_email
        account.responsavel_nome = responsavel_nome.strip()
        account.password_hash = hash_password(password)
        account.email_verified_at = None
        account.status = ACCOUNT_STATUS_PENDING
        account.activated_at = None
        account.last_login_at = None
        account.password_changed_at = utcnow()
        account.force_mfa_on_next_login = False
        account.revoked_at = None
    else:
        account = PortalPartnerAccount(
            partner_id=partner_id,
            email_normalized=normalized_email,
            responsavel_nome=responsavel_nome.strip(),
            password_hash=hash_password(password),
            status=ACCOUNT_STATUS_PENDING,
            password_changed_at=utcnow(),
        )
        db.add(account)
    db.commit()
    db.refresh(account)
    return account


def create_partner_auth_challenge(
    db: Session,
    *,
    account_id: int,
    partner_id: int,
    challenge_type: str,
    context: dict | None = None,
    expires_minutes: int,
) -> tuple[PortalPartnerAuthChallenge, str]:
    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = secrets.token_urlsafe(24)
    challenge = PortalPartnerAuthChallenge(
        challenge_id=challenge_id,
        account_id=account_id,
        partner_id=partner_id,
        challenge_type=challenge_type,
        code_hash=hash_secret(f"portal_partner_auth_code:{challenge_id}", raw_code),
        status=CHALLENGE_STATUS_PENDING,
        failed_attempts=0,
        max_attempts=max(1, int(settings.PORTAL_CLINIC_MAX_AUTH_ATTEMPTS)),
        expires_at=challenge_expires_at(expires_minutes),
        contexto_json=json_dump(context),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge, raw_code


def lock_partner_auth_challenge_if_needed(db: Session, challenge: PortalPartnerAuthChallenge) -> None:
    if challenge.failed_attempts >= challenge.max_attempts:
        challenge.status = CHALLENGE_STATUS_LOCKED
        db.commit()


def verify_partner_auth_challenge_code(
    db: Session,
    *,
    challenge: PortalPartnerAuthChallenge,
    code: str,
) -> None:
    if expire_partner_auth_challenge_if_needed(db, challenge):
        raise HTTPException(status_code=410, detail="Codigo expirado.")
    if challenge.status != CHALLENGE_STATUS_PENDING:
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    expected_hash = hash_secret(f"portal_partner_auth_code:{challenge.challenge_id}", code.strip())
    if challenge.code_hash != expected_hash:
        challenge.failed_attempts += 1
        db.commit()
        lock_partner_auth_challenge_if_needed(db, challenge)
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    challenge.status = CHALLENGE_STATUS_CONSUMED
    challenge.consumed_at = utcnow()
    db.commit()


def send_partner_login_mfa_code(
    *,
    destination: str,
    responsavel_nome: str,
    partner_nome: str,
    code: str,
    expires_in_minutes: int,
) -> PortalDeliveryResult:
    body = (
        f"Ola, {responsavel_nome}.\n\n"
        f"Use o codigo abaixo para confirmar o login do parceiro {partner_nome} no Portal Fort Cordis:\n\n"
        f"{code}\n\n"
        f"Este codigo expira em {expires_in_minutes} minuto(s).\n"
        "Se voce nao reconhece esta tentativa de acesso, ignore esta mensagem.\n"
    )
    return send_portal_email_message(
        destination=destination,
        subject="Confirme o login do parceiro - Portal Fort Cordis",
        body=body,
    )


def send_partner_password_reset_email(
    *,
    destination: str,
    responsavel_nome: str,
    partner_nome: str,
    reset_url: str,
    expires_in_minutes: int,
) -> PortalDeliveryResult:
    body = (
        f"Ola, {responsavel_nome}.\n\n"
        f"Recebemos um pedido para redefinir a senha do parceiro {partner_nome} no Portal Fort Cordis.\n\n"
        f"Acesse o link abaixo para continuar:\n{reset_url}\n\n"
        f"Este link expira em {expires_in_minutes} minuto(s).\n"
        "Se voce nao solicitou a redefinicao, ignore esta mensagem.\n"
    )
    return send_portal_email_message(
        destination=destination,
        subject="Redefina a senha do parceiro - Portal Fort Cordis",
        body=body,
    )


def send_partner_whatsapp_invite(
    *,
    destination: str,
    partner_nome: str,
    activation_url: str,
    expires_in_hours: int,
) -> PortalDeliveryResult:
    return send_portal_whatsapp_message(
        destination=destination,
        message=(
            f"Fort Cordis: o parceiro {partner_nome} ja pode ativar o portal seguro para consultar exames e laudos liberados. "
            f"Use este link individual para criar a senha de acesso: {activation_url} . "
            f"Este convite expira em {expires_in_hours} hora(s) e nao deve ser compartilhado fora da equipe autorizada."
        ),
        metadata={
            "invite_kind": "portal_partner_activation",
            "activation_url": activation_url,
            "expires_in_hours": expires_in_hours,
            "partner_nome": partner_nome,
        },
    )


def send_partner_whatsapp_login_access(
    *,
    destination: str,
    partner_nome: str,
    portal_url: str,
    account_email: str,
) -> PortalDeliveryResult:
    return send_portal_whatsapp_message(
        destination=destination,
        message=(
            f"Fort Cordis: o parceiro {partner_nome} ja tem acesso ativo ao portal seguro. "
            f"Use este link para entrar: {portal_url} . "
            f"Email de acesso: {account_email}. Se a senha tiver sido esquecida, use a opcao 'Esqueci minha senha' na tela de entrada."
        ),
        metadata={
            "invite_kind": "portal_partner_login_access",
            "portal_url": portal_url,
            "account_email": account_email,
            "partner_nome": partner_nome,
        },
    )


def set_partner_refresh_cookie(response: Response, token: str, *, expires_at: datetime, request: Request | None = None) -> None:
    max_age = max(60, int((expires_at - utcnow()).total_seconds()))
    response.set_cookie(
        key=settings.PORTAL_PARTNER_REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_portal_refresh_cookie_secure(request),
        samesite=settings.PORTAL_CLINIC_REFRESH_COOKIE_SAMESITE,
        max_age=max_age,
        path=settings.PORTAL_CLINIC_REFRESH_COOKIE_PATH,
        domain=settings.PORTAL_CLINIC_REFRESH_COOKIE_DOMAIN,
    )


def clear_partner_refresh_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(
        key=settings.PORTAL_PARTNER_REFRESH_COOKIE_NAME,
        path=settings.PORTAL_CLINIC_REFRESH_COOKIE_PATH,
        domain=settings.PORTAL_CLINIC_REFRESH_COOKIE_DOMAIN,
        secure=is_portal_refresh_cookie_secure(request),
        samesite=settings.PORTAL_CLINIC_REFRESH_COOKIE_SAMESITE,
    )


def get_partner_refresh_cookie(request: Request) -> str:
    return (request.cookies.get(settings.PORTAL_PARTNER_REFRESH_COOKIE_NAME) or "").strip()


def create_partner_refresh_session(
    db: Session,
    *,
    account_id: int,
    partner_id: int,
    request: Request | None,
    trusted_hours: int,
) -> tuple[PortalPartnerSession, str]:
    raw_token = secrets.token_urlsafe(32)
    session = PortalPartnerSession(
        account_id=account_id,
        partner_id=partner_id,
        refresh_token_hash=hash_secret("portal_partner_refresh", raw_token),
        device_label="computador-do-parceiro",
        user_agent_hash=request_user_agent_hash(request),
        trusted_until=trusted_session_expires_at(trusted_hours),
        last_seen_at=utcnow(),
        status=SESSION_STATUS_ACTIVE,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, raw_token


def get_partner_session_by_refresh_token(db: Session, raw_token: str) -> PortalPartnerSession | None:
    if not raw_token:
        return None
    session = (
        db.query(PortalPartnerSession)
        .filter(PortalPartnerSession.refresh_token_hash == hash_secret("portal_partner_refresh", raw_token))
        .first()
    )
    if session:
        expire_partner_session_if_needed(db, session)
    return session


def revoke_partner_session(
    db: Session,
    session: PortalPartnerSession,
    *,
    reason: str,
    status_value: str = SESSION_STATUS_REVOKED,
) -> None:
    session.status = status_value
    session.revoked_reason = (reason or "").strip() or None
    session.revoked_at = utcnow()
    session.last_seen_at = utcnow()
    db.commit()


def revoke_partner_sessions(db: Session, *, partner_id: int, reason: str) -> int:
    sessions = (
        db.query(PortalPartnerSession)
        .filter(
            PortalPartnerSession.partner_id == partner_id,
            PortalPartnerSession.status == SESSION_STATUS_ACTIVE,
        )
        .all()
    )
    if not sessions:
        return 0
    now = utcnow()
    for session in sessions:
        session.status = SESSION_STATUS_REVOKED
        session.revoked_reason = reason or "revogada"
        session.revoked_at = now
        session.last_seen_at = now
    db.commit()
    return len(sessions)


def build_partner_session_result(
    *,
    account: PortalPartnerAccount,
    partner: PortalPartnerProfile,
    auth_reference: str,
    auth_method: str,
    session_id: int | None = None,
    trusted_until_at: datetime | None = None,
) -> PortalPartnerAuthSessionResult:
    scope = ["partner:read", "exam:read", "exam:download"]
    access_token, expires_at = create_portal_session_token(
        actor_type="parceiro",
        actor_id=partner.id,
        challenge_id=auth_reference,
        clinica_id=partner.clinica_id,
        display_name=account.responsavel_nome,
        channel="email_password",
        scope=scope,
        account_id=account.id,
        session_id=session_id,
        auth_method=auth_method,
    )
    return PortalPartnerAuthSessionResult(
        access_token=access_token,
        expires_at=expires_at,
        scope=scope,
        account_id=account.id,
        partner_id=partner.id,
        partner_nome=partner.nome_exibicao,
        partner_tipo=partner.tipo,
        partner_tipo_label=partner_type_label(partner.tipo),
        clinica_id=partner.clinica_id,
        auth_method=auth_method,
        trusted_session_expires_at=trusted_until_at,
        session_id=session_id,
        session_reference=auth_reference,
    )


def issue_partner_session(
    db: Session,
    *,
    account: PortalPartnerAccount,
    partner: PortalPartnerProfile,
    request: Request | None,
    remember_device_until_shift_end: bool,
    auth_reference: str,
    auth_method: str,
) -> PortalPartnerAuthSessionResult:
    refresh_token = None
    trusted_until_at = None
    session_id = None
    if remember_device_until_shift_end:
        session, raw_refresh_token = create_partner_refresh_session(
            db,
            account_id=account.id,
            partner_id=partner.id,
            request=request,
            trusted_hours=settings.PORTAL_CLINIC_TRUSTED_SESSION_HOURS,
        )
        refresh_token = raw_refresh_token
        trusted_until_at = session.trusted_until
        session_id = session.id

    result = build_partner_session_result(
        account=account,
        partner=partner,
        auth_reference=auth_reference,
        auth_method=auth_method,
        session_id=session_id,
        trusted_until_at=trusted_until_at,
    )
    return PortalPartnerAuthSessionResult(
        access_token=result.access_token,
        expires_at=result.expires_at,
        scope=result.scope,
        account_id=result.account_id,
        partner_id=result.partner_id,
        partner_nome=result.partner_nome,
        partner_tipo=result.partner_tipo,
        partner_tipo_label=result.partner_tipo_label,
        clinica_id=result.clinica_id,
        auth_method=result.auth_method,
        refresh_token=refresh_token,
        trusted_session_expires_at=trusted_until_at,
        session_id=session_id,
        session_reference=auth_reference,
    )


def maybe_require_partner_mfa(account: PortalPartnerAccount, *, remember_device_until_shift_end: bool) -> bool:
    del remember_device_until_shift_end
    return bool(account.force_mfa_on_next_login)


def create_partner_password_reset_token(
    db: Session,
    *,
    account_id: int,
) -> tuple[PortalPartnerPasswordResetToken, str]:
    raw_token = secrets.token_urlsafe(32)
    token = PortalPartnerPasswordResetToken(
        account_id=account_id,
        token_hash=hash_secret("portal_partner_password_reset", raw_token),
        expires_at=password_reset_expires_at(settings.PORTAL_CLINIC_PASSWORD_RESET_EXPIRE_MINUTES),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token, raw_token


def get_partner_password_reset_token(db: Session, raw_token: str) -> PortalPartnerPasswordResetToken | None:
    if not raw_token:
        return None
    return (
        db.query(PortalPartnerPasswordResetToken)
        .filter(PortalPartnerPasswordResetToken.token_hash == hash_secret("portal_partner_password_reset", raw_token))
        .first()
    )


def validate_partner_password_reset_token_or_401(
    token: PortalPartnerPasswordResetToken | None,
) -> PortalPartnerPasswordResetToken:
    if token is None or token.revoked_at is not None or token.used_at is not None:
        raise HTTPException(status_code=401, detail="Link de redefinicao invalido ou expirado.")
    if token.expires_at <= utcnow():
        raise HTTPException(status_code=401, detail="Link de redefinicao invalido ou expirado.")
    return token


def get_partner_account_by_id(db: Session, account_id: int) -> PortalPartnerAccount | None:
    return db.query(PortalPartnerAccount).filter(PortalPartnerAccount.id == account_id).first()


def partner_allows_invite_flow(partner: PortalPartnerProfile) -> bool:
    return partner.tipo == PORTAL_PARTNER_TYPE_VETERINARIO


def logout_partner_session(
    db: Session,
    *,
    raw_refresh_token: str,
) -> None:
    session = get_partner_session_by_refresh_token(db, raw_refresh_token)
    if session:
        revoke_partner_session(db, session, reason="logout", status_value=SESSION_STATUS_LOGGED_OUT)
