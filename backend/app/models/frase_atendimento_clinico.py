from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class FraseAtendimentoClinico(Base):
    __tablename__ = "frases_atendimento_clinico"

    id = Column(Integer, primary_key=True, index=True)
    secao = Column(String, nullable=False, index=True)
    titulo = Column(String, nullable=False, index=True)
    texto = Column(Text, nullable=False)
    ordem = Column(Integer, nullable=False, default=0, index=True)
    ativo = Column(Integer, nullable=False, default=1, index=True)
    parametrizacao_origem = Column(String, nullable=False, default="seed")

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer)
