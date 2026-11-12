"""Registra o primeiro download do laudo pelo veterinario parceiro."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260923_90"
DESCRIPTION = "Adiciona downloaded_at aos destinos liberados para parceiros externos"


def upgrade(connection: Connection, dialect: str) -> None:
    del dialect
    inspector = inspect(connection)
    table = "portal_partner_release_targets"
    if table not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(table)}
    if "downloaded_at" not in columns:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN downloaded_at TIMESTAMP"))

    indexes = {index["name"] for index in inspect(connection).get_indexes(table)}
    index_name = "ix_portal_partner_release_targets_downloaded_at"
    if index_name not in indexes:
        connection.execute(text(f"CREATE INDEX {index_name} ON {table} (downloaded_at)"))
