"""Adds persisted async jobs for XML import processing."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260312_10"
DESCRIPTION = "Adiciona jobs persistidos para importacao assincrona de XML"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "xml_import_jobs"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE xml_import_jobs (
                        id SERIAL PRIMARY KEY,
                        requested_by_id INTEGER NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        arquivo_nome VARCHAR(255),
                        arquivo_caminho VARCHAR(500),
                        resultado_json TEXT,
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
                    CREATE TABLE xml_import_jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        requested_by_id INTEGER NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        arquivo_nome VARCHAR(255),
                        arquivo_caminho VARCHAR(500),
                        resultado_json TEXT,
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
            "CREATE INDEX IF NOT EXISTS ix_xml_import_jobs_requested_by_id "
            "ON xml_import_jobs (requested_by_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_xml_import_jobs_status "
            "ON xml_import_jobs (status)"
        )
    )
