"""Adiciona coluna especie ao atendimento clinico."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260322_17"
DESCRIPTION = "Adiciona especie ao atendimento clinico"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "atendimentos_clinicos"):
        return

    columns = _column_names(connection, "atendimentos_clinicos")
    if "especie" in columns:
        return

    column_type = "VARCHAR(255)" if dialect == "postgresql" else "TEXT"
    connection.execute(
        text(
            f"ALTER TABLE atendimentos_clinicos "
            f"ADD COLUMN especie {column_type}"
        )
    )
