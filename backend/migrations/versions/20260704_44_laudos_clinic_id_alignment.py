"""Align laudos clinic_id column for clinic portal exam scope."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260704_44"
DESCRIPTION = "Garante coluna clinic_id em laudos para escopo de exames do portal da clinica"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "laudos" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("laudos")}
    if "clinic_id" not in columns:
        connection.execute(text("ALTER TABLE laudos ADD COLUMN clinic_id INTEGER"))

    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_laudos_clinic_id ON laudos (clinic_id)")
    )
