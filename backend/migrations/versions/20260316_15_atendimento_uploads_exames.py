"""Adds upload metadata for atendimento attachments and exam result workflow."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260316_15"
DESCRIPTION = "Adiciona upload real de anexos e vinculo por exame no atendimento"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _ensure_anexo_upload_columns(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "anexos_atendimentos"):
        return

    columns = _column_names(connection, "anexos_atendimentos")
    missing = {
        "exame_id": ("INTEGER", "INTEGER"),
        "caminho_arquivo": ("VARCHAR(500)", "TEXT"),
        "origem": ("VARCHAR(30) NOT NULL DEFAULT 'externo'", "TEXT NOT NULL DEFAULT 'externo'"),
    }

    for column_name, (pg_type, sqlite_type) in missing.items():
        if column_name in columns:
            continue
        connection.execute(
            text(
                f"ALTER TABLE anexos_atendimentos "
                f"ADD COLUMN {column_name} {pg_type if dialect == 'postgresql' else sqlite_type}"
            )
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_anexos_atendimentos_exame_id "
            "ON anexos_atendimentos (exame_id)"
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _ensure_anexo_upload_columns(connection, dialect)
