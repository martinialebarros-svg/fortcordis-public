"""Add advanced push preferences and scheduled push notifications table."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260405_27"
DESCRIPTION = (
    "Adiciona preferencias avancadas de push em configuracoes_usuario e cria "
    "push_scheduled_notifications para lembretes/soneca"
)

DEFAULT_TYPES = "created,updated,status_changed,deleted,os_generated,payment_received,os_deleted,payment_pending"
DEFAULT_HIGH_PRIORITY_TYPES = "os_deleted,payment_pending"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_exists(connection: Connection, table_name: str, column_name: str) -> bool:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return False
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def _ensure_configuracoes_usuario_columns(connection: Connection) -> None:
    if not _table_exists(connection, "configuracoes_usuario"):
        return

    if not _column_exists(connection, "configuracoes_usuario", "notificacoes_push_prioridade_alta_tipos"):
        connection.execute(
            text(
                """
                ALTER TABLE configuracoes_usuario
                ADD COLUMN notificacoes_push_prioridade_alta_tipos TEXT NULL
                """
            )
        )

    if not _column_exists(connection, "configuracoes_usuario", "notificacoes_push_agrupar"):
        connection.execute(
            text(
                """
                ALTER TABLE configuracoes_usuario
                ADD COLUMN notificacoes_push_agrupar BOOLEAN NULL
                """
            )
        )

    if not _column_exists(connection, "configuracoes_usuario", "notificacoes_push_lembrete_pendencias"):
        connection.execute(
            text(
                """
                ALTER TABLE configuracoes_usuario
                ADD COLUMN notificacoes_push_lembrete_pendencias BOOLEAN NULL
                """
            )
        )

    if not _column_exists(connection, "configuracoes_usuario", "notificacoes_push_lembrete_horas"):
        connection.execute(
            text(
                """
                ALTER TABLE configuracoes_usuario
                ADD COLUMN notificacoes_push_lembrete_horas INTEGER NULL
                """
            )
        )

    if not _column_exists(connection, "configuracoes_usuario", "notificacoes_push_perfil"):
        connection.execute(
            text(
                """
                ALTER TABLE configuracoes_usuario
                ADD COLUMN notificacoes_push_perfil VARCHAR(30) NULL
                """
            )
        )

    connection.execute(
        text(
            """
            UPDATE configuracoes_usuario
            SET notificacoes_push_tipos = :default_types
            WHERE notificacoes_push_tipos IS NULL OR TRIM(notificacoes_push_tipos) = ''
            """
        ),
        {"default_types": DEFAULT_TYPES},
    )

    connection.execute(
        text(
            """
            UPDATE configuracoes_usuario
            SET notificacoes_push_tipos = TRIM(notificacoes_push_tipos) || ',payment_pending'
            WHERE notificacoes_push_tipos IS NOT NULL
              AND TRIM(notificacoes_push_tipos) <> ''
              AND LOWER(notificacoes_push_tipos) NOT LIKE '%payment_pending%'
            """
        )
    )

    connection.execute(
        text(
            """
            UPDATE configuracoes_usuario
            SET notificacoes_push_prioridade_alta_tipos = :default_value
            WHERE notificacoes_push_prioridade_alta_tipos IS NULL
               OR TRIM(notificacoes_push_prioridade_alta_tipos) = ''
            """
        ),
        {"default_value": DEFAULT_HIGH_PRIORITY_TYPES},
    )

    connection.execute(
        text(
            """
            UPDATE configuracoes_usuario
            SET notificacoes_push_agrupar = TRUE
            WHERE notificacoes_push_agrupar IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE configuracoes_usuario
            SET notificacoes_push_lembrete_pendencias = TRUE
            WHERE notificacoes_push_lembrete_pendencias IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE configuracoes_usuario
            SET notificacoes_push_lembrete_horas = 6
            WHERE notificacoes_push_lembrete_horas IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE configuracoes_usuario
            SET notificacoes_push_perfil = 'custom'
            WHERE notificacoes_push_perfil IS NULL OR TRIM(notificacoes_push_perfil) = ''
            """
        )
    )


def _ensure_push_scheduled_notifications_table(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "push_scheduled_notifications"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE push_scheduled_notifications (
                    id SERIAL PRIMARY KEY,
                    kind VARCHAR(40) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    user_id INTEGER NULL,
                    module VARCHAR(40) NULL,
                    action VARCHAR(80) NULL,
                    resource_type VARCHAR(40) NULL,
                    resource_id INTEGER NULL,
                    title TEXT NULL,
                    body TEXT NULL,
                    url TEXT NULL,
                    priority VARCHAR(12) NULL,
                    payload_json TEXT NULL,
                    source_notification_id VARCHAR(64) NULL,
                    snooze_minutes INTEGER NULL,
                    send_at TIMESTAMP NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NULL,
                    processed_at TIMESTAMP NULL,
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
                CREATE TABLE push_scheduled_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    user_id INTEGER NULL,
                    module TEXT NULL,
                    action TEXT NULL,
                    resource_type TEXT NULL,
                    resource_id INTEGER NULL,
                    title TEXT NULL,
                    body TEXT NULL,
                    url TEXT NULL,
                    priority TEXT NULL,
                    payload_json TEXT NULL,
                    source_notification_id TEXT NULL,
                    snooze_minutes INTEGER NULL,
                    send_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NULL,
                    processed_at TEXT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NULL
                )
                """
            )
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_push_sched_status_send_at "
            "ON push_scheduled_notifications (status, send_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_push_sched_kind_status "
            "ON push_scheduled_notifications (kind, status)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_push_sched_user_status "
            "ON push_scheduled_notifications (user_id, status)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_push_sched_resource "
            "ON push_scheduled_notifications (resource_type, resource_id)"
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _ensure_configuracoes_usuario_columns(connection)
    _ensure_push_scheduled_notifications_table(connection, dialect)
