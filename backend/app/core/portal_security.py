from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import _extract_bearer_token

PORTAL_SESSION_AUDIENCE = "fortcordis-portal"
PORTAL_DOWNLOAD_AUDIENCE = "fortcordis-portal-download"
PORTAL_DOWNLOAD_TOKEN_HEADER = "x-portal-download-token"
PORTAL_QUERY_TOKEN_KEYS = {"access_token", "download_token", "token"}


@dataclass(frozen=True)
class PortalSessionContext:
    actor_type: str
    actor_id: int
    paciente_id: int | None
    clinica_id: int | None
    challenge_id: str
    display_name: str | None
    channel: str | None
    scope: tuple[str, ...]
    expires_at: datetime
    account_id: int | None = None
    session_id: int | None = None
    auth_method: str | None = None


@dataclass(frozen=True)
class PortalDownloadContext:
    actor_type: str
    actor_id: int
    paciente_id: int | None
    clinica_id: int | None
    exame_id: int
    anexo_id: int
    expires_at: datetime


def _utcnow() -> datetime:
    return datetime.utcnow()


def _portal_credentials_exception(detail: str = "Credenciais do portal invalidas") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_scope(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item).strip() for item in value]
    else:
        raw_items = []
    return tuple(item for item in raw_items if item)


def _coerce_expiration(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            pass
    raise JWTError("exp invalido")


def _reject_query_tokens(request: Request) -> None:
    if any(request.query_params.get(key) for key in PORTAL_QUERY_TOKEN_KEYS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao use token na URL do portal.",
        )


def _encode_portal_token(
    *,
    audience: str,
    token_kind: str,
    claims: dict[str, Any],
    expires_delta: timedelta,
) -> tuple[str, datetime]:
    expires_at = _utcnow() + expires_delta
    payload = {
        "aud": audience,
        "token_kind": token_kind,
        "exp": expires_at,
        **claims,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, expires_at


def create_portal_session_token(
    *,
    actor_type: str,
    actor_id: int,
    challenge_id: str,
    paciente_id: int | None = None,
    clinica_id: int | None = None,
    display_name: str | None = None,
    channel: str | None = None,
    scope: list[str] | tuple[str, ...] | None = None,
    account_id: int | None = None,
    session_id: int | None = None,
    auth_method: str | None = None,
) -> tuple[str, datetime]:
    claims = {
        "sub": f"portal-session:{actor_type}:{actor_id}",
        "portal_actor_type": actor_type,
        "portal_actor_id": int(actor_id),
        "portal_paciente_id": paciente_id,
        "portal_clinica_id": clinica_id,
        "portal_challenge_id": challenge_id,
        "portal_display_name": (display_name or "").strip() or None,
        "portal_channel": (channel or "").strip() or None,
        "portal_scope": list(scope or []),
        "portal_account_id": account_id,
        "portal_session_id": session_id,
        "portal_auth_method": (auth_method or "").strip() or None,
    }
    return _encode_portal_token(
        audience=PORTAL_SESSION_AUDIENCE,
        token_kind="portal_session",
        claims=claims,
        expires_delta=timedelta(minutes=settings.PORTAL_SESSION_TOKEN_EXPIRE_MINUTES),
    )


def create_portal_download_token(
    session: PortalSessionContext,
    *,
    exame_id: int,
    anexo_id: int,
) -> tuple[str, datetime]:
    claims = {
        "sub": f"portal-download:{anexo_id}",
        "portal_actor_type": session.actor_type,
        "portal_actor_id": int(session.actor_id),
        "portal_paciente_id": session.paciente_id,
        "portal_clinica_id": session.clinica_id,
        "portal_exame_id": int(exame_id),
        "portal_anexo_id": int(anexo_id),
    }
    return _encode_portal_token(
        audience=PORTAL_DOWNLOAD_AUDIENCE,
        token_kind="portal_download",
        claims=claims,
        expires_delta=timedelta(minutes=settings.PORTAL_DOWNLOAD_TOKEN_EXPIRE_MINUTES),
    )


def extract_portal_bearer_token(request: Request) -> str:
    return _extract_bearer_token(request.headers.get("Authorization")).strip()


def decode_portal_session_token(token: str) -> PortalSessionContext:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=PORTAL_SESSION_AUDIENCE,
        )
    except JWTError as exc:
        raise _portal_credentials_exception() from exc

    if payload.get("token_kind") != "portal_session":
        raise _portal_credentials_exception()

    actor_type = str(payload.get("portal_actor_type") or "").strip()
    actor_id = _coerce_optional_int(payload.get("portal_actor_id"))
    challenge_id = str(payload.get("portal_challenge_id") or "").strip()
    if not actor_type or actor_id is None or not challenge_id:
        raise _portal_credentials_exception()

    return PortalSessionContext(
        actor_type=actor_type,
        actor_id=actor_id,
        paciente_id=_coerce_optional_int(payload.get("portal_paciente_id")),
        clinica_id=_coerce_optional_int(payload.get("portal_clinica_id")),
        challenge_id=challenge_id,
        display_name=str(payload.get("portal_display_name") or "").strip() or None,
        channel=str(payload.get("portal_channel") or "").strip() or None,
        scope=_coerce_scope(payload.get("portal_scope")),
        expires_at=_coerce_expiration(payload.get("exp")),
        account_id=_coerce_optional_int(payload.get("portal_account_id")),
        session_id=_coerce_optional_int(payload.get("portal_session_id")),
        auth_method=str(payload.get("portal_auth_method") or "").strip() or None,
    )


def decode_portal_download_token(token: str) -> PortalDownloadContext:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=PORTAL_DOWNLOAD_AUDIENCE,
        )
    except JWTError as exc:
        raise _portal_credentials_exception("Token de download invalido") from exc

    if payload.get("token_kind") != "portal_download":
        raise _portal_credentials_exception("Token de download invalido")

    actor_type = str(payload.get("portal_actor_type") or "").strip()
    actor_id = _coerce_optional_int(payload.get("portal_actor_id"))
    exame_id = _coerce_optional_int(payload.get("portal_exame_id"))
    anexo_id = _coerce_optional_int(payload.get("portal_anexo_id"))
    if not actor_type or actor_id is None or exame_id is None or anexo_id is None:
        raise _portal_credentials_exception("Token de download invalido")

    return PortalDownloadContext(
        actor_type=actor_type,
        actor_id=actor_id,
        paciente_id=_coerce_optional_int(payload.get("portal_paciente_id")),
        clinica_id=_coerce_optional_int(payload.get("portal_clinica_id")),
        exame_id=exame_id,
        anexo_id=anexo_id,
        expires_at=_coerce_expiration(payload.get("exp")),
    )


def get_current_portal_session(request: Request) -> PortalSessionContext:
    _reject_query_tokens(request)
    token = extract_portal_bearer_token(request)
    if not token:
        raise _portal_credentials_exception()
    return decode_portal_session_token(token)


def get_current_portal_download_token(request: Request) -> PortalDownloadContext:
    _reject_query_tokens(request)
    token = (request.headers.get(PORTAL_DOWNLOAD_TOKEN_HEADER) or "").strip()
    if not token:
        raise _portal_credentials_exception("Token de download ausente")
    return decode_portal_download_token(token)
