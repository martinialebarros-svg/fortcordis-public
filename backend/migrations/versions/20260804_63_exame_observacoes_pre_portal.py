"""Preserve exam observacoes text across portal release/revoke."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260804_63"
DESCRIPTION = "Adiciona observacoes_pre_portal em exames para restaurar o texto original ao revogar liberacao no portal"


def upgrade(connection: Connection, dialect: str) -> None:
    del dialect
    inspector = inspect(connection)
    if "exames" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("exames")}
    if "observacoes_pre_portal" not in columns:
        connection.execute(text("ALTER TABLE exames ADD COLUMN observacoes_pre_portal TEXT"))
