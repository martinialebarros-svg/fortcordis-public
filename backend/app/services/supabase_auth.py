"""Supabase Auth through the existing FastAPI boundary (no browser admin key).

Authentication belongs to Supabase; account activation and permissions remain in
usuarios/papeis. Only admin-managed app_metadata can bind those two identities.
"""
from __future__ import annotations

from uuid import UUID
from urllib.parse import urlparse
import re

import httpx
from fastapi import HTTPException
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User


def request_auth(method: str, path: str, *, token: str = "", body=None, admin=False):
    url = settings.SUPABASE_URL.rstrip("/")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or parsed.query or parsed.fragment or parsed.path
        or not settings.SUPABASE_PUBLISHABLE_KEY.startswith("sb_publishable_")
    ):
        raise HTTPException(503, "Supabase Auth nao configurado.")
    key = settings.SUPABASE_SECRET_KEY if admin else settings.SUPABASE_PUBLISHABLE_KEY
    if not key:
        raise HTTPException(503, "Administracao do Supabase Auth nao configurada.")
    headers = {"apikey": key}
    if token or admin:
        headers["Authorization"] = f"Bearer {key if admin else token}"
    try:
        # Never follow redirects carrying API keys, passwords or bearer tokens.
        response = httpx.request(
            method, f"{url}/auth/v1/{path}", headers=headers, json=body,
            timeout=settings.SUPABASE_AUTH_TIMEOUT_SECONDS, follow_redirects=False,
        )
    except httpx.HTTPError:
        raise HTTPException(503, "Servico de autenticacao indisponivel.") from None
    if response.status_code == 429:
        raise HTTPException(429, "Muitas tentativas. Aguarde antes de tentar novamente.")
    if not admin and response.status_code in {400, 401, 403, 404, 422}:
        raise JWTError("Credenciais invalidas")
    if not 200 <= response.status_code < 300:
        raise HTTPException(503, "Servico de autenticacao indisponivel.")
    if response.status_code == 204:
        return {}
    try:
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except ValueError:
        raise HTTPException(503, "Resposta invalida do servico de autenticacao.") from None


def load_app_user(db: Session, identity: dict) -> User:
    try:
        UUID(identity["id"])
        local_id = identity.get("app_metadata", {}).get("fortcordis_user_id")
        if type(local_id) is not int or local_id <= 0:
            raise ValueError()
        if identity.get("is_anonymous") or not identity.get("email_confirmed_at"):
            raise ValueError()
        email = identity["email"].strip().casefold()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise JWTError("Identidade sem vinculo Fort Cordis") from None
    user = db.query(User).filter(User.id == local_id).first()
    if user is None or not isinstance(user.email, str) or user.email.strip().casefold() != email:
        raise JWTError("Identidade sem vinculo Fort Cordis")
    if user.ativo != 1:
        raise HTTPException(403, "Usuario inativo")
    return user


def get_user(db: Session, token: str) -> User:
    # Validates with the Auth server, including session revocation. Never trusts
    # getSession, an unverified JWT, email alone, or editable user_metadata.
    return load_app_user(db, request_auth("GET", "user", token=token))


def password_session(email: str, password: str) -> dict:
    return request_auth("POST", "token?grant_type=password", body={"email": email, "password": password})


def refresh_session(refresh_token: str) -> dict:
    return request_auth("POST", "token?grant_type=refresh_token", body={"refresh_token": refresh_token})


def sign_out(token: str) -> None:
    request_auth("POST", "logout?scope=local", token=token)


def admin_users() -> list[dict]:
    users = []
    page = 1
    while True:
        batch = request_auth("GET", f"admin/users?page={page}&per_page=100", admin=True).get("users", [])
        if not isinstance(batch, list):
            raise HTTPException(503, "Resposta invalida do servico de autenticacao.")
        users.extend(batch)
        if len(batch) < 100:
            return users
        page += 1


def find_identity(user: User) -> dict | None:
    matches = [item for item in admin_users() if item.get("app_metadata", {}).get("fortcordis_user_id") == user.id]
    if len(matches) > 1:
        raise HTTPException(409, "Mais de uma identidade vinculada ao usuario.")
    return matches[0] if matches else None


def has_importable_password_hash(value: str | None) -> bool:
    return bool(re.fullmatch(r"\$2[aby]\$(?:0[4-9]|[12][0-9]|3[01])\$[./A-Za-z0-9]{53}", value or ""))


def create_identity(user: User, *, password: str | None = None) -> dict:
    body = {
        "email": user.email, "email_confirm": True,
        "app_metadata": {"fortcordis_user_id": user.id},
    }
    if password is not None:
        body["password"] = password
    else:
        if not has_importable_password_hash(user.senha_hash):
            raise HTTPException(409, "A conta requer uma senha bcrypt valida antes da importacao.")
        body["password_hash"] = user.senha_hash
    return request_auth("POST", "admin/users", body=body, admin=True)


def update_identity(user: User, *, password: str | None = None) -> None:
    identity = find_identity(user)
    if identity is None:
        raise HTTPException(409, "Usuario ainda nao importado no Supabase Auth.")
    body = {"email": user.email, "email_confirm": True}
    if password:
        body["password"] = password
    request_auth("PUT", f"admin/users/{UUID(identity['id'])}", body=body, admin=True)
