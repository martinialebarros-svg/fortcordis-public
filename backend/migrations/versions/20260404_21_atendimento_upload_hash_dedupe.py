"""Add hash support for atendimento upload deduplication."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260404_21"
DESCRIPTION = "Adiciona arquivo_hash em anexos_atendimentos para dedupe de upload"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "anexos_atendimentos"):
        return

    columns = _column_names(connection, "anexos_atendimentos")
    if "arquivo_hash" not in columns:
        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE anexos_atendimentos ADD COLUMN arquivo_hash VARCHAR(64)"))
        else:
            connection.execute(text("ALTER TABLE anexos_atendimentos ADD COLUMN arquivo_hash TEXT"))

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_anexos_atendimentos_upload_dedupe "
            "ON anexos_atendimentos (atendimento_id, exame_id, arquivo_hash, origem)"
        )
    )
