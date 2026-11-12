"""Adds role permissions matrix table (module x view/edit/delete)."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260225_10"
DESCRIPTION = "Cria tabela papeis_permissoes para matriz de permissoes por papel"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "papeis_permissoes" in inspector.get_table_names():
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE papeis_permissoes (
                    id SERIAL PRIMARY KEY,
                    papel_id INTEGER NOT NULL REFERENCES papeis(id),
                    modulo VARCHAR(80) NOT NULL,
                    visualizar INTEGER NOT NULL DEFAULT 1,
                    editar INTEGER NOT NULL DEFAULT 0,
                    excluir INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_papeis_permissoes_papel_modulo UNIQUE (papel_id, modulo)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_papeis_permissoes_papel_id ON papeis_permissoes (papel_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_papeis_permissoes_modulo ON papeis_permissoes (modulo)"))
    else:
        connection.execute(
            text(
                """
                CREATE TABLE papeis_permissoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    papel_id INTEGER NOT NULL,
                    modulo TEXT NOT NULL,
                    visualizar INTEGER NOT NULL DEFAULT 1,
                    editar INTEGER NOT NULL DEFAULT 0,
                    excluir INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_papeis_permissoes_papel_modulo UNIQUE (papel_id, modulo),
                    FOREIGN KEY (papel_id) REFERENCES papeis(id)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_papeis_permissoes_papel_id ON papeis_permissoes (papel_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_papeis_permissoes_modulo ON papeis_permissoes (modulo)"))
