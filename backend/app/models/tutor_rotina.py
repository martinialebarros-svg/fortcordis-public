"""Historicos imutaveis e complementos opcionais do cadastro de tutores."""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db.database import Base


class TutorIdentificacaoEvento(Base):
    __tablename__ = "tutores_identificacao_eventos"

    id = Column(Integer, primary_key=True)
    # Nao usar tutor_id: a mesclagem nao deve reescrever autoria/proveniencia.
    cadastro_id = Column(Integer, nullable=False, index=True)
    acao = Column(String(32), nullable=False)
    usuario_id = Column(Integer)
    usuario_nome = Column(Text)
    metodo = Column(Text)
    evidencia = Column(Text)
    motivo = Column(Text)
    detalhes_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TutorContato(Base):
    __tablename__ = "tutores_contatos"

    id = Column(Integer, primary_key=True)
    tutor_id = Column(Integer, nullable=False, index=True)
    tipo = Column(String(16), nullable=False)
    valor = Column(Text, nullable=False)
    valor_normalizado = Column(Text, nullable=False, index=True)
    rotulo = Column(Text)
    usuario_id = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TutorOrigem(Base):
    __tablename__ = "tutores_origens"

    id = Column(Integer, primary_key=True)
    tutor_id = Column(Integer, nullable=False, index=True)
    descricao = Column(Text, nullable=False)
    clinica_id = Column(Integer)
    usuario_id = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TutorDuplicidadeDescarte(Base):
    __tablename__ = "tutores_duplicidades_descartes"

    id = Column(Integer, primary_key=True)
    cadastro_id = Column(Integer, nullable=False, index=True)
    outro_cadastro_id = Column(Integer, nullable=False, index=True)
    assinatura_par = Column(String(64), nullable=False)
    motivo = Column(Text, nullable=False)
    usuario_id = Column(Integer, nullable=False)
    usuario_nome = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TutorOperacao(Base):
    __tablename__ = "tutores_operacoes"
    __table_args__ = (UniqueConstraint("usuario_id", "tipo", "chave", name="uq_tutores_operacao_usuario_tipo_chave"),)

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, nullable=False)
    tipo = Column(String(48), nullable=False)
    chave = Column(String(128), nullable=False)
    hash_payload = Column(String(64), nullable=False)
    resposta_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
