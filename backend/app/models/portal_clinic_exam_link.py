from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.db.database import Base


class PortalClinicExamLink(Base):
    """Link direto para UM laudo liberado, entregue no WhatsApp da clinica.

    Existe porque quem cria a senha do portal e o gerente, mas quem precisa do
    laudo e a secretaria - que nao sabe a senha e nao abre o e-mail do cadastro
    (ver docs/specs/portal-clinica-link-laudo-whatsapp/intent.md).

    O token bruto e devolvido uma unica vez, no momento da emissao, e so o hash
    fica no banco - mesmo padrao dos convites e do reset de senha. O link nao
    expira por tempo (decisao de 2026-09-18: a secretaria precisa reabrir a
    mensagem antiga quando o cliente perde o PDF), mas morre por revogacao
    explicita ou quando o exame deixa de estar liberado no portal.
    """

    __tablename__ = "portal_clinic_exam_links"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    # Nonce publico por linha. O token e HMAC(SECRET_KEY, exame + nonce): o nonce
    # deixa o token reconstruivel num reenvio (mesma URL) e, por ser sorteado a
    # cada emissao, garante que reemitir depois de revogar produz link novo - um
    # link revogado nunca volta a valer.
    token_nonce = Column(String(32), nullable=False)
    exame_id = Column(Integer, nullable=False, index=True)
    laudo_id = Column(Integer, nullable=True, index=True)
    clinica_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    created_by_user_id = Column(Integer, nullable=True, index=True)
    delivery_channel = Column(String(20), nullable=False, default="whatsapp")
    delivery_target_masked = Column(String(255), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    first_opened_at = Column(DateTime(timezone=True), nullable=True)
    last_opened_at = Column(DateTime(timezone=True), nullable=True)
    open_count = Column(Integer, nullable=False, default=0)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
