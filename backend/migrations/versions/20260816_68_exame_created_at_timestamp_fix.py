"""Corrige exames.created_at, que em bases legadas ficou como TEXT."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260816_68"
DESCRIPTION = (
    "Corrige tipo de exames.created_at (texto -> timestamp) para permitir "
    "COALESCE com data_solicitacao/data_resultado no painel do portal"
)

TABLE_NAME = "exames"
COLUMN_NAME = "created_at"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _is_datetime_like(column_meta: dict) -> bool:
    data_type = str(column_meta.get("type") or "").lower()
    return "timestamp" in data_type or "datetime" in data_type


def _upgrade_postgres(connection: Connection, columns: dict) -> None:
    column_meta = columns.get(COLUMN_NAME)
    if not column_meta or _is_datetime_like(column_meta):
        return

    # Bases legadas tem `created_at` como TEXT (drift de uma migracao antiga
    # que so adicionava a coluna quando ausente, sem nunca corrigir o tipo).
    # `exames.data_solicitacao`/`exames.data_resultado` ja sao timestamp; o
    # COALESCE entre os tres tipos gera
    # `psycopg2.errors.DatatypeMismatch: COALESCE types timestamp without
    # time zone and text cannot be matched` no painel operacional do portal
    # (`_build_clinic_operational_panel`, so no ramo de exames sem laudo).
    connection.execute(text(f"ALTER TABLE {TABLE_NAME} ALTER COLUMN {COLUMN_NAME} DROP DEFAULT"))
    connection.execute(
        text(
            f"""
            ALTER TABLE {TABLE_NAME}
            ALTER COLUMN {COLUMN_NAME} TYPE TIMESTAMP
            USING (
                CASE
                    WHEN {COLUMN_NAME} IS NULL THEN NULL
                    WHEN BTRIM({COLUMN_NAME}::text) = '' THEN NULL
                    WHEN {COLUMN_NAME}::text ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' THEN
                        REPLACE(SUBSTRING({COLUMN_NAME}::text FROM 1 FOR 19), 'T', ' ')::timestamp
                    ELSE NULL
                END
            )
            """
        )
    )
    connection.execute(text(f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = NOW() WHERE {COLUMN_NAME} IS NULL"))
    connection.execute(text(f"ALTER TABLE {TABLE_NAME} ALTER COLUMN {COLUMN_NAME} SET DEFAULT NOW()"))


def upgrade(connection: Connection, dialect: str) -> None:
    if dialect != "postgresql":
        # SQLite (dev/testes) cria a coluna com o tipo correto a partir do
        # modelo - o drift so existe em bases Postgres legadas.
        return

    inspector = inspect(connection)
    if TABLE_NAME not in inspector.get_table_names():
        return

    columns = _column_map(connection, TABLE_NAME)
    _upgrade_postgres(connection, columns)
