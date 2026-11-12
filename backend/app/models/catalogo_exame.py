from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class CatalogoExame(Base):
    __tablename__ = "catalogo_exames"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, nullable=False, unique=True, index=True)
    nome = Column(String, nullable=False, index=True)
    categoria = Column(String, nullable=False, index=True)
    subcategoria = Column(String)
    especie_alvo = Column(String)
    prioridade_padrao = Column(String, default="Rotina")
    valor_padrao = Column(Float, default=0)
    preparo = Column(Text)
    observacoes_padrao = Column(Text)
    sinonimos_json = Column(Text)
    clinic_id = Column(Integer, nullable=True, index=True)
    ativo = Column(Integer, nullable=False, default=1, index=True)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PainelExame(Base):
    __tablename__ = "painel_exames"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, nullable=False, unique=True, index=True)
    nome = Column(String, nullable=False, index=True)
    categoria = Column(String, index=True)
    especie_alvo = Column(String)
    observacoes = Column(Text)
    clinic_id = Column(Integer, nullable=True, index=True)
    ativo = Column(Integer, nullable=False, default=1, index=True)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PainelExameItem(Base):
    __tablename__ = "painel_exames_itens"

    id = Column(Integer, primary_key=True, index=True)
    painel_id = Column(Integer, nullable=False, index=True)
    catalogo_exame_id = Column(Integer, nullable=False, index=True)
    ordem = Column(Integer, nullable=False, default=0)
    observacoes = Column(Text)

    created_at = Column(DateTime(timezone=True), default=func.now())
