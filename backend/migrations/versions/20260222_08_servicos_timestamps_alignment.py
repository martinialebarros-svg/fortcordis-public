"""Aligns legacy `servicos` timestamp defaults for insert compatibility."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260222_08"
DESCRIPTION = "Alinha defaults/backfill de created_at e updated_at em servicos"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _ensure_column(connection: Connection, table_name: str, column_name: str, definition: str) -> None:
    columns = _column_map(connection, table_name)
    if column_name in columns:
        return
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


def _upgrade_postgres(connection: Connection) -> None:
    _ensure_column(connection, "servicos", "created_at", "TIMESTAMP")
    _ensure_column(connection, "servicos", "updated_at", "TIMESTAMP")

    connection.execute(text("UPDATE servicos SET created_at = NOW() WHERE created_at IS NULL"))
    connection.execute(text("UPDATE servicos SET updated_at = NOW() WHERE updated_at IS NULL"))

    connection.execute(text("ALTER TABLE servicos ALTER COLUMN created_at SET DEFAULT NOW()"))
    connection.execute(text("ALTER TABLE servicos ALTER COLUMN updated_at SET DEFAULT NOW()"))


def _upgrade_sqlite(connection: Connection) -> None:
    _ensure_column(connection, "servicos", "created_at", "TEXT")
    _ensure_column(connection, "servicos", "updated_at", "TEXT")

    connection.execute(
        text(
            """
            UPDATE servicos
            SET created_at = COALESCE(created_at, strftime('%Y-%m-%d %H:%M:%S', 'now')),
                updated_at = COALESCE(updated_at, strftime('%Y-%m-%d %H:%M:%S', 'now'))
            """
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "servicos" not in inspector.get_table_names():
        return

    if dialect == "postgresql":
        _upgrade_postgres(connection)
    elif dialect == "sqlite":
        _upgrade_sqlite(connection)
    else:
        _upgrade_sqlite(connection)

