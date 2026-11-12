"""Aligns legacy `tutores` and `pacientes` timestamp columns for inserts."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260222_03"
DESCRIPTION = "Alinha created_at legados de tutores/pacientes com default e backfill"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _ensure_column(connection: Connection, table_name: str, column_name: str) -> None:
    columns = _column_map(connection, table_name)
    if column_name in columns:
        return
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT"))


def _align_created_at_postgres(connection: Connection, table_name: str) -> None:
    _ensure_column(connection, table_name, "created_at")
    _ensure_column(connection, table_name, "updated_at")

    connection.execute(
        text(f"UPDATE {table_name} SET created_at = NOW()::text WHERE created_at IS NULL")
    )
    connection.execute(
        text(f"ALTER TABLE {table_name} ALTER COLUMN created_at SET DEFAULT NOW()::text")
    )

    columns = _column_map(connection, table_name)
    is_nullable = bool(columns["created_at"].get("nullable", True))
    if is_nullable:
        connection.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN created_at SET NOT NULL"))


def _align_created_at_sqlite(connection: Connection, table_name: str) -> None:
    _ensure_column(connection, table_name, "created_at")
    _ensure_column(connection, table_name, "updated_at")
    connection.execute(
        text(
            f"""
            UPDATE {table_name}
            SET created_at = strftime('%Y-%m-%d %H:%M:%S', 'now')
            WHERE created_at IS NULL
            """
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())

    target_tables = [table for table in ("tutores", "pacientes") if table in table_names]
    if not target_tables:
        return

    for table_name in target_tables:
        if dialect == "postgresql":
            _align_created_at_postgres(connection, table_name)
        elif dialect == "sqlite":
            _align_created_at_sqlite(connection, table_name)
        else:
            # Other dialects are not used in this project at the moment.
            _ensure_column(connection, table_name, "created_at")
            _ensure_column(connection, table_name, "updated_at")
