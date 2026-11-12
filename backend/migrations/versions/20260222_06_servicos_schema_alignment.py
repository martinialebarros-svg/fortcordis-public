"""Aligns legacy stage schema for `servicos` with current model usage."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260222_06"
DESCRIPTION = "Alinha schema legado de servicos (precos por regiao e ativo boolean)"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _add_missing_columns(connection: Connection, dialect: str, columns: dict) -> None:
    if dialect == "postgresql":
        created_at_sql = "ALTER TABLE servicos ADD COLUMN created_at TIMESTAMP DEFAULT NOW()"
        updated_at_sql = "ALTER TABLE servicos ADD COLUMN updated_at TIMESTAMP"
        ativo_sql = "ALTER TABLE servicos ADD COLUMN ativo BOOLEAN DEFAULT true"
    else:
        created_at_sql = "ALTER TABLE servicos ADD COLUMN created_at DATETIME"
        updated_at_sql = "ALTER TABLE servicos ADD COLUMN updated_at DATETIME"
        ativo_sql = "ALTER TABLE servicos ADD COLUMN ativo INTEGER DEFAULT 1"

    add_statements = {
        "duracao_minutos": "ALTER TABLE servicos ADD COLUMN duracao_minutos INTEGER",
        "ativo": ativo_sql,
        "created_at": created_at_sql,
        "updated_at": updated_at_sql,
        "preco_fortaleza_comercial": (
            "ALTER TABLE servicos ADD COLUMN preco_fortaleza_comercial NUMERIC(10,2) DEFAULT 0"
        ),
        "preco_fortaleza_plantao": (
            "ALTER TABLE servicos ADD COLUMN preco_fortaleza_plantao NUMERIC(10,2) DEFAULT 0"
        ),
        "preco_rm_comercial": (
            "ALTER TABLE servicos ADD COLUMN preco_rm_comercial NUMERIC(10,2) DEFAULT 0"
        ),
        "preco_rm_plantao": (
            "ALTER TABLE servicos ADD COLUMN preco_rm_plantao NUMERIC(10,2) DEFAULT 0"
        ),
        "preco_domiciliar_comercial": (
            "ALTER TABLE servicos ADD COLUMN preco_domiciliar_comercial NUMERIC(10,2) DEFAULT 0"
        ),
        "preco_domiciliar_plantao": (
            "ALTER TABLE servicos ADD COLUMN preco_domiciliar_plantao NUMERIC(10,2) DEFAULT 0"
        ),
    }

    for column_name, sql in add_statements.items():
        if column_name not in columns:
            connection.execute(text(sql))


def _normalize_ativo_postgres(connection: Connection, columns: dict) -> None:
    if "ativo" not in columns:
        return

    data_type = str(columns["ativo"]["type"]).lower()
    if "boolean" in data_type:
        return

    connection.execute(text("ALTER TABLE servicos ALTER COLUMN ativo DROP DEFAULT"))
    connection.execute(
        text(
            """
            ALTER TABLE servicos
            ALTER COLUMN ativo TYPE boolean
            USING CASE
                WHEN ativo IS NULL THEN false
                WHEN ativo::text IN ('1', 't', 'true', 'TRUE') THEN true
                ELSE false
            END
            """
        )
    )
    connection.execute(text("ALTER TABLE servicos ALTER COLUMN ativo SET DEFAULT true"))
    connection.execute(text("UPDATE servicos SET ativo = true WHERE ativo IS NULL"))
    connection.execute(text("ALTER TABLE servicos ALTER COLUMN ativo SET NOT NULL"))


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "servicos" not in inspector.get_table_names():
        return

    columns = _column_map(connection, "servicos")
    _add_missing_columns(connection, dialect, columns)

    if dialect == "postgresql":
        columns = _column_map(connection, "servicos")
        _normalize_ativo_postgres(connection, columns)

