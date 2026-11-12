from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
import secrets

from app.db.database import get_db
from app.models.user import User
from app.schemas.user import Token, UserResponse
from app.core.config import settings
from app.core.security import get_current_user, get_request_token
from app.services import supabase_auth

def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(dependencies=[Depends(_no_store)])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$", "$2$")


def _request_uses_https(request: Request | None = None) -> bool:
    if request is None:
        return False

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").strip().lower()
    if forwarded_proto:
        first_value = forwarded_proto.split(",")[0].strip()
        if first_value == "https":
            return True

    return (request.url.scheme or "").strip().lower() == "https"


def _is_cookie_secure(request: Request | None = None) -> bool:
    if settings.AUTH_COOKIE_SECURE:
        return True
    if settings.APP_ENV.lower() in {"production", "staging", "stage"}:
        return True
    return _request_uses_https(request)


def _session_cookie_max_age() -> int:
    if settings.AUTH_PROVIDER == "supabase":
        return settings.SUPABASE_REFRESH_COOKIE_MAX_AGE
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def _set_auth_cookie(response: Response, token: str, request: Request | None = None) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_is_cookie_secure(request),
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=_session_cookie_max_age(),
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )


def _set_csrf_cookie(response: Response, csrf_token: str, request: Request | None = None) -> None:
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=_is_cookie_secure(request),
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=_session_cookie_max_age(),
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )


def _clear_auth_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=_is_cookie_secure(request),
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


def _clear_csrf_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(
        key=settings.CSRF_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=_is_cookie_secure(request),
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica senha apenas com hash bcrypt (sem fallback legado em texto plano)."""
    if not hashed_password or not hashed_password.startswith(_BCRYPT_PREFIXES):
        return False

    # bcrypt nao aceita senha > 72 bytes; trunca para evitar ValueError.
    pwd_bytes = plain_password.encode("utf-8")[:72]
    plain_truncated = pwd_bytes.decode("utf-8", errors="ignore")
    return pwd_context.verify(plain_truncated, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def _credentials_error() -> HTTPException:
    return HTTPException(401, "Email ou senha incorretos", headers={"WWW-Authenticate": "Bearer"})


def _token_response(user: User, token: str, *, expires_at: int | None = None) -> dict:
    return {
        "access_token": token, "token_type": "bearer", "user_id": user.id,
        "nome": user.nome, "email": user.email, "papeis": [p.nome for p in user.papeis],
        "provider": settings.AUTH_PROVIDER, "expires_at": expires_at,
    }


def _accept_supabase_session(db: Session, session: dict, response: Response, request: Request) -> dict:
    try:
        token = session["access_token"]
        refresh_token = session["refresh_token"]
        if not isinstance(token, str) or not token or not isinstance(refresh_token, str) or not refresh_token:
            raise ValueError()
        # Validate the actual token with Auth before setting any cookies.
        user = supabase_auth.get_user(db, token)
        expires_at = int(jwt.get_unverified_claims(token)["exp"])
    except (KeyError, TypeError, ValueError, JWTError):
        raise _credentials_error() from None
    user.ultimo_acesso = datetime.now()
    db.commit()
    _set_auth_cookie(response, token, request)
    _set_csrf_cookie(response, secrets.token_urlsafe(32), request)
    response.set_cookie(
        key=settings.SUPABASE_REFRESH_COOKIE_NAME, value=refresh_token,
        httponly=True, secure=_is_cookie_secure(request),
        samesite=settings.AUTH_COOKIE_SAMESITE, max_age=_session_cookie_max_age(),
        path=settings.AUTH_COOKIE_PATH, domain=settings.AUTH_COOKIE_DOMAIN,
    )
    return _token_response(user, token, expires_at=expires_at)

@router.post("/login", response_model=Token)
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    if settings.AUTH_PROVIDER == "supabase":
        try:
            session = supabase_auth.password_session(form_data.username.strip().lower(), form_data.password)
        except JWTError:
            raise _credentials_error() from None
        return _accept_supabase_session(db, session, response, request)

    user = db.query(User).filter(User.email == form_data.username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if user.ativo != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo"
        )
    
    if not verify_password(form_data.password, user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Pega os nomes dos papéis
    papeis_nomes = [p.nome for p in user.papeis]
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "user_id": user.id, "nome": user.nome, "papeis": papeis_nomes}, 
        expires_delta=access_token_expires
    )
    
    user.ultimo_acesso = datetime.now()
    db.commit()

    _set_auth_cookie(response, access_token, request)
    _set_csrf_cookie(response, secrets.token_urlsafe(32), request)
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "nome": user.nome,
        "email": user.email,
        "papeis": papeis_nomes
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    if settings.AUTH_PROVIDER == "supabase":
        token = get_request_token(request)
        refresh_token = request.cookies.get(settings.SUPABASE_REFRESH_COOKIE_NAME)
        needs_refresh = not token
        if token:
            try:
                supabase_auth.sign_out(token)
            except JWTError:
                needs_refresh = True
        if needs_refresh and refresh_token:
            # Expired/missing access tokens cannot revoke the refresh session.
            try:
                session = supabase_auth.refresh_session(refresh_token)
                supabase_auth.sign_out(session["access_token"])
            except JWTError:
                pass  # Already revoked; local cleanup is still safe.
    _clear_auth_cookie(response, request)
    _clear_csrf_cookie(response, request)
    response.delete_cookie(
        key=settings.SUPABASE_REFRESH_COOKIE_NAME, path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN, secure=_is_cookie_secure(request),
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return {"success": True}


@router.post("/refresh", response_model=Token)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    if settings.AUTH_PROVIDER != "supabase":
        raise HTTPException(401, "Sessao expirada. Entre novamente.")
    refresh_token = request.cookies.get(settings.SUPABASE_REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise _credentials_error()
    try:
        session = supabase_auth.refresh_session(refresh_token)
    except JWTError:
        raise _credentials_error() from None
    return _accept_supabase_session(db, session, response, request)


@router.get("/session")
def read_session(request: Request, current_user: User = Depends(get_current_user)):
    token = get_request_token(request)
    # Expiration is only a scheduling hint; get_current_user already validated
    # authentication, activity, identity binding and session revocation.
    expires_at = jwt.get_unverified_claims(token).get("exp")
    return {"id": current_user.id, **_token_response(current_user, token, expires_at=expires_at)}

@router.get("/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
