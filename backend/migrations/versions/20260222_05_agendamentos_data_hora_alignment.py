"""Aligns legacy `agendamentos` date/hour columns used by agenda filters."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260222_05"
DESCRIPTION = "Alinha colunas data/hora de agendamentos com backfill a partir de inicio"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _ensure_column(connection: Connection, table_name: str, column_name: str) -> None:
    columns = _column_map(connection, table_name)
    if column_name in columns:
        return
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT"))


def _upgrade_postgres(connection: Connection) -> None:
    connection.execute(
        text(
            """
            UPDATE agendamentos
            SET
                data = COALESCE(data, SUBSTRING(inicio::text FROM 1 FOR 10)),
                hora = COALESCE(hora, SUBSTRING(inicio::text FROM 12 FOR 5))
            WHERE inicio IS NOT NULL
              AND (data IS NULL OR hora IS NULL)
            """
        )
    )


def _upgrade_sqlite(connection: Connection) -> None:
    connection.execute(
        text(
            """
            UPDATE agendamentos
            SET
                data = COALESCE(data, substr(CAST(inicio AS TEXT), 1, 10)),
                hora = COALESCE(hora, substr(CAST(inicio AS TEXT), 12, 5))
            WHERE inicio IS NOT NULL
              AND (data IS NULL OR hora IS NULL)
            """
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "agendamentos" not in inspector.get_table_names():
        return

    for column_name in ("data", "hora", "paciente", "tutor", "telefone", "servico", "clinica"):
        _ensure_column(connection, "agendamentos", column_name)

    if dialect == "postgresql":
        _upgrade_postgres(connection)
    elif dialect == "sqlite":
        _upgrade_sqlite(connection)
    else:
        _upgrade_sqlite(connection)

