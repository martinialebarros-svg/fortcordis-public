from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from app.db.database import Base


class TutorMesclagem(Base):
    __tablename__ = "tutores_mesclagens"

    id = Column(Integer, primary_key=True)
    principal_id = Column(Integer, nullable=False, index=True)
    secundario_id = Column(Integer, nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False)
    usuario_nome = Column(Text)
    motivo = Column(Text, nullable=False)
    detalhes_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
