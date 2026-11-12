"""Adds selected presentation field to prescription items."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260319_16"
DESCRIPTION = "Adiciona apresentacao selecionada aos itens da prescricao"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "prescricoes_itens"):
        return

    columns = _column_names(connection, "prescricoes_itens")
    if "apresentacao_selecionada" in columns:
        return

    column_type = "VARCHAR(255)" if dialect == "postgresql" else "TEXT"
    connection.execute(
        text(
            f"ALTER TABLE prescricoes_itens "
            f"ADD COLUMN apresentacao_selecionada {column_type}"
        )
    )
