"""Adds clinica_id columns to financeiro tables in an idempotent way."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260304_07"
DESCRIPTION = "Adds clinica_id to transacoes, contas_pagar and contas_receber"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _ensure_column(connection: Connection, table_name: str, column_name: str) -> None:
    if not _table_exists(connection, table_name):
        return

    columns = _column_names(connection, table_name)
    if column_name in columns:
        return

    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER"))


def upgrade(connection: Connection, dialect: str) -> None:
    _ = dialect  # kept for runner signature compatibility
    _ensure_column(connection, "transacoes", "clinica_id")
    _ensure_column(connection, "contas_pagar", "clinica_id")
    _ensure_column(connection, "contas_receber", "clinica_id")
