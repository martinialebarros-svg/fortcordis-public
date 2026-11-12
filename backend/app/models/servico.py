from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean
from sqlalchemy.sql import func
from app.db.database import Base

class Servico(Base):
    __tablename__ = "servicos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    descricao = Column(String)
    duracao_minutos = Column(Integer)
    ativo = Column(Boolean, default=True)
    
    # Preços por região e tipo de horário
    # Fortaleza
    preco_fortaleza_comercial = Column(Numeric(10, 2), default=0)
    preco_fortaleza_plantao = Column(Numeric(10, 2), default=0)
    
    # Região Metropolitana
    preco_rm_comercial = Column(Numeric(10, 2), default=0)
    preco_rm_plantao = Column(Numeric(10, 2), default=0)
    
    # Atendimento Domiciliar
    preco_domiciliar_comercial = Column(Numeric(10, 2), default=0)
    preco_domiciliar_plantao = Column(Numeric(10, 2), default=0)
    
    # Preço legado (mantido para compatibilidade)
    preco = Column(Numeric(10, 2))
    
    # Campos de auditoria
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
