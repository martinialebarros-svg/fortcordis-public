"""Create push subscriptions table for browser web push."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260405_25"
DESCRIPTION = "Cria tabela push_subscriptions para inscricoes de notificacoes push web"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "push_subscriptions"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE push_subscriptions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        endpoint TEXT NOT NULL UNIQUE,
                        p256dh TEXT NOT NULL,
                        auth TEXT NOT NULL,
                        expiration_time VARCHAR(64) NULL,
                        user_agent TEXT NULL,
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        last_success_at TIMESTAMP NULL,
                        last_failure_at TIMESTAMP NULL,
                        failure_reason TEXT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NULL
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE push_subscriptions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        endpoint TEXT NOT NULL UNIQUE,
                        p256dh TEXT NOT NULL,
                        auth TEXT NOT NULL,
                        expiration_time TEXT NULL,
                        user_agent TEXT NULL,
                        active INTEGER NOT NULL DEFAULT 1,
                        last_success_at TEXT NULL,
                        last_failure_at TEXT NULL,
                        failure_reason TEXT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NULL
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user_id "
            "ON push_subscriptions (user_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_active "
            "ON push_subscriptions (active)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user_active "
            "ON push_subscriptions (user_id, active)"
        )
    )
