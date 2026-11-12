"""Track first partner-clinic view of an exam released to the portal."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260815_67"
DESCRIPTION = "Adiciona visualizado_portal_em em exames para registrar o primeiro acesso da clinica parceira"


def upgrade(connection: Connection, dialect: str) -> None:
    del dialect
    inspector = inspect(connection)
    if "exames" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("exames")}
    if "visualizado_portal_em" not in columns:
        connection.execute(text("ALTER TABLE exames ADD COLUMN visualizado_portal_em TIMESTAMP"))
