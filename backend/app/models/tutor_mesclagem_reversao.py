from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from app.db.database import Base


class TutorMesclagemReversao(Base):
    __tablename__ = "tutores_mesclagens_reversoes"

    id = Column(Integer, primary_key=True)
    mesclagem_id = Column(Integer, nullable=False, unique=True)
    usuario_id = Column(Integer, nullable=False)
    usuario_nome = Column(Text)
    motivo = Column(Text, nullable=False)
    detalhes_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
