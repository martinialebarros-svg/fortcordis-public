"""Creates exam adjustment history, mirroring prescricao_item_ajustes."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260805_64"
DESCRIPTION = "Cria historico de ajustes do exame (resultado, valor_referencia, unidade, prioridade, status, observacoes)"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "exame_ajustes"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE exame_ajustes (
                    id SERIAL PRIMARY KEY,
                    exame_id INTEGER NOT NULL,
                    atendimento_id INTEGER NOT NULL,
                    campo VARCHAR(80) NOT NULL,
                    valor_anterior TEXT,
                    valor_novo TEXT,
                    motivo TEXT,
                    responsavel_id INTEGER,
                    responsavel_nome VARCHAR(255),
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE exame_ajustes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exame_id INTEGER NOT NULL,
                    atendimento_id INTEGER NOT NULL,
                    campo TEXT NOT NULL,
                    valor_anterior TEXT,
                    valor_novo TEXT,
                    motivo TEXT,
                    responsavel_id INTEGER,
                    responsavel_nome TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_exame_ajustes_exame_id ON exame_ajustes (exame_id)")
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_exame_ajustes_atendimento_id ON exame_ajustes (atendimento_id)")
    )
