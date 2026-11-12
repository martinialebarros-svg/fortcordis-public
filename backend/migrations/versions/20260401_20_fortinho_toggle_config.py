"""Add Fortinho toggle column into configuracoes."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260401_20"
DESCRIPTION = "Adiciona fortinho_habilitado em configuracoes"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "configuracoes"):
        return

    columns = _column_names(connection, "configuracoes")
    if "fortinho_habilitado" not in columns:
        if dialect == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE configuracoes "
                    "ADD COLUMN fortinho_habilitado BOOLEAN DEFAULT FALSE"
                )
            )
        else:
            connection.execute(
                text("ALTER TABLE configuracoes ADD COLUMN fortinho_habilitado BOOLEAN")
            )

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                UPDATE configuracoes
                SET fortinho_habilitado = FALSE
                WHERE fortinho_habilitado IS NULL
                """
            )
        )
        return

    connection.execute(
        text(
            """
            UPDATE configuracoes
            SET fortinho_habilitado = 0
            WHERE fortinho_habilitado IS NULL
            """
        )
    )
