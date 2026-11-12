"""Adiciona laudos.finalizado_em e exames.urgente_laudo."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260816_70"
DESCRIPTION = (
    "Adiciona laudos.finalizado_em (momento da 1a finalizacao) e "
    "exames.urgente_laudo (marcador manual da fila de laudos pendentes)"
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
        "laudos",
        "finalizado_em",
        postgres_type="TIMESTAMP",
        sqlite_type="DATETIME",
    )
    _add_column_if_missing(
        connection,
        dialect,
        "exames",
        "urgente_laudo",
        postgres_type="BOOLEAN",
        sqlite_type="BOOLEAN",
        default_sql="FALSE",
    )

    inspector = inspect(connection)
    if "exames" in inspector.get_table_names():
        connection.execute(
            text("UPDATE exames SET urgente_laudo = FALSE WHERE urgente_laudo IS NULL")
        )
        if dialect == "postgresql":
            connection.execute(
                text("ALTER TABLE exames ALTER COLUMN urgente_laudo SET NOT NULL")
            )

    if "laudos" in inspector.get_table_names() and dialect == "postgresql":
        # Backfill: laudos ja finalizados antes desta migration nao tem como
        # saber quando foram finalizados de fato - deixamos finalizado_em
        # nulo para eles (ficam fora do indicador de agilidade ate serem
        # editados de novo, o que e aceitavel: nao ha dado historico real
        # pra recuperar).
        pass
