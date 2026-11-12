"""Create table auditoria_eventos for user action trail."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260303_05"
DESCRIPTION = "Cria tabela de auditoria de acoes dos usuarios"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "auditoria_eventos" in inspector.get_table_names():
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE auditoria_eventos (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NULL,
                    usuario_nome VARCHAR(255) NULL,
                    usuario_email VARCHAR(255) NULL,
                    modulo VARCHAR(80) NOT NULL,
                    entidade VARCHAR(80) NOT NULL,
                    entidade_id VARCHAR(80) NULL,
                    acao VARCHAR(80) NOT NULL,
                    descricao TEXT NULL,
                    detalhes_json TEXT NULL,
                    ip_origem VARCHAR(64) NULL,
                    rota VARCHAR(255) NULL,
                    metodo VARCHAR(10) NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE auditoria_eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER,
                    usuario_nome TEXT,
                    usuario_email TEXT,
                    modulo TEXT NOT NULL,
                    entidade TEXT NOT NULL,
                    entidade_id TEXT,
                    acao TEXT NOT NULL,
                    descricao TEXT,
                    detalhes_json TEXT,
                    ip_origem TEXT,
                    rota TEXT,
                    metodo TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_auditoria_eventos_created_at ON auditoria_eventos (created_at)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_auditoria_eventos_usuario_id ON auditoria_eventos (usuario_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_auditoria_eventos_modulo ON auditoria_eventos (modulo)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_auditoria_eventos_acao ON auditoria_eventos (acao)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_auditoria_eventos_entidade ON auditoria_eventos (entidade)"))
