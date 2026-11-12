"""Ensures legacy `servicos.preco` column exists for ORM compatibility."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260222_07"
DESCRIPTION = "Garante coluna legado servicos.preco para compatibilidade"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "servicos" not in inspector.get_table_names():
        return

    columns = _column_map(connection, "servicos")
    if "preco" not in columns:
        connection.execute(
            text("ALTER TABLE servicos ADD COLUMN preco NUMERIC(10,2) DEFAULT 0")
        )

    # Backfill opcional: usa o preco comercial de Fortaleza quando vazio.
    connection.execute(
        text(
            """
            UPDATE servicos
            SET preco = COALESCE(preco, preco_fortaleza_comercial, 0)
            """
        )
    )

