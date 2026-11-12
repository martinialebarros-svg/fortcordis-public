"""Expand the admin AI with supervised memory, knowledge, feedback and safe operations."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260721_53"
DESCRIPTION = "Expande Mente FortCordis com memoria, conhecimento, feedback, rascunhos e bloqueios"


def _timestamp(dialect: str) -> tuple[str, str]:
    if dialect == "postgresql":
        return "TIMESTAMP WITH TIME ZONE", "NOW()"
    return "DATETIME", "CURRENT_TIMESTAMP"


def _identity(dialect: str) -> str:
    return "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _add_message_telemetry(connection: Connection) -> None:
    inspector = inspect(connection)
    if "assistente_ia_mensagens" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("assistente_ia_mensagens")}
    additions = {
        "provider_response_id": "VARCHAR(255) NULL",
        "input_tokens": "INTEGER NULL",
        "output_tokens": "INTEGER NULL",
        "total_tokens": "INTEGER NULL",
        "latency_ms": "INTEGER NULL",
        "provider_status": "VARCHAR(32) NULL",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(text(f"ALTER TABLE assistente_ia_mensagens ADD COLUMN {name} {definition}"))


def upgrade(connection: Connection, dialect: str) -> None:
    timestamp_type, timestamp_default = _timestamp(dialect)
    boolean_type = "BOOLEAN"
    boolean_true = "TRUE" if dialect == "postgresql" else "1"
    identity = _identity(dialect)
    tables = set(inspect(connection).get_table_names())

    _add_message_telemetry(connection)

    if "assistente_ia_memorias" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_memorias (
                id VARCHAR(36) PRIMARY KEY,
                titulo VARCHAR(180) NOT NULL,
                conteudo TEXT NOT NULL,
                categoria VARCHAR(60) NOT NULL DEFAULT 'operacao',
                origem VARCHAR(40) NOT NULL DEFAULT 'admin',
                status VARCHAR(24) NOT NULL DEFAULT 'pending',
                criado_por_id INTEGER NOT NULL,
                aprovado_por_id INTEGER NULL,
                aprovado_em {timestamp_type} NULL,
                rejeitado_em {timestamp_type} NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "assistente_ia_conhecimento_documentos" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_conhecimento_documentos (
                id VARCHAR(36) PRIMARY KEY,
                titulo VARCHAR(220) NOT NULL,
                categoria VARCHAR(60) NOT NULL DEFAULT 'manual',
                conteudo TEXT NOT NULL,
                fonte VARCHAR(500) NULL,
                conteudo_sha256 VARCHAR(64) NOT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'active',
                criado_por_id INTEGER NOT NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "assistente_ia_feedbacks" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_feedbacks (
                id {identity},
                mensagem_id INTEGER NOT NULL,
                conversa_id VARCHAR(36) NOT NULL,
                usuario_id INTEGER NOT NULL,
                avaliacao VARCHAR(16) NOT NULL,
                categoria VARCHAR(60) NULL,
                comentario TEXT NULL,
                correcao_esperada TEXT NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "assistente_ia_rascunhos_clinicos" not in tables:
        connection.execute(text(f"""
            CREATE TABLE assistente_ia_rascunhos_clinicos (
                id VARCHAR(36) PRIMARY KEY,
                laudo_id INTEGER NOT NULL,
                conversa_id VARCHAR(36) NOT NULL,
                usuario_id INTEGER NOT NULL,
                titulo VARCHAR(220) NOT NULL,
                conteudo TEXT NOT NULL,
                alertas_json TEXT NULL,
                fontes_json TEXT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'draft',
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "agenda_bloqueios" not in tables:
        connection.execute(text(f"""
            CREATE TABLE agenda_bloqueios (
                id VARCHAR(36) PRIMARY KEY,
                inicio {timestamp_type} NOT NULL,
                fim {timestamp_type} NOT NULL,
                motivo TEXT NOT NULL,
                ativo {boolean_type} NOT NULL DEFAULT {boolean_true},
                criado_por_id INTEGER NOT NULL,
                criado_por_nome VARCHAR(180) NULL,
                liberado_por_id INTEGER NULL,
                liberado_em {timestamp_type} NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NULL
            )
        """))

    statements = (
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_memorias_status ON assistente_ia_memorias (status)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_memorias_criado_por ON assistente_ia_memorias (criado_por_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_memorias_status_categoria ON assistente_ia_memorias (status, categoria, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_documentos_status ON assistente_ia_conhecimento_documentos (status)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_documentos_sha ON assistente_ia_conhecimento_documentos (conteudo_sha256)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_documentos_status_categoria ON assistente_ia_conhecimento_documentos (status, categoria, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_feedbacks_mensagem ON assistente_ia_feedbacks (mensagem_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_feedbacks_conversa ON assistente_ia_feedbacks (conversa_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_feedbacks_usuario_created ON assistente_ia_feedbacks (usuario_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_rascunhos_laudo ON assistente_ia_rascunhos_clinicos (laudo_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_rascunhos_conversa ON assistente_ia_rascunhos_clinicos (conversa_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistente_ia_rascunhos_usuario_status ON assistente_ia_rascunhos_clinicos (usuario_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_agenda_bloqueios_ativo ON agenda_bloqueios (ativo)",
        "CREATE INDEX IF NOT EXISTS ix_agenda_bloqueios_criado_por ON agenda_bloqueios (criado_por_id)",
        "CREATE INDEX IF NOT EXISTS ix_agenda_bloqueios_ativo_inicio_fim ON agenda_bloqueios (ativo, inicio, fim)",
    )
    for statement in statements:
        connection.execute(text(statement))
