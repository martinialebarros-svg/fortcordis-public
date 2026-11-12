"""Add dedupe key and unique index to guard concurrent upload races."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260404_22"
DESCRIPTION = "Adiciona dedupe_key e indice unico para evitar corrida no upload de anexos"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "anexos_atendimentos"):
        return

    columns = _column_names(connection, "anexos_atendimentos")
    if "dedupe_key" not in columns:
        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE anexos_atendimentos ADD COLUMN dedupe_key VARCHAR(96)"))
        else:
            connection.execute(text("ALTER TABLE anexos_atendimentos ADD COLUMN dedupe_key TEXT"))

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                UPDATE anexos_atendimentos
                SET dedupe_key = 'exame:' || COALESCE(CAST(exame_id AS TEXT), 'none') || '|sha256:' || LOWER(arquivo_hash)
                WHERE origem = 'upload'
                  AND arquivo_hash IS NOT NULL
                  AND TRIM(COALESCE(arquivo_hash, '')) <> ''
                  AND (dedupe_key IS NULL OR TRIM(COALESCE(dedupe_key, '')) = '')
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                UPDATE anexos_atendimentos
                SET dedupe_key = 'exame:' || COALESCE(CAST(exame_id AS TEXT), 'none') || '|sha256:' || LOWER(arquivo_hash)
                WHERE origem = 'upload'
                  AND arquivo_hash IS NOT NULL
                  AND TRIM(COALESCE(arquivo_hash, '')) <> ''
                  AND (dedupe_key IS NULL OR TRIM(COALESCE(dedupe_key, '')) = '')
                """
            )
        )

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_anexos_atendimentos_upload_dedupe "
            "ON anexos_atendimentos (atendimento_id, origem, dedupe_key)"
        )
    )
