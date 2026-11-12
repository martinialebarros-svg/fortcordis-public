"""Add agenda schedule/holidays columns into configuracoes."""
from __future__ import annotations

import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260301_03"
DESCRIPTION = "Adiciona agenda_semanal e agenda_feriados em configuracoes"

DEFAULT_AGENDA_SEMANAL = {
    "1": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "2": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "3": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "4": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "5": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "6": {"ativo": True, "inicio": "09:00", "fim": "13:00"},
    "7": {"ativo": False, "inicio": "09:00", "fim": "13:00"},
}


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "configuracoes"):
        return

    columns = _column_names(connection, "configuracoes")

    if "agenda_semanal" not in columns:
        connection.execute(text("ALTER TABLE configuracoes ADD COLUMN agenda_semanal TEXT"))

    if "agenda_feriados" not in columns:
        connection.execute(text("ALTER TABLE configuracoes ADD COLUMN agenda_feriados TEXT"))

    connection.execute(
        text(
            """
            UPDATE configuracoes
            SET agenda_semanal = :agenda_semanal
            WHERE agenda_semanal IS NULL OR TRIM(agenda_semanal) = ''
            """
        ),
        {"agenda_semanal": json.dumps(DEFAULT_AGENDA_SEMANAL, ensure_ascii=False)},
    )

    connection.execute(
        text(
            """
            UPDATE configuracoes
            SET agenda_feriados = :agenda_feriados
            WHERE agenda_feriados IS NULL OR TRIM(agenda_feriados) = ''
            """
        ),
        {"agenda_feriados": "[]"},
    )
