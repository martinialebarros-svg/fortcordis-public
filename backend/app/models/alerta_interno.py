from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func
from app.db.database import Base


class AlertaInterno(Base):
    """Aviso explicito e persistente para a equipe interna (nao depende de push)."""

    __tablename__ = "alertas_internos"
    __table_args__ = (
        Index("ix_alertas_internos_lido_criado_id", "lido", "criado_em", "id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String(80), nullable=False)
    nivel = Column(String(20), nullable=False, default="aviso")  # info, aviso, critico
    titulo = Column(String(200), nullable=False)
    mensagem = Column(Text, nullable=False)

    entidade_tipo = Column(String(80), nullable=True)
    entidade_id = Column(Integer, nullable=True)
    clinica_id = Column(Integer, nullable=True)

    lido = Column(Boolean, nullable=False, default=False)
    lido_por_id = Column(Integer, nullable=True)
    lido_por_nome = Column(String(120), nullable=True)
    lido_em = Column(DateTime(timezone=True), nullable=True)

    criado_em = Column(DateTime(timezone=True), server_default=func.now())
