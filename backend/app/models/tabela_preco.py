"""Modelo para tabelas de preço por região"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric
from sqlalchemy.sql import func
from app.db.database import Base


class TabelaPreco(Base):
    """Tabela de preço para uma região específica"""
    __tablename__ = "tabelas_preco"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)  # Ex: "Fortaleza", "Região Metropolitana", "Domiciliar"
    descricao = Column(Text)
    
    # Campos de auditoria
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    ativo = Column(Integer, default=1)


class PrecoServico(Base):
    """Preço de um serviço em uma tabela específica"""
    __tablename__ = "precos_servicos"

    id = Column(Integer, primary_key=True, index=True)
    tabela_preco_id = Column(Integer, nullable=False)
    servico_id = Column(Integer, nullable=False)
    
    # Preços por tipo de horário
    preco_comercial = Column(Numeric(10, 2), default=0)  # Horário comercial
    preco_plantao = Column(Numeric(10, 2), default=0)    # Horário de plantão
    
    # Observações específicas
    observacoes = Column(Text)
    
    # Auditoria
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PrecoServicoClinica(Base):
    """Preco negociado de um servico para uma clinica especifica."""
    __tablename__ = "precos_servicos_clinica"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, nullable=False, index=True)
    servico_id = Column(Integer, nullable=False, index=True)

    # Precos customizados por horario; quando nulo usa preco da tabela padrao.
    preco_comercial = Column(Numeric(10, 2), nullable=True)
    preco_plantao = Column(Numeric(10, 2), nullable=True)

    ativo = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
