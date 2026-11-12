"""Create upload dedupe cleanup runs table."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260405_24"
DESCRIPTION = "Cria tabela upload_dedupe_cleanup_runs para historico de limpeza automatica"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "upload_dedupe_cleanup_runs"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE upload_dedupe_cleanup_runs (
                        id SERIAL PRIMARY KEY,
                        executor VARCHAR(20) NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        retention_days INTEGER NOT NULL,
                        cutoff_date VARCHAR(10) NOT NULL,
                        deleted_rows INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT NULL,
                        duration_ms INTEGER NULL,
                        started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        finished_at TIMESTAMP NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE upload_dedupe_cleanup_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        executor TEXT NOT NULL,
                        status TEXT NOT NULL,
                        retention_days INTEGER NOT NULL,
                        cutoff_date TEXT NOT NULL,
                        deleted_rows INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT NULL,
                        duration_ms INTEGER NULL,
                        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        finished_at TEXT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_upload_dedupe_cleanup_runs_created_at "
            "ON upload_dedupe_cleanup_runs (created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_upload_dedupe_cleanup_runs_status_created_at "
            "ON upload_dedupe_cleanup_runs (status, created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_upload_dedupe_cleanup_runs_executor_created_at "
            "ON upload_dedupe_cleanup_runs (executor, created_at)"
        )
    )
