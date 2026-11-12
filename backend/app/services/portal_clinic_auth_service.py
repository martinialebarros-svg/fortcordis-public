from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request, Response, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.portal_security import create_portal_session_token
from app.models.clinica import Clinica
from app.models.portal_clinic_auth import (
    PortalAuthChallenge,
    PortalClinicAccount,
    PortalClinicInvite,
    PortalClinicSession,
    PortalPasswordResetToken,
)
from app.services.portal_delivery_service import PortalDeliveryResult, send_portal_email_message
from app.services.whatsapp_agenda_service import normalize_whatsapp_number
from app.services.whatsapp_template_delivery_service import send_approved_utility_template

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$", "$2$")

INVITE_STATUS_PENDING = "pending"
INVITE_STATUS_USED = "used"
INVITE_STATUS_EXPIRED = "expired"
INVITE_STATUS_REVOKED = "revoked"

MAX_ACTIVE_CLINIC_MANAGERS = 5

ACCOUNT_STATUS_PENDING = "pending_verification"
ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_LOCKED = "locked"
ACCOUNT_STATUS_REVOKED = "revoked"

SESSION_STATUS_ACTIVE = "active"
SESSION_STATUS_EXPIRED = "expired"
SESSION_STATUS_REVOKED = "revoked"
SESSION_STATUS_LOGGED_OUT = "logged_out"

CHALLENGE_STATUS_PENDING = "pending"
CHALLENGE_STATUS_CONSUMED = "consumed"
CHALLENGE_STATUS_EXPIRED = "expired"
CHALLENGE_STATUS_LOCKED = "locked"

CHALLENGE_TYPE_EMAIL_VERIFICATION = "email_verification"
CHALLENGE_TYPE_LOGIN_MFA = "login_mfa"


@dataclass(frozen=True)
class PortalClinicAuthSessionResult:
    access_token: str
    expires_at: datetime
    scope: list[str]
    account_id: int
    clinica_id: int
    auth_method: str
    refresh_token: str | None = None
    trusted_session_expires_at: datetime | None = None
    session_id: int | None = None
    session_reference: str | None = None


def utcnow() -> datetime:
    return datetime.utcnow()


def normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    return digits


def mask_email(value: str | None) -> str:
    normalized = normalize_email(value)
    if "@" not in normalized:
        return "***"
    local, domain = normalized.split("@", 1)
    local_mask = (local[:2] + "***") if len(local) > 2 else "***"
    return f"{local_mask}@{domain}"


def mask_phone(value: str | None) -> str:
    digits = normalize_phone(value)
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


def json_dump(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def json_load_dict(value: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def is_clinica_active(clinica: Clinica | None) -> bool:
    ativo = getattr(clinica, "ativo", False)
    return clinica is not None and ativo not in (False, 0, "0")


def hash_secret(kind: str, raw_value: str) -> str:
    raw = f"{kind}:{raw_value}:{settings.SECRET_KEY}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def generate_challenge_id() -> str:
    return secrets.token_urlsafe(24)


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# Palavras curtas, sem acento, sem ambiguidade visual/sonora - usadas so
# para compor a senha temporaria de convite (formato `palavra-NNNN`).
_TEMP_PASSWORD_WORDS = (
    "abelha", "amora", "anel", "arco", "aroma", "avela", "baleia", "banana",
    "barco", "bode", "bolha", "bolo", "bosque", "cacto", "cafe", "campo",
    "canela", "canoa", "carvao", "casaco", "cesta", "chave", "chuva",
    "cobra", "coelho", "coral", "corvo", "creme", "cristal", "diamante",
    "dourado", "estrela", "fada", "farol", "flauta", "flecha", "flor",
    "floresta", "folha", "fonte", "foguete", "fumaca", "funil", "gaivota",
    "galho", "garfo", "gato", "gaveta", "girafa", "grama", "grao", "grilo",
    "guarda", "harpa", "ilha", "jaca", "jangada", "jardim", "jarra",
    "joaninha", "lago", "lagosta", "laranja", "leao", "leque", "limao",
    "lince", "lontra", "louva", "luar", "lucia", "macaco", "maca", "mango",
    "manteiga", "mapa", "mar", "marfim", "melancia", "melao", "menta",
    "mistura", "morango", "mostarda", "musgo", "neve", "noz", "nuvem",
    "oceano", "orquidea", "ostra", "outono", "ovelha", "paisagem", "palma",
    "pandeiro", "panela", "pantera", "papagaio", "pardal", "pasta",
    "pavao", "pedra", "peixe", "pente", "pera", "perola", "pinha",
    "pinheiro", "pipoca", "planeta", "pomba", "ponte", "porta", "praia",
    "prata", "quintal", "raio", "rio", "roda", "rosa", "sabao", "sacola",
    "sal", "salada", "sapato", "sapo", "seda", "selva", "sino", "sol",
    "tapete", "tartaruga", "tesoura", "tigre", "tomate", "tordo", "torre",
    "tucano", "tulipa", "uva", "vagalume", "vale", "vaso", "vela",
    "velame", "vento", "verde", "vidro", "vinho", "violeta", "zebra",
)


def gerar_senha_temporaria() -> str:
    """Senha temporaria facil de ler/digitar: `palavra-NNNN`.

    Usada quando o admin gera uma conta de clinica com senha ja
    definida (em vez de a clinica criar a propria senha) - o MFA
    obrigatorio enquanto `must_change_password` estiver ligado
    compensa a entropia menor.
    """
    palavra = secrets.choice(_TEMP_PASSWORD_WORDS)
    digitos = f"{secrets.randbelow(10_000):04d}"
    return f"{palavra}-{digitos}"


def hash_password(plain_password: str) -> str:
    pwd_bytes = plain_password.encode("utf-8")[:72]
    plain_truncated = pwd_bytes.decode("utf-8", errors="ignore")
    return pwd_context.hash(plain_truncated)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password or not hashed_password.startswith(_BCRYPT_PREFIXES):
        return False
    pwd_bytes = plain_password.encode("utf-8")[:72]
    plain_truncated = pwd_bytes.decode("utf-8", errors="ignore")
    return pwd_context.verify(plain_truncated, hashed_password)


def challenge_expires_at(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=max(1, int(minutes)))


def trusted_session_expires_at(hours: int) -> datetime:
    return utcnow() + timedelta(hours=max(1, int(hours)))


def password_reset_expires_at(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=max(1, int(minutes)))


def _request_uses_https(request: Request | None = None) -> bool:
    if request is None:
        return False
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").strip().lower()
    if forwarded_proto:
        first_value = forwarded_proto.split(",")[0].strip()
        if first_value == "https":
            return True
    return (request.url.scheme or "").strip().lower() == "https"


def is_portal_refresh_cookie_secure(request: Request | None = None) -> bool:
    if settings.PORTAL_CLINIC_REFRESH_COOKIE_SECURE:
        return True
    if settings.APP_ENV.lower() in {"production", "staging", "stage"}:
        return True
    return _request_uses_https(request)


def set_portal_refresh_cookie(response: Response, token: str, *, expires_at: datetime, request: Request | None = None) -> None:
    max_age = max(60, int((expires_at - utcnow()).total_seconds()))
    response.set_cookie(
        key=settings.PORTAL_CLINIC_REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_portal_refresh_cookie_secure(request),
        samesite=settings.PORTAL_CLINIC_REFRESH_COOKIE_SAMESITE,
        max_age=max_age,
        path=settings.PORTAL_CLINIC_REFRESH_COOKIE_PATH,
        domain=settings.PORTAL_CLINIC_REFRESH_COOKIE_DOMAIN,
    )


def clear_portal_refresh_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(
        key=settings.PORTAL_CLINIC_REFRESH_COOKIE_NAME,
        path=settings.PORTAL_CLINIC_REFRESH_COOKIE_PATH,
        domain=settings.PORTAL_CLINIC_REFRESH_COOKIE_DOMAIN,
        secure=is_portal_refresh_cookie_secure(request),
        samesite=settings.PORTAL_CLINIC_REFRESH_COOKIE_SAMESITE,
    )


def get_portal_refresh_cookie(request: Request) -> str:
    return (request.cookies.get(settings.PORTAL_CLINIC_REFRESH_COOKIE_NAME) or "").strip()


def request_user_agent_hash(request: Request | None) -> str | None:
    if request is None:
        return None
    user_agent = (request.headers.get("user-agent") or "").strip()
    if not user_agent:
        return None
    return hash_secret("portal_user_agent", user_agent)


def build_activation_url(request: Request, invite_token: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/clinica-parceira/ativar/{invite_token}"


def build_clinic_portal_url(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/clinica-parceira"


def build_password_reset_url(request: Request, reset_token: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/clinica-parceira/redefinir-senha?token={reset_token}"


def get_active_clinica_or_404(db: Session, clinica_id: int) -> Clinica:
    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    if not is_clinica_active(clinica):
        raise HTTPException(status_code=404, detail="Clinica nao encontrada.")
    return clinica


def expire_invite_if_needed(db: Session, invite: PortalClinicInvite) -> bool:
    if invite.expires_at and invite.expires_at <= utcnow():
        if invite.status == INVITE_STATUS_PENDING:
            invite.status = INVITE_STATUS_EXPIRED
            db.commit()
        return True
    return False


def expire_auth_challenge_if_needed(db: Session, challenge: PortalAuthChallenge) -> bool:
    if challenge.expires_at and challenge.expires_at <= utcnow():
        if challenge.status == CHALLENGE_STATUS_PENDING:
            challenge.status = CHALLENGE_STATUS_EXPIRED
            db.commit()
        return True
    return False


def expire_session_if_needed(db: Session, session: PortalClinicSession) -> bool:
    if session.trusted_until and session.trusted_until <= utcnow():
        if session.status == SESSION_STATUS_ACTIVE:
            session.status = SESSION_STATUS_EXPIRED
            db.commit()
        return True
    return False


def revoke_pending_invites_for_clinica_email(db: Session, clinica_id: int, account_email: str | None) -> int:
    """Revoga apenas o convite pendente do mesmo email nesta clinica, preservando convites de outros gestores."""
    normalized_email = normalize_email(account_email)
    invites = (
        db.query(PortalClinicInvite)
        .filter(
            PortalClinicInvite.clinica_id == clinica_id,
            PortalClinicInvite.status == INVITE_STATUS_PENDING,
        )
        .all()
    )
    count = 0
    now = utcnow()
    for invite in invites:
        invite_email = normalize_email(json_load_dict(invite.contexto_json).get("account_email"))
        if invite_email != normalized_email:
            continue
        invite.status = INVITE_STATUS_REVOKED
        invite.revoked_at = now
        count += 1
    if count:
        db.commit()
    return count


def count_active_clinic_manager_slots(db: Session, clinica_id: int) -> int:
    """Conta gestores com conta nao revogada ou convite pendente, para limitar convites simultaneos por clinica."""
    active_accounts = len(get_active_accounts_by_clinica(db, clinica_id))
    pending_invites = (
        db.query(PortalClinicInvite)
        .filter(
            PortalClinicInvite.clinica_id == clinica_id,
            PortalClinicInvite.status == INVITE_STATUS_PENDING,
        )
        .count()
    )
    return active_accounts + pending_invites


def create_clinic_invite(
    db: Session,
    *,
    clinica_id: int,
    delivery_channel: str,
    delivery_target: str,
    account_email: str | None = None,
    expires_in_hours: int,
    created_by_user_id: int | None,
) -> tuple[PortalClinicInvite, str]:
    revoke_pending_invites_for_clinica_email(db, clinica_id, account_email)
    raw_token = generate_opaque_token()
    normalized_account_email = normalize_email(account_email)
    invite = PortalClinicInvite(
        clinica_id=clinica_id,
        token_hash=hash_secret("portal_clinic_invite", raw_token),
        status=INVITE_STATUS_PENDING,
        delivery_channel=(delivery_channel or "whatsapp").strip().lower() or "whatsapp",
        delivery_target_masked=mask_phone(delivery_target) if delivery_channel == "whatsapp" else mask_email(delivery_target),
        expires_at=utcnow() + timedelta(hours=max(1, int(expires_in_hours))),
        created_by_user_id=created_by_user_id,
        contexto_json=json_dump(
            {
                "delivery_target": delivery_target,
                "account_email": normalized_account_email or None,
            }
        ),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, raw_token


def get_invite_by_raw_token(db: Session, raw_token: str) -> PortalClinicInvite | None:
    token_hash = hash_secret("portal_clinic_invite", raw_token)
    invite = (
        db.query(PortalClinicInvite)
        .filter(PortalClinicInvite.token_hash == token_hash)
        .first()
    )
    if invite:
        expire_invite_if_needed(db, invite)
    return invite


def get_account_by_email(db: Session, email: str) -> PortalClinicAccount | None:
    return (
        db.query(PortalClinicAccount)
        .filter(PortalClinicAccount.email_normalized == normalize_email(email))
        .first()
    )


def get_active_accounts_by_clinica(db: Session, clinica_id: int) -> list[PortalClinicAccount]:
    """Retorna todas as contas nao revogadas da clinica, mais recente primeiro (uma por gestor convidado)."""
    return (
        db.query(PortalClinicAccount)
        .filter(
            PortalClinicAccount.clinica_id == clinica_id,
            PortalClinicAccount.status.in_([ACCOUNT_STATUS_PENDING, ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_LOCKED]),
            PortalClinicAccount.revoked_at.is_(None),
        )
        .order_by(PortalClinicAccount.id.desc())
        .all()
    )


def create_or_replace_pending_account(
    db: Session,
    *,
    clinica_id: int,
    email: str,
    responsavel_nome: str,
    password: str,
) -> PortalClinicAccount:
    normalized_email = normalize_email(email)
    existing_by_email = get_account_by_email(db, normalized_email)
    if existing_by_email and existing_by_email.status != ACCOUNT_STATUS_REVOKED:
        if existing_by_email.status == ACCOUNT_STATUS_PENDING and existing_by_email.clinica_id == clinica_id:
            existing_by_email.status = ACCOUNT_STATUS_REVOKED
            existing_by_email.revoked_at = utcnow()
        else:
            raise HTTPException(status_code=409, detail="Ja existe uma conta para este email.")

    if existing_by_email and existing_by_email.status == ACCOUNT_STATUS_REVOKED:
        account = existing_by_email
        account.clinica_id = clinica_id
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
        account = PortalClinicAccount(
            clinica_id=clinica_id,
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


def create_auth_challenge(
    db: Session,
    *,
    account_id: int,
    clinica_id: int,
    challenge_type: str,
    context: dict[str, Any] | None = None,
    expires_minutes: int,
) -> tuple[PortalAuthChallenge, str]:
    raw_code = generate_code()
    challenge_id = generate_challenge_id()
    challenge = PortalAuthChallenge(
        challenge_id=challenge_id,
        account_id=account_id,
        clinica_id=clinica_id,
        challenge_type=challenge_type,
        code_hash=hash_secret(f"portal_auth_code:{challenge_id}", raw_code),
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


def lock_auth_challenge_if_needed(db: Session, challenge: PortalAuthChallenge) -> None:
    if challenge.failed_attempts >= challenge.max_attempts:
        challenge.status = CHALLENGE_STATUS_LOCKED
        db.commit()


def verify_auth_challenge_code(
    db: Session,
    *,
    challenge: PortalAuthChallenge,
    code: str,
) -> None:
    if expire_auth_challenge_if_needed(db, challenge):
        raise HTTPException(status_code=410, detail="Codigo expirado.")
    if challenge.status != CHALLENGE_STATUS_PENDING:
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    expected_hash = hash_secret(f"portal_auth_code:{challenge.challenge_id}", code.strip())
    if challenge.code_hash != expected_hash:
        challenge.failed_attempts += 1
        db.commit()
        lock_auth_challenge_if_needed(db, challenge)
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    challenge.status = CHALLENGE_STATUS_CONSUMED
    challenge.consumed_at = utcnow()
    db.commit()


def send_email_verification_code(
    *,
    destination: str,
    responsavel_nome: str,
    clinica_nome: str,
    code: str,
    expires_in_minutes: int,
) -> PortalDeliveryResult:
    body = (
        f"Ola, {responsavel_nome}.\n\n"
        f"Use o codigo abaixo para ativar o acesso da clinica {clinica_nome} no Portal Fort Cordis:\n\n"
        f"{code}\n\n"
        f"Este codigo expira em {expires_in_minutes} minuto(s).\n"
        "Se voce nao reconhece esta solicitacao, ignore esta mensagem.\n"
    )
    return send_portal_email_message(
        destination=destination,
        subject="Confirme o email da clinica - Portal Fort Cordis",
        body=body,
    )


def send_login_mfa_code(
    *,
    destination: str,
    responsavel_nome: str,
    clinica_nome: str,
    code: str,
    expires_in_minutes: int,
) -> PortalDeliveryResult:
    body = (
        f"Ola, {responsavel_nome}.\n\n"
        f"Use o codigo abaixo para confirmar o login da clinica {clinica_nome} no Portal Fort Cordis:\n\n"
        f"{code}\n\n"
        f"Este codigo expira em {expires_in_minutes} minuto(s).\n"
        "Se voce nao reconhece esta tentativa de acesso, ignore esta mensagem.\n"
    )
    return send_portal_email_message(
        destination=destination,
        subject="Confirme o login da clinica - Portal Fort Cordis",
        body=body,
    )


def send_password_reset_email(
    *,
    destination: str,
    responsavel_nome: str,
    clinica_nome: str,
    reset_url: str,
    expires_in_minutes: int,
) -> PortalDeliveryResult:
    body = (
        f"Ola, {responsavel_nome}.\n\n"
        f"Recebemos um pedido para redefinir a senha da clinica {clinica_nome} no Portal Fort Cordis.\n\n"
        f"Acesse o link abaixo para continuar:\n{reset_url}\n\n"
        f"Este link expira em {expires_in_minutes} minuto(s).\n"
        "Se voce nao solicitou a redefinicao, ignore esta mensagem.\n"
    )
    return send_portal_email_message(
        destination=destination,
        subject="Redefina a senha da clinica - Portal Fort Cordis",
        body=body,
    )


def send_whatsapp_invite(
    *,
    destination: str,
    clinica_id: int,
    clinica_nome: str,
    activation_url: str,
    expires_in_hours: int,
    idempotency_key: str,
) -> PortalDeliveryResult:
    expira_em = f"{max(1, int(expires_in_hours))} hora(s)"
    send_approved_utility_template(
        template_key="portalClinicInviteActivation",
        subject_type="clinica",
        subject_id=clinica_id,
        destination=normalize_whatsapp_number(destination),
        parameters=[clinica_nome, activation_url, expira_em],
        idempotency_key=idempotency_key,
    )
    return PortalDeliveryResult(provider="whatsapp_business_template", channel="whatsapp")


def send_whatsapp_login_access(
    *,
    destination: str,
    clinica_id: int,
    clinica_nome: str,
    portal_url: str,
    account_email: str,
    idempotency_key: str,
) -> PortalDeliveryResult:
    send_approved_utility_template(
        template_key="portalClinicInviteLoginAccess",
        subject_type="clinica",
        subject_id=clinica_id,
        destination=normalize_whatsapp_number(destination),
        parameters=[clinica_nome, portal_url, account_email],
        idempotency_key=idempotency_key,
    )
    return PortalDeliveryResult(provider="whatsapp_business_template", channel="whatsapp")


def send_whatsapp_temporary_password(
    *,
    destination: str,
    clinica_id: int,
    clinica_nome: str,
    portal_url: str,
    account_email: str,
    senha_temporaria: str,
    idempotency_key: str,
) -> PortalDeliveryResult:
    send_approved_utility_template(
        template_key="portalClinicInviteTemporaryPassword",
        subject_type="clinica",
        subject_id=clinica_id,
        destination=normalize_whatsapp_number(destination),
        parameters=[clinica_nome, portal_url, account_email, senha_temporaria],
        idempotency_key=idempotency_key,
    )
    return PortalDeliveryResult(provider="whatsapp_business_template", channel="whatsapp")


def create_refresh_session(
    db: Session,
    *,
    account_id: int,
    clinica_id: int,
    request: Request | None,
    trusted_hours: int,
) -> tuple[PortalClinicSession, str]:
    raw_token = generate_opaque_token()
    session = PortalClinicSession(
        account_id=account_id,
        clinica_id=clinica_id,
        refresh_token_hash=hash_secret("portal_clinic_refresh", raw_token),
        device_label="computador-da-unidade",
        user_agent_hash=request_user_agent_hash(request),
        trusted_until=trusted_session_expires_at(trusted_hours),
        last_seen_at=utcnow(),
        status=SESSION_STATUS_ACTIVE,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, raw_token


def get_session_by_refresh_token(db: Session, raw_token: str) -> PortalClinicSession | None:
    if not raw_token:
        return None
    session = (
        db.query(PortalClinicSession)
        .filter(PortalClinicSession.refresh_token_hash == hash_secret("portal_clinic_refresh", raw_token))
        .first()
    )
    if session:
        expire_session_if_needed(db, session)
    return session


def revoke_session(db: Session, session: PortalClinicSession, *, reason: str, status_value: str = SESSION_STATUS_REVOKED) -> None:
    session.status = status_value
    session.revoked_reason = (reason or "").strip() or None
    session.revoked_at = utcnow()
    session.last_seen_at = utcnow()
    db.commit()


def revoke_sessions_for_account(db: Session, *, account_id: int, reason: str) -> int:
    """Revoga apenas as sessoes deste gestor, sem afetar sessoes de outros gestores da mesma clinica."""
    sessions = (
        db.query(PortalClinicSession)
        .filter(
            PortalClinicSession.account_id == account_id,
            PortalClinicSession.status == SESSION_STATUS_ACTIVE,
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


def revoke_sessions_for_clinica(db: Session, *, clinica_id: int, reason: str, session_id: int | None = None) -> int:
    query = db.query(PortalClinicSession).filter(
        PortalClinicSession.clinica_id == clinica_id,
        PortalClinicSession.status == SESSION_STATUS_ACTIVE,
    )
    if session_id is not None:
        query = query.filter(PortalClinicSession.id == session_id)
    sessions = query.all()
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


def build_clinic_session_result(
    *,
    account: PortalClinicAccount,
    clinica_id: int,
    auth_reference: str,
    auth_method: str,
    session_id: int | None = None,
    trusted_until_at: datetime | None = None,
) -> PortalClinicAuthSessionResult:
    scope = ["clinic:read", "exam:read", "exam:download"]
    access_token, expires_at = create_portal_session_token(
        actor_type="clinica",
        actor_id=clinica_id,
        challenge_id=auth_reference,
        clinica_id=clinica_id,
        display_name=account.responsavel_nome,
        channel="email_password",
        scope=scope,
        account_id=account.id,
        session_id=session_id,
        auth_method=auth_method,
    )
    return PortalClinicAuthSessionResult(
        access_token=access_token,
        expires_at=expires_at,
        scope=scope,
        account_id=account.id,
        clinica_id=clinica_id,
        auth_method=auth_method,
        trusted_session_expires_at=trusted_until_at,
        session_id=session_id,
        session_reference=auth_reference,
    )


def issue_clinic_session(
    db: Session,
    *,
    account: PortalClinicAccount,
    request: Request | None,
    remember_device_until_shift_end: bool,
    auth_reference: str,
    auth_method: str,
) -> PortalClinicAuthSessionResult:
    refresh_token = None
    trusted_until_at = None
    session_id = None
    if remember_device_until_shift_end:
        session, raw_refresh_token = create_refresh_session(
            db,
            account_id=account.id,
            clinica_id=account.clinica_id,
            request=request,
            trusted_hours=settings.PORTAL_CLINIC_TRUSTED_SESSION_HOURS,
        )
        refresh_token = raw_refresh_token
        trusted_until_at = session.trusted_until
        session_id = session.id

    result = build_clinic_session_result(
        account=account,
        clinica_id=account.clinica_id,
        auth_reference=auth_reference,
        auth_method=auth_method,
        session_id=session_id,
        trusted_until_at=trusted_until_at,
    )
    return PortalClinicAuthSessionResult(
        access_token=result.access_token,
        expires_at=result.expires_at,
        scope=result.scope,
        account_id=result.account_id,
        clinica_id=result.clinica_id,
        auth_method=result.auth_method,
        refresh_token=refresh_token,
        trusted_session_expires_at=trusted_until_at,
        session_id=session_id,
        session_reference=auth_reference,
    )


def maybe_require_mfa(account: PortalClinicAccount, *, remember_device_until_shift_end: bool) -> bool:
    return bool(account.force_mfa_on_next_login) or bool(account.must_change_password)


def create_password_reset_token(db: Session, *, account_id: int) -> tuple[PortalPasswordResetToken, str]:
    raw_token = generate_opaque_token()
    token = PortalPasswordResetToken(
        account_id=account_id,
        token_hash=hash_secret("portal_password_reset", raw_token),
        expires_at=password_reset_expires_at(settings.PORTAL_CLINIC_PASSWORD_RESET_EXPIRE_MINUTES),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token, raw_token


def get_password_reset_token(db: Session, raw_token: str) -> PortalPasswordResetToken | None:
    if not raw_token:
        return None
    return (
        db.query(PortalPasswordResetToken)
        .filter(PortalPasswordResetToken.token_hash == hash_secret("portal_password_reset", raw_token))
        .first()
    )


def validate_password_reset_token_or_401(token: PortalPasswordResetToken | None) -> PortalPasswordResetToken:
    if token is None or token.revoked_at is not None or token.used_at is not None:
        raise HTTPException(status_code=401, detail="Link de redefinicao invalido ou expirado.")
    if token.expires_at <= utcnow():
        raise HTTPException(status_code=401, detail="Link de redefinicao invalido ou expirado.")
    return token
