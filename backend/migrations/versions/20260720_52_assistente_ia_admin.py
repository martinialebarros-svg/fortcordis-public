"""Create the admin AI assistant conversation and approval tables."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260720_52"
DESCRIPTION = "Cria conversas, mensagens e aprovacoes do assistente IA admin"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())

    if "assistente_ia_conversas" not in tables:
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE assistente_ia_conversas (
                        id VARCHAR(36) PRIMARY KEY,
                        usuario_id INTEGER NOT NULL,
                        titulo VARCHAR(160) NOT NULL DEFAULT 'Nova conversa',
                        previous_response_id VARCHAR(255) NULL,
                        ativa BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE assistente_ia_conversas (
                        id VARCHAR(36) PRIMARY KEY,
                        usuario_id INTEGER NOT NULL,
                        titulo VARCHAR(160) NOT NULL DEFAULT 'Nova conversa',
                        previous_response_id VARCHAR(255),
                        ativa BOOLEAN NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    tables = set(inspect(connection).get_table_names())
    if "assistente_ia_mensagens" not in tables:
        identity = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
        timestamp_default = "NOW()" if dialect == "postgresql" else "CURRENT_TIMESTAMP"
        connection.execute(
            text(
                f"""
                CREATE TABLE assistente_ia_mensagens (
                    id {identity},
                    conversa_id VARCHAR(36) NOT NULL,
                    usuario_id INTEGER NOT NULL,
                    papel VARCHAR(20) NOT NULL,
                    conteudo TEXT NOT NULL,
                    ferramentas_json TEXT NULL,
                    acao_pendente_id VARCHAR(36) NULL,
                    created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
                )
                """
            )
        )

    tables = set(inspect(connection).get_table_names())
    if "assistente_ia_acoes_pendentes" not in tables:
        timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
        timestamp_default = "NOW()" if dialect == "postgresql" else "CURRENT_TIMESTAMP"
        connection.execute(
            text(
                f"""
                CREATE TABLE assistente_ia_acoes_pendentes (
                    id VARCHAR(36) PRIMARY KEY,
                    conversa_id VARCHAR(36) NOT NULL,
                    usuario_id INTEGER NOT NULL,
                    tipo_acao VARCHAR(80) NOT NULL,
                    argumentos_json TEXT NOT NULL,
                    alvo_snapshot_json TEXT NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'pending',
                    expires_at {timestamp_type} NOT NULL,
                    decided_at {timestamp_type} NULL,
                    executed_at {timestamp_type} NULL,
                    resultado_json TEXT NULL,
                    created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
                )
                """
            )
        )

    statements = (
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_conversas_usuario_id ON assistente_ia_conversas (usuario_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_conversas_usuario_updated ON assistente_ia_conversas (usuario_id, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_mensagens_conversa_id ON assistente_ia_mensagens (conversa_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_mensagens_usuario_id ON assistente_ia_mensagens (usuario_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_mensagens_acao_id ON assistente_ia_mensagens (acao_pendente_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_mensagens_conversa_created ON assistente_ia_mensagens (conversa_id, created_at, id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_acoes_conversa_id ON assistente_ia_acoes_pendentes (conversa_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_acoes_usuario_id ON assistente_ia_acoes_pendentes (usuario_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_acoes_status ON assistente_ia_acoes_pendentes (status)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_acoes_usuario_status ON assistente_ia_acoes_pendentes (usuario_id, status, created_at)",
    )
    for statement in statements:
        connection.execute(text(statement))
