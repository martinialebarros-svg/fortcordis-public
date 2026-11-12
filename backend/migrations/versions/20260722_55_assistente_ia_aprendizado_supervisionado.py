"""Add supervised learning suggestions, memory versions and regression contracts."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260722_55"
DESCRIPTION = "Adiciona aprendizado supervisionado, versoes de memoria e regressao automatica"


def _timestamp(dialect: str) -> tuple[str, str]:
    if dialect == "postgresql":
        return "TIMESTAMP WITH TIME ZONE", "NOW()"
    return "DATETIME", "CURRENT_TIMESTAMP"


def _identity(dialect: str) -> str:
    return "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


def upgrade(connection: Connection, dialect: str) -> None:
    timestamp_type, timestamp_default = _timestamp(dialect)
    identity = _identity(dialect)
    tables = set(inspect(connection).get_table_names())

    if "assistente_ia_memorias" in tables:
        columns = {column["name"] for column in inspect(connection).get_columns("assistente_ia_memorias")}
        if "versao_atual" not in columns:
            connection.execute(text(
                "ALTER TABLE assistente_ia_memorias "
                "ADD COLUMN versao_atual INTEGER NOT NULL DEFAULT 1"
            ))

    if "assistente_ia_aprendizados" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_aprendizados (
                id VARCHAR(36) PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                feedback_id INTEGER NULL,
                memoria_alvo_id VARCHAR(36) NULL,
                titulo VARCHAR(180) NOT NULL,
                conteudo TEXT NOT NULL,
                categoria VARCHAR(60) NOT NULL DEFAULT 'operacao',
                origem VARCHAR(40) NOT NULL DEFAULT 'manual',
                fonte_json TEXT NOT NULL DEFAULT '{{}}',
                impacto_json TEXT NOT NULL DEFAULT '{{}}',
                status VARCHAR(24) NOT NULL DEFAULT 'pending',
                revisado_por_id INTEGER NULL,
                revisado_em {timestamp_type} NULL,
                memoria_id VARCHAR(36) NULL,
                caso_regressao_id VARCHAR(36) NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "assistente_ia_memoria_versoes" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_memoria_versoes (
                id {identity},
                memoria_id VARCHAR(36) NOT NULL,
                versao INTEGER NOT NULL,
                titulo VARCHAR(180) NOT NULL,
                conteudo TEXT NOT NULL,
                categoria VARCHAR(60) NOT NULL,
                origem VARCHAR(40) NOT NULL,
                tipo_alteracao VARCHAR(24) NOT NULL DEFAULT 'create',
                aprendizado_id VARCHAR(36) NULL,
                criado_por_id INTEGER NOT NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                UNIQUE (memoria_id, versao)
            )
        """))

    if "assistente_ia_regressao_casos" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_regressao_casos (
                id VARCHAR(36) PRIMARY KEY,
                aprendizado_id VARCHAR(36) NULL,
                memoria_id VARCHAR(36) NOT NULL,
                tipo VARCHAR(40) NOT NULL DEFAULT 'memory_contract',
                prompt TEXT NOT NULL,
                expectativa_json TEXT NOT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'active',
                ultimo_status VARCHAR(24) NULL,
                verificado_em {timestamp_type} NULL,
                criado_por_id INTEGER NOT NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    statements = (
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_aprendizados_usuario ON assistente_ia_aprendizados (usuario_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_aprendizados_status ON assistente_ia_aprendizados (status)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_aprendizados_feedback ON assistente_ia_aprendizados (feedback_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_aprendizados_memoria_alvo ON assistente_ia_aprendizados (memoria_alvo_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_aprendizados_memoria ON assistente_ia_aprendizados (memoria_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_aprendizados_usuario_status_created ON assistente_ia_aprendizados (usuario_id, status, created_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_assistente_ia_memoria_versoes_memoria_versao ON assistente_ia_memoria_versoes (memoria_id, versao)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_memoria_versoes_aprendizado ON assistente_ia_memoria_versoes (aprendizado_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_regressao_casos_aprendizado ON assistente_ia_regressao_casos (aprendizado_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_regressao_casos_memoria ON assistente_ia_regressao_casos (memoria_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_regressao_casos_status ON assistente_ia_regressao_casos (status)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_regressao_casos_status_created ON assistente_ia_regressao_casos (status, created_at)",
    )
    for statement in statements:
        connection.execute(text(statement))
