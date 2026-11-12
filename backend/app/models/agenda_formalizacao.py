from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.db.database import Base


class AgendaFormalizacaoInvite(Base):
    """Convite de link unico para a clinica preencher paciente/tutor de uma

    reserva pendente (via Portal), sem precisar de conta/login - mesmo
    padrao de token opaco + hash usado em `PortalClinicInvite`, mas
    vinculado a um agendamento especifico em vez de uma clinica.
    """

    __tablename__ = "agenda_formalizacao_invites"

    id = Column(Integer, primary_key=True, index=True)
    agendamento_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
