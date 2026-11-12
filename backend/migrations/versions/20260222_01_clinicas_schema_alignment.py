"""Aligns legacy stage schema for `clinicas` with current model usage."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260222_01"
DESCRIPTION = "Alinha schema legado de clinicas (colunas e tipos)"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _add_missing_columns(connection: Connection, table_name: str, columns: dict) -> None:
    add_statements = {
        "observacoes": "ALTER TABLE clinicas ADD COLUMN observacoes TEXT",
        "tabela_preco_id": "ALTER TABLE clinicas ADD COLUMN tabela_preco_id INTEGER DEFAULT 1",
        "preco_personalizado_km": (
            "ALTER TABLE clinicas ADD COLUMN preco_personalizado_km NUMERIC(10,2) DEFAULT 0"
        ),
        "preco_personalizado_base": (
            "ALTER TABLE clinicas ADD COLUMN preco_personalizado_base NUMERIC(10,2) DEFAULT 0"
        ),
        "observacoes_preco": "ALTER TABLE clinicas ADD COLUMN observacoes_preco TEXT",
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

    connection.execute(text("ALTER TABLE clinicas ALTER COLUMN ativo DROP DEFAULT"))
    connection.execute(
        text(
            """
            ALTER TABLE clinicas
            ALTER COLUMN ativo TYPE boolean
            USING CASE
                WHEN ativo IS NULL THEN false
                WHEN ativo::text IN ('1', 't', 'true', 'TRUE') THEN true
                ELSE false
            END
            """
        )
    )
    connection.execute(text("ALTER TABLE clinicas ALTER COLUMN ativo SET DEFAULT true"))
    connection.execute(text("UPDATE clinicas SET ativo = true WHERE ativo IS NULL"))
    connection.execute(text("ALTER TABLE clinicas ALTER COLUMN ativo SET NOT NULL"))


def _drop_nome_key_not_null_postgres(connection: Connection, columns: dict) -> None:
    if "nome_key" not in columns:
        return

    is_nullable = bool(columns["nome_key"].get("nullable", True))
    if not is_nullable:
        connection.execute(text("ALTER TABLE clinicas ALTER COLUMN nome_key DROP NOT NULL"))


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "clinicas" not in inspector.get_table_names():
        return

    columns = _column_map(connection, "clinicas")
    _add_missing_columns(connection, "clinicas", columns)

    if dialect == "postgresql":
        # Refresh metadata after ALTER TABLE operations.
        columns = _column_map(connection, "clinicas")
        _normalize_ativo_postgres(connection, columns)

        columns = _column_map(connection, "clinicas")
        _drop_nome_key_not_null_postgres(connection, columns)

