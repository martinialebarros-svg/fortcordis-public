"""Ensure medicamentos table has legacy-compatible columns used by current API."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260228_02"
DESCRIPTION = "Garante colunas principio_ativo, concentracao e forma_farmaceutica em medicamentos"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "medicamentos"):
        return

    columns = _column_names(connection, "medicamentos")

    missing = {
        "principio_ativo": ("VARCHAR(255)", "TEXT"),
        "concentracao": ("VARCHAR(255)", "TEXT"),
        "forma_farmaceutica": ("VARCHAR(255)", "TEXT"),
    }

    for col_name, (pg_type, sqlite_type) in missing.items():
        if col_name in columns:
            continue
        col_type = pg_type if dialect == "postgresql" else sqlite_type
        connection.execute(text(f"ALTER TABLE medicamentos ADD COLUMN {col_name} {col_type}"))
