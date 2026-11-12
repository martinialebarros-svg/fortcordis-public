"""Creates exam catalog and panel tables for atendimento."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260315_13"
DESCRIPTION = "Cria catalogo de exames, paineis e metadados de solicitacao"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _create_catalogo_exames(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "catalogo_exames"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE catalogo_exames (
                    id SERIAL PRIMARY KEY,
                    codigo VARCHAR(120) NOT NULL UNIQUE,
                    nome VARCHAR(255) NOT NULL,
                    categoria VARCHAR(120) NOT NULL,
                    subcategoria VARCHAR(120),
                    especie_alvo VARCHAR(255),
                    prioridade_padrao VARCHAR(50) DEFAULT 'Rotina',
                    valor_padrao DOUBLE PRECISION DEFAULT 0,
                    preparo TEXT,
                    observacoes_padrao TEXT,
                    sinonimos_json TEXT,
                    clinic_id INTEGER,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE catalogo_exames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT NOT NULL UNIQUE,
                    nome TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    subcategoria TEXT,
                    especie_alvo TEXT,
                    prioridade_padrao TEXT DEFAULT 'Rotina',
                    valor_padrao REAL DEFAULT 0,
                    preparo TEXT,
                    observacoes_padrao TEXT,
                    sinonimos_json TEXT,
                    clinic_id INTEGER,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
                """
            )
        )

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_catalogo_exames_codigo ON catalogo_exames (codigo)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_catalogo_exames_nome ON catalogo_exames (nome)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_catalogo_exames_categoria ON catalogo_exames (categoria)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_catalogo_exames_clinic_id ON catalogo_exames (clinic_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_catalogo_exames_ativo ON catalogo_exames (ativo)"))


def _create_painel_exames(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "painel_exames"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE painel_exames (
                    id SERIAL PRIMARY KEY,
                    codigo VARCHAR(120) NOT NULL UNIQUE,
                    nome VARCHAR(255) NOT NULL,
                    categoria VARCHAR(120),
                    especie_alvo VARCHAR(255),
                    observacoes TEXT,
                    clinic_id INTEGER,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE painel_exames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT NOT NULL UNIQUE,
                    nome TEXT NOT NULL,
                    categoria TEXT,
                    especie_alvo TEXT,
                    observacoes TEXT,
                    clinic_id INTEGER,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
                """
            )
        )

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_painel_exames_codigo ON painel_exames (codigo)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_painel_exames_nome ON painel_exames (nome)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_painel_exames_categoria ON painel_exames (categoria)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_painel_exames_clinic_id ON painel_exames (clinic_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_painel_exames_ativo ON painel_exames (ativo)"))


def _create_painel_exames_itens(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "painel_exames_itens"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE painel_exames_itens (
                    id SERIAL PRIMARY KEY,
                    painel_id INTEGER NOT NULL,
                    catalogo_exame_id INTEGER NOT NULL,
                    ordem INTEGER NOT NULL DEFAULT 0,
                    observacoes TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE painel_exames_itens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    painel_id INTEGER NOT NULL,
                    catalogo_exame_id INTEGER NOT NULL,
                    ordem INTEGER NOT NULL DEFAULT 0,
                    observacoes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_painel_exames_itens_painel_id ON painel_exames_itens (painel_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_painel_exames_itens_catalogo_exame_id ON painel_exames_itens (catalogo_exame_id)"))


def _add_exame_snapshot_columns(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "exames"):
        return

    columns = _column_names(connection, "exames")
    missing = {
        "catalogo_exame_id": ("INTEGER", "INTEGER"),
        "painel_exame_id": ("INTEGER", "INTEGER"),
        "painel_exame_nome": ("VARCHAR(255)", "TEXT"),
        "categoria_exame": ("VARCHAR(120)", "TEXT"),
        "preparo": ("TEXT", "TEXT"),
    }

    for column_name, (pg_type, sqlite_type) in missing.items():
        if column_name in columns:
            continue
        column_type = pg_type if dialect == "postgresql" else sqlite_type
        connection.execute(text(f"ALTER TABLE exames ADD COLUMN {column_name} {column_type}"))

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_exames_catalogo_exame_id ON exames (catalogo_exame_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_exames_painel_exame_id ON exames (painel_exame_id)"))


def upgrade(connection: Connection, dialect: str) -> None:
    _create_catalogo_exames(connection, dialect)
    _create_painel_exames(connection, dialect)
    _create_painel_exames_itens(connection, dialect)
    _add_exame_snapshot_columns(connection, dialect)
