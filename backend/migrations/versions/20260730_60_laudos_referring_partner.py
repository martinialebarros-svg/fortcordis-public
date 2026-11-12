"""Add referring veterinary partner linkage to laudos."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260730_60"
DESCRIPTION = "Adiciona veterinario_parceiro_id em laudos para vinculo operacional de encaminhamento"


def upgrade(connection: Connection, dialect: str) -> None:
    del dialect
    inspector = inspect(connection)
    if "laudos" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("laudos")}
    if "veterinario_parceiro_id" not in columns:
        connection.execute(text("ALTER TABLE laudos ADD COLUMN veterinario_parceiro_id INTEGER"))

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_laudos_veterinario_parceiro_id "
            "ON laudos (veterinario_parceiro_id)"
        )
    )
