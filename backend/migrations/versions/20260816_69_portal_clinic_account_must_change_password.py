"""Adiciona must_change_password em portal_clinic_accounts."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260816_69"
DESCRIPTION = "Adiciona portal_clinic_accounts.must_change_password (senha temporaria de convite)"

TABLE_NAME = "portal_clinic_accounts"
COLUMN_NAME = "must_change_password"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if TABLE_NAME not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    if COLUMN_NAME in columns:
        return

    boolean_type = "BOOLEAN" if dialect == "postgresql" else "BOOLEAN"
    connection.execute(
        text(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {COLUMN_NAME} {boolean_type} DEFAULT FALSE")
    )
    connection.execute(
        text(f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = FALSE WHERE {COLUMN_NAME} IS NULL")
    )
    if dialect == "postgresql":
        connection.execute(
            text(f"ALTER TABLE {TABLE_NAME} ALTER COLUMN {COLUMN_NAME} SET NOT NULL")
        )
