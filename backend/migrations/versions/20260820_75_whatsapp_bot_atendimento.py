"""Cria o schema do chatbot de atendimento do WhatsApp (Fase 1 - so schema).

Nenhuma tabela aqui e lida ou escrita em runtime ainda: e o encanamento de
banco para as fases seguintes (fila/worker, portoes, geracao). Ver
docs/specs/whatsapp-chatbot-atendimento/spec.md.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260820_75"
DESCRIPTION = (
    "Cria whatsapp_bot_jobs/respostas/conversa_estado e as colunas "
    "whatsapp_bot_atendimento_habilitado/whatsapp_bot_modo em configuracoes"
)


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _create_whatsapp_bot_jobs(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "whatsapp_bot_jobs"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE whatsapp_bot_jobs (
                    id SERIAL PRIMARY KEY,
                    wa_identity VARCHAR(30) NOT NULL,
                    conversation_id VARCHAR(64) NOT NULL,
                    wa_message_id VARCHAR(160) NOT NULL UNIQUE,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    scheduled_for TIMESTAMP NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE whatsapp_bot_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wa_identity TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    wa_message_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    scheduled_for DATETIME NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_whatsapp_bot_jobs_status_scheduled_for "
            "ON whatsapp_bot_jobs (status, scheduled_for)"
        )
    )


def _create_whatsapp_bot_respostas(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "whatsapp_bot_respostas"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE whatsapp_bot_respostas (
                    id SERIAL PRIMARY KEY,
                    job_id INTEGER NOT NULL,
                    wa_identity VARCHAR(30) NOT NULL,
                    conversation_id VARCHAR(64) NOT NULL,
                    decisao VARCHAR(20) NOT NULL,
                    motivo TEXT,
                    texto_gerado TEXT,
                    texto_enviado TEXT,
                    modelo VARCHAR(100),
                    prompt_version VARCHAR(50),
                    tools_usadas TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    latencia_ms INTEGER,
                    resolution VARCHAR(20),
                    match_type VARCHAR(20),
                    feedback VARCHAR(20),
                    enviado_por_id INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE whatsapp_bot_respostas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    wa_identity TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    decisao TEXT NOT NULL,
                    motivo TEXT,
                    texto_gerado TEXT,
                    texto_enviado TEXT,
                    modelo TEXT,
                    prompt_version TEXT,
                    tools_usadas TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    latencia_ms INTEGER,
                    resolution TEXT,
                    match_type TEXT,
                    feedback TEXT,
                    enviado_por_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_whatsapp_bot_respostas_job_id "
            "ON whatsapp_bot_respostas (job_id)"
        )
    )


def _create_whatsapp_bot_conversa_estado(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "whatsapp_bot_conversa_estado"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE whatsapp_bot_conversa_estado (
                    wa_identity VARCHAR(30) PRIMARY KEY,
                    modo VARCHAR(20) NOT NULL DEFAULT 'suggest',
                    pausado_ate TIMESTAMP,
                    handoff_motivo VARCHAR(50),
                    atualizado_por_id INTEGER,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE whatsapp_bot_conversa_estado (
                    wa_identity TEXT PRIMARY KEY,
                    modo TEXT NOT NULL DEFAULT 'suggest',
                    pausado_ate DATETIME,
                    handoff_motivo TEXT,
                    atualizado_por_id INTEGER,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )


def _add_configuracoes_columns(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "configuracoes"):
        return

    columns = _column_names(connection, "configuracoes")

    if "whatsapp_bot_atendimento_habilitado" not in columns:
        if dialect == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE configuracoes "
                    "ADD COLUMN whatsapp_bot_atendimento_habilitado BOOLEAN DEFAULT FALSE"
                )
            )
        else:
            connection.execute(
                text(
                    "ALTER TABLE configuracoes "
                    "ADD COLUMN whatsapp_bot_atendimento_habilitado BOOLEAN"
                )
            )

    if "whatsapp_bot_modo" not in columns:
        if dialect == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE configuracoes "
                    "ADD COLUMN whatsapp_bot_modo VARCHAR(20) DEFAULT 'suggest'"
                )
            )
        else:
            connection.execute(
                text("ALTER TABLE configuracoes ADD COLUMN whatsapp_bot_modo TEXT")
            )

    false_literal = "FALSE" if dialect == "postgresql" else "0"
    connection.execute(
        text(
            f"UPDATE configuracoes SET whatsapp_bot_atendimento_habilitado = {false_literal} "
            "WHERE whatsapp_bot_atendimento_habilitado IS NULL"
        )
    )
    connection.execute(
        text(
            "UPDATE configuracoes SET whatsapp_bot_modo = 'suggest' "
            "WHERE whatsapp_bot_modo IS NULL"
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _create_whatsapp_bot_jobs(connection, dialect)
    _create_whatsapp_bot_respostas(connection, dialect)
    _create_whatsapp_bot_conversa_estado(connection, dialect)
    _add_configuracoes_columns(connection, dialect)
