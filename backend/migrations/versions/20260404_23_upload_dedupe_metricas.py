"""Create upload dedupe metrics table for observability."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260404_23"
DESCRIPTION = "Cria tabela upload_dedupe_metricas para observabilidade de dedupe"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "upload_dedupe_metricas"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE upload_dedupe_metricas (
                        id SERIAL PRIMARY KEY,
                        atendimento_id INTEGER NOT NULL,
                        clinica_id INTEGER NULL,
                        evento VARCHAR(40) NOT NULL,
                        dedupe_key VARCHAR(120) NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE upload_dedupe_metricas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        atendimento_id INTEGER NOT NULL,
                        clinica_id INTEGER NULL,
                        evento TEXT NOT NULL,
                        dedupe_key TEXT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_upload_dedupe_metricas_created_at "
            "ON upload_dedupe_metricas (created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_upload_dedupe_metricas_evento_created_at "
            "ON upload_dedupe_metricas (evento, created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_upload_dedupe_metricas_clinica_created_at "
            "ON upload_dedupe_metricas (clinica_id, created_at)"
        )
    )
