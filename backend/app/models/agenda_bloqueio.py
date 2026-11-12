from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class AgendaBloqueio(Base):
    __tablename__ = "agenda_bloqueios"
    __table_args__ = (
        Index("ix_agenda_bloqueios_ativo_inicio_fim", "ativo", "inicio", "fim"),
    )

    id = Column(String(36), primary_key=True)
    inicio = Column(DateTime(timezone=True), nullable=False)
    fim = Column(DateTime(timezone=True), nullable=False)
    motivo = Column(Text, nullable=False)
    ativo = Column(Boolean, nullable=False, default=True, index=True)
    criado_por_id = Column(Integer, nullable=False, index=True)
    criado_por_nome = Column(String(180), nullable=True)
    liberado_por_id = Column(Integer, nullable=True)
    liberado_em = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
