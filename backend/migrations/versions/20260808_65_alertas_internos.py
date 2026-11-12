"""Creates alertas_internos table for explicit, persistent in-app staff notifications."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260808_65"
DESCRIPTION = "Cria tabela alertas_internos para avisos explicitos e persistentes para a equipe interna"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "alertas_internos"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE alertas_internos (
                    id SERIAL PRIMARY KEY,
                    tipo VARCHAR(80) NOT NULL,
                    nivel VARCHAR(20) NOT NULL DEFAULT 'aviso',
                    titulo VARCHAR(200) NOT NULL,
                    mensagem TEXT NOT NULL,
                    entidade_tipo VARCHAR(80),
                    entidade_id INTEGER,
                    clinica_id INTEGER,
                    lido BOOLEAN NOT NULL DEFAULT FALSE,
                    lido_por_id INTEGER,
                    lido_por_nome VARCHAR(120),
                    lido_em TIMESTAMP,
                    criado_em TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE alertas_internos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo TEXT NOT NULL,
                    nivel TEXT NOT NULL DEFAULT 'aviso',
                    titulo TEXT NOT NULL,
                    mensagem TEXT NOT NULL,
                    entidade_tipo TEXT,
                    entidade_id INTEGER,
                    clinica_id INTEGER,
                    lido BOOLEAN NOT NULL DEFAULT 0,
                    lido_por_id INTEGER,
                    lido_por_nome TEXT,
                    lido_em DATETIME,
                    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_alertas_internos_lido_criado_id "
            "ON alertas_internos (lido, criado_em, id)"
        )
    )
