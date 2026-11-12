from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class PacienteMesclagem(Base):
    __tablename__ = "pacientes_mesclagens"
    __table_args__ = (
        CheckConstraint("principal_id <> secundario_id", name="ck_pacientes_mesclagens_par"),
        Index("ix_pacientes_mesclagens_estado_id", "estado", "id"),
    )

    id = Column(Integer, primary_key=True)
    par_chave = Column(String(48), nullable=False, unique=True)
    principal_id = Column(Integer, ForeignKey("pacientes.id", ondelete="RESTRICT"), nullable=False, index=True)
    secundario_id = Column(Integer, ForeignKey("pacientes.id", ondelete="RESTRICT"), nullable=False, index=True)
    estado = Column(String(16), nullable=False)
    criado_por_id = Column(Integer, nullable=False)
    criado_por_nome = Column(String(255), nullable=False)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    confirmado_por_id = Column(Integer)
    confirmado_por_nome = Column(String(255))
    confirmado_em = Column(DateTime(timezone=True))
    motivo = Column(Text)
    # Preserve a descrição dos dois cadastros e os IDs movidos, sem duplicar documentos.
    evidencia = Column(JSON)
