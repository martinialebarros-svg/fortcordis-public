from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class PortalAccessChallenge(Base):
    __tablename__ = "portal_access_challenges"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(String(64), nullable=False, unique=True, index=True)
    actor_type = Column(String(20), nullable=False, index=True)
    actor_id = Column(Integer, nullable=False, index=True)
    paciente_id = Column(Integer, nullable=True, index=True)
    clinica_id = Column(Integer, nullable=True, index=True)
    responsavel_nome = Column(String(255))
    canal = Column(String(20), nullable=False)
    contato_mascarado = Column(String(255), nullable=False)
    scope_json = Column(Text, nullable=False, default="[]")
    contexto_json = Column(Text, nullable=False, default="{}")
    code_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    failed_attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
