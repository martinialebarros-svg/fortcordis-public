"""Move o marcador de urgencia da fila de pendentes para agendamentos.urgente_laudo.

A maioria dos agendamentos nao gera Exame/AtendimentoClinico (fluxo do
dropdown "Laudar", que cria o Laudo direto via agendamento_id) - o
marcador em exames.urgente_laudo (migration 20260816_70) so fazia
sentido para o fluxo raro de Atendimento Clinico completo. Move para
agendamentos.urgente_laudo, que existe para os dois fluxos.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260817_71"
DESCRIPTION = (
    "Adiciona agendamentos.urgente_laudo e remove exames.urgente_laudo "
    "(marcador de urgencia da fila de laudos pendentes precisa viver no "
    "agendamento, nao no exame, para cobrir o fluxo sem Atendimento Clinico)"
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


def _drop_column_if_exists(connection: Connection, table_name: str, column_name: str) -> None:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name not in columns:
        return

    connection.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {column_name}"))


def upgrade(connection: Connection, dialect: str) -> None:
    _add_column_if_missing(
        connection,
        dialect,
        "agendamentos",
        "urgente_laudo",
        postgres_type="BOOLEAN",
        sqlite_type="BOOLEAN",
        default_sql="FALSE",
    )

    inspector = inspect(connection)
    if "agendamentos" in inspector.get_table_names():
        connection.execute(
            text("UPDATE agendamentos SET urgente_laudo = FALSE WHERE urgente_laudo IS NULL")
        )
        if dialect == "postgresql":
            connection.execute(
                text("ALTER TABLE agendamentos ALTER COLUMN urgente_laudo SET NOT NULL")
            )

    _drop_column_if_exists(connection, "exames", "urgente_laudo")
