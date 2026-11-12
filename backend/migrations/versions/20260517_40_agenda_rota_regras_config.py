"""Add route rules configuration column for agenda scheduling."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260517_40"
DESCRIPTION = "Adiciona agenda_rota_regras em configuracoes"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "configuracoes"):
        return

    columns = _column_names(connection, "configuracoes")
    if "agenda_rota_regras" in columns:
        return

    if dialect == "postgresql":
        connection.execute(
            text("ALTER TABLE configuracoes ADD COLUMN agenda_rota_regras TEXT")
        )
        return

    connection.execute(text("ALTER TABLE configuracoes ADD COLUMN agenda_rota_regras TEXT"))
