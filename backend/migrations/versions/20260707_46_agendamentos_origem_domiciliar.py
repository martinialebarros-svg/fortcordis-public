"""Add domiciliary-origin fields to agendamentos."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260707_46"
DESCRIPTION = "Adiciona tutor_id e origem_atendimento em agendamentos"

TARGET_TABLE = "agendamentos"
NEW_COLUMNS = {
    "tutor_id": 'ALTER TABLE agendamentos ADD COLUMN tutor_id INTEGER',
    "origem_atendimento": "ALTER TABLE agendamentos ADD COLUMN origem_atendimento VARCHAR(32) DEFAULT 'clinica_parceira'",
}


def _backfill_tutor_id(connection: Connection) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if TARGET_TABLE not in tables or "pacientes" not in tables:
        return

    agendamento_columns = {column["name"] for column in inspector.get_columns(TARGET_TABLE)}
    paciente_columns = {column["name"] for column in inspector.get_columns("pacientes")}
    if "tutor_id" not in agendamento_columns or "tutor_id" not in paciente_columns:
        return

    connection.execute(
        text(
            """
            UPDATE agendamentos
            SET tutor_id = (
                SELECT pacientes.tutor_id
                FROM pacientes
                WHERE pacientes.id = agendamentos.paciente_id
            )
            WHERE (tutor_id IS NULL OR tutor_id = 0)
              AND paciente_id IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM pacientes
                  WHERE pacientes.id = agendamentos.paciente_id
                    AND pacientes.tutor_id IS NOT NULL
              )
            """
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if TARGET_TABLE not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(TARGET_TABLE)}
    for column_name, sql in NEW_COLUMNS.items():
        if column_name in existing_columns:
            continue
        connection.execute(text(sql))

    _backfill_tutor_id(connection)
    connection.execute(
        text(
            "UPDATE agendamentos SET origem_atendimento = 'clinica_parceira' "
            "WHERE origem_atendimento IS NULL OR TRIM(origem_atendimento) = ''"
        )
    )
