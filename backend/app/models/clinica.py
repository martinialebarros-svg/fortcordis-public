from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Numeric, Float, JSON
from sqlalchemy.sql import func
from app.db.database import Base


class Clinica(Base):
    __tablename__ = "clinicas"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    razao_social = Column(String)
    cnpj = Column(String)
    telefone = Column(String)
    whatsapps = Column(JSON, nullable=False, default=list)
    email = Column(String)
    atividade_cnae = Column(String)
    endereco = Column(String)
    numero = Column(String)
    complemento = Column(String)
    bairro = Column(String)
    cidade = Column(String)  # Para identificar a regiao
    estado = Column(String)
    cep = Column(String)
    # Exclusivo da contabilidade; nunca alimentar geocoding ou rotas com este campo.
    endereco_fiscal = Column(JSON, nullable=True)
    regiao_operacional = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    place_id = Column(String)
    endereco_normalizado = Column(String)
    geocode_at = Column(DateTime(timezone=True))
    observacoes = Column(Text)  # Observacoes gerais da clinica

    # Tabela de preco associada (1 = Fortaleza, 2 = Regiao Metropolitana, 3 = Domiciliar, 4 = Personalizado)
    tabela_preco_id = Column(Integer, default=1)

    # Preco personalizado para cidades distantes (ex: Aracati)
    # Usado quando tabela_preco_id = 4 (Personalizado)
    preco_personalizado_km = Column(Numeric(10, 2), default=0)  # Valor por km adicional
    preco_personalizado_base = Column(Numeric(10, 2), default=0)  # Valor base do atendimento

    # Observacoes sobre o preco negociado
    observacoes_preco = Column(Text)

    ativo = Column(Boolean, default=True)

    # Campos de auditoria
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
