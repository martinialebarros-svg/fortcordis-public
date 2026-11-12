"""Create bounded persisted HTTP latency samples for PERF-17."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260903_80"
DESCRIPTION = "Cria amostras persistentes de latencia HTTP por release"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "runtime_http_latency_metrics"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE runtime_http_latency_metrics (
                        id SERIAL PRIMARY KEY,
                        endpoint VARCHAR(120) NOT NULL,
                        release_id VARCHAR(80) NOT NULL DEFAULT 'unknown',
                        status_code INTEGER NOT NULL,
                        duration_ms DOUBLE PRECISION NOT NULL,
                        database_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                        pool_wait_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE runtime_http_latency_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        endpoint TEXT NOT NULL,
                        release_id TEXT NOT NULL DEFAULT 'unknown',
                        status_code INTEGER NOT NULL,
                        duration_ms REAL NOT NULL,
                        database_ms REAL NOT NULL DEFAULT 0,
                        pool_wait_ms REAL NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_runtime_http_latency_metrics_created_at "
            "ON runtime_http_latency_metrics (created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_runtime_http_latency_metrics_endpoint_release_created "
            "ON runtime_http_latency_metrics (endpoint, release_id, created_at)"
        )
    )
