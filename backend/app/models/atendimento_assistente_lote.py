"""Private resumable AI workspaces, separate from clinical records."""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, Index

from app.db.database import Base


class AtendimentoAssistenteLote(Base):
    __tablename__ = "atendimento_assistente_lotes"
    __table_args__ = (
        UniqueConstraint("usuario_id", "request_id", name="uq_assistente_lote_request"),
        Index("ix_assistente_lote_owner", "usuario_id", "atendimento_id", "created_at"),
        Index("ix_assistente_lote_queue", "status", "lease_until"),
    )

    id = Column(String(36), primary_key=True)
    request_id = Column(String(36), nullable=False)
    usuario_id = Column(Integer, nullable=False)
    atendimento_id = Column(Integer, nullable=False)
    paciente_id = Column(Integer, nullable=False)
    manifest_hash = Column(String(64), nullable=False)
    context_json = Column(Text, nullable=False)
    transcricao = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="uploading")
    erro = Column(Text)
    resultado_json = Column(Text)
    # Veterinary decisions are independent of the immutable per-source readings.
    revisoes_identidade_json = Column(Text)
    lease_token = Column(String(36))
    lease_until = Column(DateTime)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)


class AtendimentoAssistenteLoteArquivo(Base):
    __tablename__ = "atendimento_assistente_lote_arquivos"
    __table_args__ = (Index("ix_assistente_lote_arquivo_job", "lote_id", "ordem"),)

    lote_id = Column(String(36), primary_key=True)
    id = Column(String(36), primary_key=True)
    ordem = Column(Integer, nullable=False)
    nome = Column(String(180), nullable=False)
    tipo = Column(String(10), nullable=False)
    tamanho = Column(Integer, nullable=False)
    mime = Column(String(150), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    sha256 = Column(String(64))
    caminho = Column(Text)
    erro = Column(Text)
    resultado_json = Column(Text)
