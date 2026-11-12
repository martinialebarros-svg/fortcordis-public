"""Confianca de dispositivo da recepcao - portal em modo laudos, sem senha.

Ver docs/specs/portal-clinica-dispositivo-confiavel/.

Duas decisoes que dao o tom do modulo:

- **Escopo travado em laudos.** A confianca nasce de um link entregue no WhatsApp
  da clinica, que e canal compartilhado; ela nunca pode alcancar financeiro,
  agenda ou recibo. O escopo e gravado na linha e reemitido a cada sessao, e a
  conferencia de verdade acontece nos endpoints (`portal-escopo-sessao-clinica`).
- **Token sorteado, nao derivado.** Diferente do link de laudo - que deriva o
  token por HMAC para que um reenvio repita a mesma URL - aqui o segredo vive num
  cookie e e rotacionado a cada uso. Nao ha nada a reconstruir, entao sorteio puro
  e o mais simples e o mais seguro.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.services.portal_clinic_auth_service import (
    generate_opaque_token,
    hash_secret,
    is_portal_refresh_cookie_secure,
    request_user_agent_hash,
)

TRUST_STATUS_ACTIVE = "active"
TRUST_STATUS_REVOKED = "revoked"
TRUST_STATUS_EXPIRED = "expired"

TRUST_ORIGIN_EXAM_LINK = "exam_link"

_TOKEN_KIND = "portal_clinic_device_trust"

# Escopo do modo laudos: leitura e download de exame liberado, nada de gestao da
# unidade. Espelha PORTAL_SCOPE_CLINICA sem `clinic:read`.
DEVICE_TRUST_SCOPE: tuple[str, ...] = ("exam:read", "exam:download")


def utcnow() -> datetime:
    return datetime.utcnow()


def hash_trust_token(raw_token: str) -> str:
    return hash_secret(_TOKEN_KIND, str(raw_token or ""))


def _inactivity_delta() -> timedelta:
    dias = max(1, int(settings.PORTAL_CLINIC_DEVICE_TRUST_INACTIVITY_DAYS or 30))
    return timedelta(days=dias)


def _next_expiration() -> datetime:
    return utcnow() + _inactivity_delta()


def create_trust(
    db: Session,
    *,
    clinica_id: int,
    request: Request | None,
    origin_exam_link_id: int | None = None,
    device_label: str | None = None,
) -> tuple[PortalClinicTrustedDevice, str]:
    raw_token = generate_opaque_token()
    trust = PortalClinicTrustedDevice(
        clinica_id=clinica_id,
        refresh_token_hash=hash_trust_token(raw_token),
        device_label=(str(device_label or "").strip() or "computador-da-recepcao")[:120],
        user_agent_hash=request_user_agent_hash(request),
        origin=TRUST_ORIGIN_EXAM_LINK,
        origin_exam_link_id=origin_exam_link_id,
        scope_json=json.dumps(list(DEVICE_TRUST_SCOPE)),
        status=TRUST_STATUS_ACTIVE,
        expires_at=_next_expiration(),
        last_seen_at=utcnow(),
    )
    db.add(trust)
    db.commit()
    db.refresh(trust)
    return trust, raw_token


def expire_trust_if_needed(db: Session, trust: PortalClinicTrustedDevice) -> bool:
    if trust.expires_at and trust.expires_at <= utcnow():
        if trust.status == TRUST_STATUS_ACTIVE:
            trust.status = TRUST_STATUS_EXPIRED
            db.commit()
        return True
    return False


def resolve_active_trust(db: Session, raw_token: str | None) -> PortalClinicTrustedDevice | None:
    token = str(raw_token or "").strip()
    if not token:
        return None
    trust = (
        db.query(PortalClinicTrustedDevice)
        .filter(PortalClinicTrustedDevice.refresh_token_hash == hash_trust_token(token))
        .first()
    )
    if trust is None:
        return None
    if expire_trust_if_needed(db, trust):
        return None
    if trust.status != TRUST_STATUS_ACTIVE:
        return None
    return trust


def rotate_and_renew(
    db: Session,
    trust: PortalClinicTrustedDevice,
    *,
    request: Request | None,
) -> str:
    """Troca o segredo do cookie e empurra o prazo de inatividade.

    A rotacao a cada uso limita a janela de um cookie copiado: o proximo acesso
    legitimo invalida a copia.
    """
    raw_token = generate_opaque_token()
    trust.refresh_token_hash = hash_trust_token(raw_token)
    trust.last_seen_at = utcnow()
    trust.expires_at = _next_expiration()
    if trust.user_agent_hash is None:
        trust.user_agent_hash = request_user_agent_hash(request)
    db.commit()
    return raw_token


def user_agent_matches(trust: PortalClinicTrustedDevice, request: Request | None) -> bool:
    """Mesmo criterio de `refresh_login_clinica`: so compara quando ha os dois lados."""
    atual = request_user_agent_hash(request)
    if not trust.user_agent_hash or not atual:
        return True
    return trust.user_agent_hash == atual


def revoke_trust(db: Session, trust: PortalClinicTrustedDevice, *, motivo: str) -> None:
    trust.status = TRUST_STATUS_REVOKED
    trust.revoked_at = utcnow()
    trust.revoked_reason = (str(motivo or "").strip() or None) and str(motivo).strip()[:255]
    db.commit()


def _revoke_query(db: Session, query, motivo: str) -> int:
    trusts = query.filter(PortalClinicTrustedDevice.status == TRUST_STATUS_ACTIVE).all()
    if not trusts:
        return 0
    agora = utcnow()
    razao = str(motivo or "").strip()[:255] or None
    for trust in trusts:
        trust.status = TRUST_STATUS_REVOKED
        trust.revoked_at = agora
        trust.revoked_reason = razao
    db.commit()
    return len(trusts)


def revoke_trusts_for_clinica(db: Session, clinica_id: int, *, motivo: str) -> int:
    return _revoke_query(
        db,
        db.query(PortalClinicTrustedDevice).filter(
            PortalClinicTrustedDevice.clinica_id == clinica_id
        ),
        motivo,
    )


def revoke_trusts_for_exam(db: Session, exame_id: int, *, motivo: str) -> int:
    """Revoga confiancas nascidas de qualquer link daquele exame.

    Chamado ao lado de `revoke_links_for_exam`, e nao de dentro dele, para que os
    dois servicos nao dependam um do outro.
    """
    link_ids = [
        row[0]
        for row in db.query(PortalClinicExamLink.id)
        .filter(PortalClinicExamLink.exame_id == exame_id)
        .all()
    ]
    if not link_ids:
        return 0
    return _revoke_query(
        db,
        db.query(PortalClinicTrustedDevice).filter(
            PortalClinicTrustedDevice.origin_exam_link_id.in_(link_ids)
        ),
        motivo,
    )


# --------------------------------------------------------------------------
# Cookie
# --------------------------------------------------------------------------


def set_device_cookie(
    response: Response,
    raw_token: str,
    *,
    expires_at: datetime,
    request: Request | None = None,
) -> None:
    max_age = max(60, int((expires_at - utcnow()).total_seconds()))
    response.set_cookie(
        key=settings.PORTAL_CLINIC_DEVICE_TRUST_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=is_portal_refresh_cookie_secure(request),
        samesite=settings.PORTAL_CLINIC_REFRESH_COOKIE_SAMESITE,
        max_age=max_age,
        path=settings.PORTAL_CLINIC_REFRESH_COOKIE_PATH,
        domain=settings.PORTAL_CLINIC_REFRESH_COOKIE_DOMAIN,
    )


def clear_device_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(
        key=settings.PORTAL_CLINIC_DEVICE_TRUST_COOKIE_NAME,
        path=settings.PORTAL_CLINIC_REFRESH_COOKIE_PATH,
        domain=settings.PORTAL_CLINIC_REFRESH_COOKIE_DOMAIN,
        secure=is_portal_refresh_cookie_secure(request),
        samesite=settings.PORTAL_CLINIC_REFRESH_COOKIE_SAMESITE,
    )


def get_device_cookie(request: Request) -> str:
    return (request.cookies.get(settings.PORTAL_CLINIC_DEVICE_TRUST_COOKIE_NAME) or "").strip()
