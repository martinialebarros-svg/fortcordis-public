"""Adds clinic-specific service pricing overrides."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260226_12"
DESCRIPTION = "Cria tabela de preco por servico para clinica"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _create_table(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "precos_servicos_clinica"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE precos_servicos_clinica (
                    id SERIAL PRIMARY KEY,
                    clinica_id INTEGER NOT NULL,
                    servico_id INTEGER NOT NULL,
                    preco_comercial NUMERIC(10,2) NULL,
                    preco_plantao NUMERIC(10,2) NULL,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NULL
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE precos_servicos_clinica (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clinica_id INTEGER NOT NULL,
                    servico_id INTEGER NOT NULL,
                    preco_comercial NUMERIC(10,2),
                    preco_plantao NUMERIC(10,2),
                    ativo INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NULL
                )
                """
            )
        )


def _ensure_columns(connection: Connection) -> None:
    columns = _column_names(connection, "precos_servicos_clinica")
    statements = {
        "preco_comercial": "ALTER TABLE precos_servicos_clinica ADD COLUMN preco_comercial NUMERIC(10,2)",
        "preco_plantao": "ALTER TABLE precos_servicos_clinica ADD COLUMN preco_plantao NUMERIC(10,2)",
        "ativo": "ALTER TABLE precos_servicos_clinica ADD COLUMN ativo INTEGER DEFAULT 1",
        "created_at": "ALTER TABLE precos_servicos_clinica ADD COLUMN created_at DATETIME",
        "updated_at": "ALTER TABLE precos_servicos_clinica ADD COLUMN updated_at DATETIME",
    }

    for column_name, sql in statements.items():
        if column_name not in columns:
            connection.execute(text(sql))


def _ensure_indexes(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_precos_servicos_clinica ON precos_servicos_clinica (clinica_id, servico_id)"
        )
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_precos_servicos_clinica_clinica_id ON precos_servicos_clinica (clinica_id)")
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_precos_servicos_clinica_servico_id ON precos_servicos_clinica (servico_id)")
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_precos_servicos_clinica_ativo ON precos_servicos_clinica (ativo)")
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _create_table(connection, dialect)
    if _table_exists(connection, "precos_servicos_clinica"):
        _ensure_columns(connection)
        _ensure_indexes(connection)
