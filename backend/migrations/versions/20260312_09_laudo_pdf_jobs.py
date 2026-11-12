"""Adds persisted async jobs for laudo PDF generation."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260312_09"
DESCRIPTION = "Adiciona jobs persistidos para geracao assincrona de PDF de laudos"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "laudo_pdf_jobs"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE laudo_pdf_jobs (
                        id SERIAL PRIMARY KEY,
                        laudo_id INTEGER NOT NULL,
                        requested_by_id INTEGER NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        cache_key VARCHAR(64) NOT NULL,
                        arquivo_nome VARCHAR(255),
                        arquivo_caminho VARCHAR(500),
                        erro TEXT,
                        tentativas INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        started_at TIMESTAMP,
                        finished_at TIMESTAMP,
                        expires_at TIMESTAMP
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE laudo_pdf_jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        laudo_id INTEGER NOT NULL,
                        requested_by_id INTEGER NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        cache_key VARCHAR(64) NOT NULL,
                        arquivo_nome VARCHAR(255),
                        arquivo_caminho VARCHAR(500),
                        erro TEXT,
                        tentativas INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        started_at DATETIME,
                        finished_at DATETIME,
                        expires_at DATETIME
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_laudo_pdf_jobs_laudo_id "
            "ON laudo_pdf_jobs (laudo_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_laudo_pdf_jobs_requested_by_id "
            "ON laudo_pdf_jobs (requested_by_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_laudo_pdf_jobs_status "
            "ON laudo_pdf_jobs (status)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_laudo_pdf_jobs_cache_key "
            "ON laudo_pdf_jobs (cache_key)"
        )
    )
