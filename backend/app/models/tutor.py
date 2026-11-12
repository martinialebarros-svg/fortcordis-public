from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Text
from sqlalchemy.sql import func
from app.db.database import Base


class Tutor(Base):
    __tablename__ = "tutores"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(Text)
    nome_key = Column(Text)
    # Nome e chave normalizada sao campos de busca, nunca identidade unica.
    identificacao_pendente = Column(Boolean, nullable=False, default=True, server_default="true")
    origem_cadastro = Column(Text)
    identificacao_observacoes = Column(Text)
    mesclado_em_id = Column(Integer, index=True)
    telefone = Column(Text)
    whatsapp = Column(Text)
    email = Column(Text)
    cpf = Column(Text)
    cep = Column(Text)
    endereco = Column(Text)
    numero = Column(Text)
    complemento = Column(Text)
    bairro = Column(Text)
    cidade = Column(Text)
    estado = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)
    place_id = Column(Text)
    endereco_normalizado = Column(Text)
    ativo = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
