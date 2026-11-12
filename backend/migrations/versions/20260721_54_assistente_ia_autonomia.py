"""Add proactive radar, read-only missions, semantic retrieval and eval runs."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260721_54"
DESCRIPTION = "Adiciona radar, missoes de leitura, busca semantica e laboratorio de avaliacoes"


def _timestamp(dialect: str) -> tuple[str, str]:
    if dialect == "postgresql":
        return "TIMESTAMP WITH TIME ZONE", "NOW()"
    return "DATETIME", "CURRENT_TIMESTAMP"


def _identity(dialect: str) -> str:
    return "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _add_document_semantic_columns(connection: Connection) -> None:
    inspector = inspect(connection)
    if "assistente_ia_conhecimento_documentos" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("assistente_ia_conhecimento_documentos")}
    boolean_false = "FALSE" if connection.dialect.name == "postgresql" else "0"
    timestamp_type, _ = _timestamp(connection.dialect.name)
    additions = {
        "semantic_enabled": f"BOOLEAN NOT NULL DEFAULT {boolean_false}",
        "semantic_status": "VARCHAR(24) NOT NULL DEFAULT 'disabled'",
        "embedding_model": "VARCHAR(80) NULL",
        "semantic_error": "TEXT NULL",
        "indexed_at": f"{timestamp_type} NULL",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(text(f"ALTER TABLE assistente_ia_conhecimento_documentos ADD COLUMN {name} {definition}"))


def upgrade(connection: Connection, dialect: str) -> None:
    timestamp_type, timestamp_default = _timestamp(dialect)
    identity = _identity(dialect)
    boolean_true = "TRUE" if dialect == "postgresql" else "1"
    tables = set(inspect(connection).get_table_names())

    _add_document_semantic_columns(connection)

    if "assistente_ia_conhecimento_trechos" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_conhecimento_trechos (
                id {identity},
                documento_id VARCHAR(36) NOT NULL,
                ordem INTEGER NOT NULL,
                conteudo TEXT NOT NULL,
                conteudo_sha256 VARCHAR(64) NOT NULL,
                embedding_json TEXT NOT NULL,
                embedding_model VARCHAR(80) NOT NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                UNIQUE (documento_id, ordem)
            )
        """))

    if "assistente_ia_missoes" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_missoes (
                id VARCHAR(36) PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                titulo VARCHAR(180) NOT NULL,
                tipo VARCHAR(40) NOT NULL,
                configuracao_json TEXT NOT NULL DEFAULT '{{}}',
                recorrencia VARCHAR(16) NOT NULL DEFAULT 'daily',
                horario_local VARCHAR(5) NOT NULL DEFAULT '07:00',
                dias_semana_json TEXT NOT NULL DEFAULT '[]',
                timezone VARCHAR(64) NOT NULL DEFAULT 'America/Fortaleza',
                enabled BOOLEAN NOT NULL DEFAULT {boolean_true},
                next_run_at {timestamp_type} NULL,
                last_run_at {timestamp_type} NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "assistente_ia_execucoes" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_execucoes (
                id VARCHAR(36) PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                missao_id VARCHAR(36) NULL,
                tipo VARCHAR(40) NOT NULL,
                origem VARCHAR(24) NOT NULL DEFAULT 'manual',
                status VARCHAR(24) NOT NULL DEFAULT 'queued',
                entrada_json TEXT NOT NULL DEFAULT '{{}}',
                saida_json TEXT NULL,
                erro TEXT NULL,
                provider_response_id VARCHAR(255) NULL,
                started_at {timestamp_type} NULL,
                finished_at {timestamp_type} NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    statements = (
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_documentos_semantic_status ON assistente_ia_conhecimento_documentos (semantic_status)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_trechos_documento ON assistente_ia_conhecimento_trechos (documento_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_assistente_ia_trechos_documento_ordem ON assistente_ia_conhecimento_trechos (documento_id, ordem)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_missoes_usuario ON assistente_ia_missoes (usuario_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_missoes_tipo ON assistente_ia_missoes (tipo)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_missoes_enabled_next_run ON assistente_ia_missoes (enabled, next_run_at)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_execucoes_usuario ON assistente_ia_execucoes (usuario_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_execucoes_missao ON assistente_ia_execucoes (missao_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_execucoes_tipo ON assistente_ia_execucoes (tipo)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_execucoes_status_created ON assistente_ia_execucoes (status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_execucoes_usuario_tipo_created ON assistente_ia_execucoes (usuario_id, tipo, created_at)",
    )
    for statement in statements:
        connection.execute(text(statement))
