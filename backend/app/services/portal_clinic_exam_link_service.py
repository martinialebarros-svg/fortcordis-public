"""Emissao e resolucao do link direto de laudo entregue no WhatsApp da clinica.

A regra de negocio vive aqui, e nao nos endpoints, porque dois caminhos diferentes
a usam: o aviso de laudo (`laudos.py`) emite, e a pagina publica (`portal.py`)
resolve. Ver docs/specs/portal-clinica-link-laudo-whatsapp/.

Decisao de seguranca central: resolver um link NAO emite sessao de portal. Uma
sessao de clinica daria acesso a todos os exames da unidade; o link vale por um
exame so. Quem mexer neste modulo precisa manter essa separacao.

Sobre a derivacao do token: o banco guarda so o SHA-256, como nos convites e no
reset de senha. Mas o aviso pode ser reenviado, e um reenvio precisa repetir a
MESMA URL - senao o link da mensagem anterior morreria, contrariando a decisao de
2026-09-18 de que a secretaria consegue reabrir a mensagem antiga quando o cliente
perde o PDF. Por isso o token e derivado por HMAC(SECRET_KEY, exame + nonce da
linha) em vez de sorteado: e reconstruivel a partir da linha, continua imprevisivel
para quem nao tem a SECRET_KEY, e um dump de banco sozinho nao entrega link
utilizavel. O nonce e sorteado a cada emissao, entao reemitir depois de revogar da
um link diferente - revogacao nao volta atras.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.portal_clinic_exam_link import PortalClinicExamLink

LINK_STATUS_ACTIVE = "active"
LINK_STATUS_REVOKED = "revoked"

_TOKEN_DERIVATION_PREFIX = "portal-exam-link:v1:"
# HMAC-SHA256 em base64url sem padding -> 43 caracteres.
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def utcnow() -> datetime:
    return datetime.utcnow()


def generate_token_nonce() -> str:
    return secrets.token_hex(16)


def derive_link_token(exame_id: int, token_nonce: str) -> str:
    """Token estavel e imprevisivel para aquele exame + nonce.

    Estavel porque o reenvio precisa repetir a mesma URL; imprevisivel porque
    depende da SECRET_KEY, que nao esta no banco.
    """
    digest = hmac.new(
        str(settings.SECRET_KEY or "").encode("utf-8"),
        f"{_TOKEN_DERIVATION_PREFIX}{int(exame_id)}:{str(token_nonce or '')}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def hash_link_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def is_plausible_link_token(raw_token: str | None) -> bool:
    """Descarta lixo obvio antes de encostar no banco (CB-005)."""
    return bool(_TOKEN_PATTERN.match(str(raw_token or "").strip()))


def get_active_link_for_exam(db: Session, exame_id: int) -> PortalClinicExamLink | None:
    return (
        db.query(PortalClinicExamLink)
        .filter(
            PortalClinicExamLink.exame_id == exame_id,
            PortalClinicExamLink.status == LINK_STATUS_ACTIVE,
        )
        .order_by(PortalClinicExamLink.id.desc())
        .first()
    )


def issue_exam_link(
    db: Session,
    *,
    exame_id: int,
    clinica_id: int,
    laudo_id: int | None = None,
    created_by_user_id: int | None = None,
    delivery_target_masked: str | None = None,
) -> tuple[PortalClinicExamLink, str]:
    """Emite o link daquele exame, ou reaproveita o ativo que ja existe (RF-012).

    Devolve `(link, raw_token)`. Reenviar o aviso do mesmo exame nao cria linha
    nova nem credencial nova: devolve o mesmo token do link ativo.
    """
    existing = get_active_link_for_exam(db, exame_id)
    if existing is not None:
        raw_token = derive_link_token(existing.exame_id, existing.token_nonce)
        if hash_link_token(raw_token) == existing.token_hash:
            if delivery_target_masked:
                existing.delivery_target_masked = delivery_target_masked
            existing.delivered_at = utcnow()
            db.commit()
            db.refresh(existing)
            return existing, raw_token
        # SECRET_KEY rotacionada depois da emissao: o token derivado nao bate mais
        # com o hash guardado. O link antigo e irrecuperavel, entao encerra e emite
        # outro em vez de devolver URL que nao resolve.
        revoke_links_for_exam(db, exame_id, motivo="secret_key_rotacionada")

    token_nonce = generate_token_nonce()
    raw_token = derive_link_token(exame_id, token_nonce)
    link = PortalClinicExamLink(
        token_hash=hash_link_token(raw_token),
        token_nonce=token_nonce,
        exame_id=exame_id,
        laudo_id=laudo_id,
        clinica_id=clinica_id,
        status=LINK_STATUS_ACTIVE,
        created_by_user_id=created_by_user_id,
        delivery_channel="whatsapp",
        delivery_target_masked=delivery_target_masked,
        delivered_at=utcnow(),
        open_count=0,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link, raw_token


def resolve_active_link(db: Session, raw_token: str | None) -> PortalClinicExamLink | None:
    if not is_plausible_link_token(raw_token):
        return None
    token_hash = hash_link_token(str(raw_token).strip())
    return (
        db.query(PortalClinicExamLink)
        .filter(
            PortalClinicExamLink.token_hash == token_hash,
            PortalClinicExamLink.status == LINK_STATUS_ACTIVE,
        )
        .first()
    )


def register_link_open(db: Session, link: PortalClinicExamLink) -> None:
    now = utcnow()
    if link.first_opened_at is None:
        link.first_opened_at = now
    link.last_opened_at = now
    link.open_count = int(link.open_count or 0) + 1
    db.commit()


def revoke_links_for_exam(db: Session, exame_id: int, motivo: str | None = None) -> int:
    links = (
        db.query(PortalClinicExamLink)
        .filter(
            PortalClinicExamLink.exame_id == exame_id,
            PortalClinicExamLink.status == LINK_STATUS_ACTIVE,
        )
        .all()
    )
    if not links:
        return 0
    now = utcnow()
    reason = str(motivo or "").strip()[:255] or None
    for link in links:
        link.status = LINK_STATUS_REVOKED
        link.revoked_at = now
        link.revoked_reason = reason
    db.commit()
    return len(links)


def build_exam_link_url(request: Request | None, raw_token: str) -> str:
    configured = str(settings.PORTAL_CLINIC_EXAM_LINK_BASE_URL or "").strip().rstrip("/")
    if configured:
        base = configured
    elif request is not None:
        base = str(request.base_url).rstrip("/")
    else:
        base = ""
    return f"{base}/laudo/{raw_token}"
