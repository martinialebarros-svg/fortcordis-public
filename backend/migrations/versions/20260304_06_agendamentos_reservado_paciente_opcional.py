"""Allow reserved appointments without paciente_id."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260304_06"
DESCRIPTION = "Permite salvar status Reservado sem paciente (paciente_id opcional)"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "agendamentos" not in inspector.get_table_names():
        return

    columns = {column["name"]: column for column in inspector.get_columns("agendamentos")}
    paciente_col = columns.get("paciente_id")
    if not paciente_col:
        return

    # SQLite normalmente ja esta sem NOT NULL nessa coluna; alteracao so e necessaria no Postgres.
    is_nullable = bool(paciente_col.get("nullable", True))
    if is_nullable:
        return

    if dialect == "postgresql":
        connection.execute(text("ALTER TABLE agendamentos ALTER COLUMN paciente_id DROP NOT NULL"))
