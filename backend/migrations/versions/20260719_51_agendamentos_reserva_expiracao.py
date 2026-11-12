"""Persist reservation deadlines so expired holds stop blocking the agenda."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260719_51"
DESCRIPTION = "Adiciona prazo efetivo de expiracao para reservas da agenda"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "agendamentos" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("agendamentos")}
    if "reserva_expira_em" in columns:
        return

    column_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
    connection.execute(
        text(
            "ALTER TABLE agendamentos "
            f"ADD COLUMN reserva_expira_em {column_type} NULL"
        )
    )
