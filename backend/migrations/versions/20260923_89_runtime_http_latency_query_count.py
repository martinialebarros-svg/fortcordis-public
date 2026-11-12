"""Add database query count to persisted HTTP latency samples."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260923_89"
DESCRIPTION = "Adiciona contagem de consultas as amostras de latencia HTTP"


def upgrade(connection: Connection, dialect: str) -> None:
    del dialect
    inspector = inspect(connection)
    if "runtime_http_latency_metrics" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("runtime_http_latency_metrics")
    }
    if "database_query_count" in columns:
        return

    connection.execute(
        text(
            "ALTER TABLE runtime_http_latency_metrics "
            "ADD COLUMN database_query_count INTEGER NOT NULL DEFAULT 0"
        )
    )
