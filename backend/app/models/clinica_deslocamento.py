from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.database import Base


class ClinicaDeslocamento(Base):
    __tablename__ = "clinica_deslocamentos"
    __table_args__ = (
        UniqueConstraint(
            "origem_clinica_id",
            "destino_clinica_id",
            "perfil",
            name="uq_clinica_deslocamentos_par",
        ),
        Index("ix_clinica_deslocamentos_origem", "origem_clinica_id"),
        Index("ix_clinica_deslocamentos_destino", "destino_clinica_id"),
        Index("ix_clinica_deslocamentos_perfil", "perfil"),
    )

    id = Column(Integer, primary_key=True, index=True)
    origem_clinica_id = Column(Integer, nullable=False)
    destino_clinica_id = Column(Integer, nullable=False)
    perfil = Column(String(20), nullable=False, default="comercial")
    distancia_km = Column(Numeric(10, 2), nullable=False, default=0)
    duracao_min = Column(Integer, nullable=False, default=0)
    fonte = Column(String(50), nullable=False, default="heuristica")
    manual_override = Column(Boolean, nullable=False, default=False)
    observacoes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
