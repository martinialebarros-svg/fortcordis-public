from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class AuditoriaEvento(Base):
    __tablename__ = "auditoria_eventos"

    id = Column(Integer, primary_key=True, index=True)

    usuario_id = Column(Integer, index=True, nullable=True)
    usuario_nome = Column(String(255), nullable=True)
    usuario_email = Column(String(255), nullable=True)

    modulo = Column(String(80), index=True, nullable=False)
    entidade = Column(String(80), index=True, nullable=False)
    entidade_id = Column(String(80), index=True, nullable=True)
    acao = Column(String(80), index=True, nullable=False)
    descricao = Column(Text, nullable=True)
    detalhes_json = Column(Text, nullable=True)

    ip_origem = Column(String(64), nullable=True)
    rota = Column(String(255), nullable=True)
    metodo = Column(String(10), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
