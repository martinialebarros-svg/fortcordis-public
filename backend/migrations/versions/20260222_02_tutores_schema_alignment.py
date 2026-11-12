"""Aligns legacy stage schema for `tutores` with current model usage."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260222_02"
DESCRIPTION = "Alinha schema legado de tutores (nome_key e nullability)"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "tutores" not in inspector.get_table_names():
        return

    columns = _column_map(connection, "tutores")

    if "nome_key" not in columns:
        connection.execute(text("ALTER TABLE tutores ADD COLUMN nome_key TEXT"))
        columns = _column_map(connection, "tutores")

    # Banco legado no stage estava com NOT NULL em nome_key, mas fluxo atual
    # nem sempre depende desse campo para operação.
    if dialect == "postgresql" and "nome_key" in columns:
        is_nullable = bool(columns["nome_key"].get("nullable", True))
        if not is_nullable:
            connection.execute(text("ALTER TABLE tutores ALTER COLUMN nome_key DROP NOT NULL"))

