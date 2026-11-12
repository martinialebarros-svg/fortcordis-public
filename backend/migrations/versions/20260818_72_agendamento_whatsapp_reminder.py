"""Adiciona colunas de controle do lembrete automatico de consulta via WhatsApp.

O lembrete (template Meta "appointmentReminder") ate agora so era enviado
manualmente pela Agenda. Um worker em background precisa de estado
persistido por agendamento para saber o que ja foi avisado e quantas vezes
tentou - nao havia nenhuma coluna equivalente.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260818_72"
DESCRIPTION = (
    "Adiciona agendamentos.whatsapp_reminder_sent_at/attempts/last_error "
    "para o worker de lembrete automatico de consulta via WhatsApp"
)


def _add_column_if_missing(
    connection: Connection,
    dialect: str,
    table_name: str,
    column_name: str,
    postgres_type: str,
    sqlite_type: str,
    default_sql: str | None = None,
) -> None:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return

    column_type = postgres_type if dialect == "postgresql" else sqlite_type
    default_clause = f" DEFAULT {default_sql}" if default_sql else ""
    connection.execute(
        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}{default_clause}")
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _add_column_if_missing(
        connection,
        dialect,
        "agendamentos",
        "whatsapp_reminder_sent_at",
        postgres_type="TIMESTAMP",
        sqlite_type="TIMESTAMP",
    )
    _add_column_if_missing(
        connection,
        dialect,
        "agendamentos",
        "whatsapp_reminder_attempts",
        postgres_type="INTEGER",
        sqlite_type="INTEGER",
        default_sql="0",
    )
    _add_column_if_missing(
        connection,
        dialect,
        "agendamentos",
        "whatsapp_reminder_last_error",
        postgres_type="TEXT",
        sqlite_type="TEXT",
    )

    inspector = inspect(connection)
    if "agendamentos" not in inspector.get_table_names():
        return

    connection.execute(
        text(
            "UPDATE agendamentos SET whatsapp_reminder_attempts = 0 "
            "WHERE whatsapp_reminder_attempts IS NULL"
        )
    )
    if dialect == "postgresql":
        connection.execute(
            text(
                "ALTER TABLE agendamentos "
                "ALTER COLUMN whatsapp_reminder_attempts SET NOT NULL"
            )
        )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agendamentos_reminder_pendentes "
            "ON agendamentos (whatsapp_reminder_sent_at, status, inicio)"
        )
    )
