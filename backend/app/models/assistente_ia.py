from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class AssistenteIAConversa(Base):
    __tablename__ = "assistente_ia_conversas"
    __table_args__ = (
        Index(
            "ix_assistente_ia_conversas_usuario_updated",
            "usuario_id",
            "updated_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    titulo = Column(String(160), nullable=False, default="Nova conversa")
    previous_response_id = Column(String(255), nullable=True)
    ativa = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AssistenteIAMensagem(Base):
    __tablename__ = "assistente_ia_mensagens"
    __table_args__ = (
        Index(
            "ix_assistente_ia_mensagens_conversa_created",
            "conversa_id",
            "created_at",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    conversa_id = Column(String(36), nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    papel = Column(String(20), nullable=False)
    conteudo = Column(Text, nullable=False)
    ferramentas_json = Column(Text, nullable=True)
    acao_pendente_id = Column(String(36), nullable=True, index=True)
    provider_response_id = Column(String(255), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    provider_status = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssistenteIAAcaoPendente(Base):
    __tablename__ = "assistente_ia_acoes_pendentes"
    __table_args__ = (
        Index(
            "ix_assistente_ia_acoes_usuario_status",
            "usuario_id",
            "status",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    conversa_id = Column(String(36), nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    tipo_acao = Column(String(80), nullable=False)
    argumentos_json = Column(Text, nullable=False)
    alvo_snapshot_json = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="pending", index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    resultado_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssistenteIAMemoria(Base):
    __tablename__ = "assistente_ia_memorias"
    __table_args__ = (
        Index("ix_assistente_ia_memorias_status_categoria", "status", "categoria", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    titulo = Column(String(180), nullable=False)
    conteudo = Column(Text, nullable=False)
    categoria = Column(String(60), nullable=False, default="operacao")
    origem = Column(String(40), nullable=False, default="admin")
    status = Column(String(24), nullable=False, default="pending", index=True)
    versao_atual = Column(Integer, nullable=False, default=1)
    criado_por_id = Column(Integer, nullable=False, index=True)
    aprovado_por_id = Column(Integer, nullable=True)
    aprovado_em = Column(DateTime(timezone=True), nullable=True)
    rejeitado_em = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AssistenteIAAprendizado(Base):
    __tablename__ = "assistente_ia_aprendizados"
    __table_args__ = (
        Index(
            "ix_assistente_ia_aprendizados_usuario_status_created",
            "usuario_id",
            "status",
            "created_at",
        ),
        Index("ix_assistente_ia_aprendizados_feedback", "feedback_id"),
    )

    id = Column(String(36), primary_key=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    feedback_id = Column(Integer, nullable=True)
    memoria_alvo_id = Column(String(36), nullable=True, index=True)
    titulo = Column(String(180), nullable=False)
    conteudo = Column(Text, nullable=False)
    categoria = Column(String(60), nullable=False, default="operacao")
    origem = Column(String(40), nullable=False, default="manual")
    fonte_json = Column(Text, nullable=False, default="{}")
    impacto_json = Column(Text, nullable=False, default="{}")
    status = Column(String(24), nullable=False, default="pending", index=True)
    revisado_por_id = Column(Integer, nullable=True)
    revisado_em = Column(DateTime(timezone=True), nullable=True)
    memoria_id = Column(String(36), nullable=True, index=True)
    caso_regressao_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AssistenteIAMemoriaVersao(Base):
    __tablename__ = "assistente_ia_memoria_versoes"
    __table_args__ = (
        Index(
            "ix_assistente_ia_memoria_versoes_memoria_versao",
            "memoria_id",
            "versao",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    memoria_id = Column(String(36), nullable=False, index=True)
    versao = Column(Integer, nullable=False)
    titulo = Column(String(180), nullable=False)
    conteudo = Column(Text, nullable=False)
    categoria = Column(String(60), nullable=False)
    origem = Column(String(40), nullable=False)
    tipo_alteracao = Column(String(24), nullable=False, default="create")
    aprendizado_id = Column(String(36), nullable=True, index=True)
    criado_por_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssistenteIARegressaoCaso(Base):
    __tablename__ = "assistente_ia_regressao_casos"
    __table_args__ = (
        Index(
            "ix_assistente_ia_regressao_casos_status_created",
            "status",
            "created_at",
        ),
        Index("ix_assistente_ia_regressao_casos_memoria", "memoria_id"),
    )

    id = Column(String(36), primary_key=True)
    aprendizado_id = Column(String(36), nullable=True, index=True)
    memoria_id = Column(String(36), nullable=False, index=True)
    tipo = Column(String(40), nullable=False, default="memory_contract")
    prompt = Column(Text, nullable=False)
    expectativa_json = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="active", index=True)
    ultimo_status = Column(String(24), nullable=True)
    verificado_em = Column(DateTime(timezone=True), nullable=True)
    criado_por_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AssistenteIAConhecimentoDocumento(Base):
    __tablename__ = "assistente_ia_conhecimento_documentos"
    __table_args__ = (
        Index("ix_assistente_ia_documentos_status_categoria", "status", "categoria", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    titulo = Column(String(220), nullable=False)
    categoria = Column(String(60), nullable=False, default="manual")
    conteudo = Column(Text, nullable=False)
    fonte = Column(String(500), nullable=True)
    conteudo_sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="active", index=True)
    semantic_enabled = Column(Boolean, nullable=False, default=False)
    semantic_status = Column(String(24), nullable=False, default="disabled", index=True)
    embedding_model = Column(String(80), nullable=True)
    semantic_error = Column(Text, nullable=True)
    indexed_at = Column(DateTime(timezone=True), nullable=True)
    criado_por_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AssistenteIAConhecimentoTrecho(Base):
    __tablename__ = "assistente_ia_conhecimento_trechos"
    __table_args__ = (
        Index(
            "ix_assistente_ia_trechos_documento_ordem",
            "documento_id",
            "ordem",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    documento_id = Column(String(36), nullable=False, index=True)
    ordem = Column(Integer, nullable=False)
    conteudo = Column(Text, nullable=False)
    conteudo_sha256 = Column(String(64), nullable=False)
    embedding_json = Column(Text, nullable=False)
    embedding_model = Column(String(80), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssistenteIAMissao(Base):
    __tablename__ = "assistente_ia_missoes"
    __table_args__ = (
        Index(
            "ix_assistente_ia_missoes_enabled_next_run",
            "enabled",
            "next_run_at",
        ),
        Index(
            "ix_assistente_ia_missoes_usuario_updated",
            "usuario_id",
            "updated_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    titulo = Column(String(180), nullable=False)
    tipo = Column(String(40), nullable=False, index=True)
    configuracao_json = Column(Text, nullable=False, default="{}")
    recorrencia = Column(String(16), nullable=False, default="daily")
    horario_local = Column(String(5), nullable=False, default="07:00")
    dias_semana_json = Column(Text, nullable=False, default="[]")
    timezone = Column(String(64), nullable=False, default="America/Fortaleza")
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AssistenteIAExecucao(Base):
    __tablename__ = "assistente_ia_execucoes"
    __table_args__ = (
        Index(
            "ix_assistente_ia_execucoes_status_created",
            "status",
            "created_at",
        ),
        Index(
            "ix_assistente_ia_execucoes_usuario_tipo_created",
            "usuario_id",
            "tipo",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    missao_id = Column(String(36), nullable=True, index=True)
    tipo = Column(String(40), nullable=False, index=True)
    origem = Column(String(24), nullable=False, default="manual")
    status = Column(String(24), nullable=False, default="queued", index=True)
    entrada_json = Column(Text, nullable=False, default="{}")
    saida_json = Column(Text, nullable=True)
    erro = Column(Text, nullable=True)
    provider_response_id = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssistenteIAFeedback(Base):
    __tablename__ = "assistente_ia_feedbacks"
    __table_args__ = (
        Index("ix_assistente_ia_feedbacks_usuario_created", "usuario_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    mensagem_id = Column(Integer, nullable=False, index=True)
    conversa_id = Column(String(36), nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    avaliacao = Column(String(16), nullable=False)
    categoria = Column(String(60), nullable=True)
    comentario = Column(Text, nullable=True)
    correcao_esperada = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssistenteIARascunhoClinico(Base):
    __tablename__ = "assistente_ia_rascunhos_clinicos"
    __table_args__ = (
        Index("ix_assistente_ia_rascunhos_usuario_status", "usuario_id", "status", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    laudo_id = Column(Integer, nullable=False, index=True)
    conversa_id = Column(String(36), nullable=False, index=True)
    usuario_id = Column(Integer, nullable=False, index=True)
    titulo = Column(String(220), nullable=False)
    conteudo = Column(Text, nullable=False)
    alertas_json = Column(Text, nullable=True)
    fontes_json = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="draft", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
