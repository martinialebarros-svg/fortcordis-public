"""Add user preference column for push action types."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260405_26"
DESCRIPTION = "Adiciona configuracoes_usuario.notificacoes_push_tipos para filtro de eventos push"

DEFAULT_TYPES = "created,updated,status_changed,deleted"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_exists(connection: Connection, table_name: str, column_name: str) -> bool:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return False
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "configuracoes_usuario"):
        return

    if not _column_exists(connection, "configuracoes_usuario", "notificacoes_push_tipos"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    ALTER TABLE configuracoes_usuario
                    ADD COLUMN notificacoes_push_tipos TEXT NULL
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    ALTER TABLE configuracoes_usuario
                    ADD COLUMN notificacoes_push_tipos TEXT NULL
                    """
                )
            )

    connection.execute(
        text(
            """
            UPDATE configuracoes_usuario
            SET notificacoes_push_tipos = :default_types
            WHERE notificacoes_push_tipos IS NULL
            """
        ),
        {"default_types": DEFAULT_TYPES},
    )
