"""Creates configurable quick phrases for atendimento clinical notes."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260316_14"
DESCRIPTION = "Cria banco de frases rapidas do editor clinico do atendimento"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "frases_atendimento_clinico"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE frases_atendimento_clinico (
                        id SERIAL PRIMARY KEY,
                        secao VARCHAR(120) NOT NULL,
                        titulo VARCHAR(255) NOT NULL,
                        texto TEXT NOT NULL,
                        ordem INTEGER NOT NULL DEFAULT 0,
                        ativo INTEGER NOT NULL DEFAULT 1,
                        parametrizacao_origem VARCHAR(50) NOT NULL DEFAULT 'seed',
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP,
                        created_by INTEGER
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE frases_atendimento_clinico (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        secao TEXT NOT NULL,
                        titulo TEXT NOT NULL,
                        texto TEXT NOT NULL,
                        ordem INTEGER NOT NULL DEFAULT 0,
                        ativo INTEGER NOT NULL DEFAULT 1,
                        parametrizacao_origem TEXT NOT NULL DEFAULT 'seed',
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME,
                        created_by INTEGER
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_atendimento_clinico_secao "
            "ON frases_atendimento_clinico (secao)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_atendimento_clinico_titulo "
            "ON frases_atendimento_clinico (titulo)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_atendimento_clinico_ordem "
            "ON frases_atendimento_clinico (ordem)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_atendimento_clinico_ativo "
            "ON frases_atendimento_clinico (ativo)"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_frases_atendimento_clinico_secao_titulo "
            "ON frases_atendimento_clinico (secao, titulo)"
        )
    )
