"""Add agenda exceptions by date into configuracoes."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260301_04"
DESCRIPTION = "Adiciona agenda_excecoes em configuracoes"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "configuracoes"):
        return

    columns = _column_names(connection, "configuracoes")
    if "agenda_excecoes" not in columns:
        connection.execute(text("ALTER TABLE configuracoes ADD COLUMN agenda_excecoes TEXT"))

    connection.execute(
        text(
            """
            UPDATE configuracoes
            SET agenda_excecoes = :agenda_excecoes
            WHERE agenda_excecoes IS NULL OR TRIM(agenda_excecoes) = ''
            """
        ),
        {"agenda_excecoes": "[]"},
    )
