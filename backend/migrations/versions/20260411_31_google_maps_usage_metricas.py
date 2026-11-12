"""Create Google Maps usage metrics table for backend observability."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260411_31"
DESCRIPTION = "Cria tabela google_maps_usage_metricas para observabilidade de rotas Google"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "google_maps_usage_metricas"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE google_maps_usage_metricas (
                        id SERIAL PRIMARY KEY,
                        service VARCHAR(40) NOT NULL,
                        operation VARCHAR(80) NOT NULL,
                        provider VARCHAR(40) NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'ok',
                        origem_clinica_id INTEGER NULL,
                        destino_clinica_id INTEGER NULL,
                        perfil VARCHAR(20) NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE google_maps_usage_metricas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        service TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ok',
                        origem_clinica_id INTEGER NULL,
                        destino_clinica_id INTEGER NULL,
                        perfil TEXT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_google_maps_usage_metricas_created_at "
            "ON google_maps_usage_metricas (created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_google_maps_usage_metricas_service_created "
            "ON google_maps_usage_metricas (service, created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_google_maps_usage_metricas_operation_created "
            "ON google_maps_usage_metricas (operation, created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_google_maps_usage_metricas_pair_created "
            "ON google_maps_usage_metricas (origem_clinica_id, destino_clinica_id, created_at)"
        )
    )
