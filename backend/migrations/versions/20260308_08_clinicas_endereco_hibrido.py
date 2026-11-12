"""Adds hybrid-address columns for clinics and CEP learning table."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260308_08"
DESCRIPTION = "Adiciona campos de endereco hibrido nas clinicas e aprendizado de bairro por CEP"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _ensure_clinicas_columns(connection: Connection) -> None:
    if not _table_exists(connection, "clinicas"):
        return

    statements = {
        "numero": "ALTER TABLE clinicas ADD COLUMN numero VARCHAR(50)",
        "complemento": "ALTER TABLE clinicas ADD COLUMN complemento TEXT",
        "bairro": "ALTER TABLE clinicas ADD COLUMN bairro TEXT",
        "regiao_operacional": "ALTER TABLE clinicas ADD COLUMN regiao_operacional VARCHAR(50)",
        "place_id": "ALTER TABLE clinicas ADD COLUMN place_id VARCHAR(255)",
    }
    columns = _column_names(connection, "clinicas")
    for column_name, sql in statements.items():
        if column_name not in columns:
            connection.execute(text(sql))


def _create_cep_bairro_overrides(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "cep_bairro_overrides"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE cep_bairro_overrides (
                    id SERIAL PRIMARY KEY,
                    cep VARCHAR(8) NOT NULL,
                    bairro VARCHAR(255) NOT NULL,
                    cidade VARCHAR(255),
                    estado VARCHAR(10),
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE cep_bairro_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cep VARCHAR(8) NOT NULL,
                    bairro TEXT NOT NULL,
                    cidade TEXT,
                    estado TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_cep_bairro_overrides_cep "
            "ON cep_bairro_overrides (cep)"
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _ensure_clinicas_columns(connection)
    _create_cep_bairro_overrides(connection, dialect)

