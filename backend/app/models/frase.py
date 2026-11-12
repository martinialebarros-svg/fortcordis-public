"""Modelo para frases qualitativas de laudos"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.db.database import Base


class FraseQualitativa(Base):
    """Modelo para frases qualitativas de laudos ecocardiográficos"""
    __tablename__ = "frases_qualitativas"

    id = Column(Integer, primary_key=True, index=True)
    chave = Column(String(255), unique=True, index=True, nullable=False)
    patologia = Column(String(255), nullable=False)
    grau = Column(String(100), nullable=False, default="Normal")
    
    # Campos da qualitativa detalhada (estrutura similar ao sistema antigo)
    valvas = Column(Text, default="")
    camaras = Column(Text, default="")
    funcao = Column(Text, default="")
    pericardio = Column(Text, default="")
    vasos = Column(Text, default="")
    ad_vd = Column(Text, default="")  # Átrio direito / VD
    conclusao = Column(Text, default="")
    
    # Campos em formato JSON para mais flexibilidade
    detalhado = Column(JSON, default=dict)  # {valvas: {...}, camaras: {...}, ...}
    
    # Metadados
    layout = Column(String(50), default="detalhado")  # "detalhado" ou "enxuto"
    ativo = Column(Integer, default=1)
    
    # Auditoria
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True)


class FraseQualitativaHistorico(Base):
    """Histórico de alterações nas frases"""
    __tablename__ = "frases_qualitativas_historico"

    id = Column(Integer, primary_key=True, index=True)
    frase_id = Column(Integer, ForeignKey("frases_qualitativas.id"))
    chave = Column(String(255))
    patologia = Column(String(255))
    grau = Column(String(100))
    conteudo = Column(JSON)  # Snapshot completo da frase
    acao = Column(String(50))  # CREATE, UPDATE, DELETE
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
