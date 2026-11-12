"""Create bounded real-user frontend performance samples for PERF-23."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260930_94"
DESCRIPTION = "Cria amostras anonimas de desempenho percebido no frontend"


def upgrade(connection: Connection, dialect: str) -> None:
    if "runtime_frontend_performance_metrics" not in inspect(connection).get_table_names():
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE runtime_frontend_performance_metrics (
                        id SERIAL PRIMARY KEY,
                        route_group VARCHAR(40) NOT NULL,
                        release_id VARCHAR(80) NOT NULL DEFAULT 'unknown',
                        navigation_type VARCHAR(16) NOT NULL,
                        outcome VARCHAR(16) NOT NULL,
                        shell_ms DOUBLE PRECISION NOT NULL,
                        content_ms DOUBLE PRECISION NULL,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE runtime_frontend_performance_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        route_group TEXT NOT NULL,
                        release_id TEXT NOT NULL DEFAULT 'unknown',
                        navigation_type TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        shell_ms REAL NOT NULL,
                        content_ms REAL NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_runtime_frontend_performance_created_at "
            "ON runtime_frontend_performance_metrics (created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_runtime_frontend_performance_route_release_created "
            "ON runtime_frontend_performance_metrics (route_group, release_id, created_at)"
        )
    )
