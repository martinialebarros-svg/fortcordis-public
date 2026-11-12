"""Adds triagem, diagnosticos, evolucoes, anexos and alertas ao atendimento clinico."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260227_01"
DESCRIPTION = "Adiciona triagem, diagnosticos estruturados, evolucoes, anexos e alertas clinicos"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _add_triagem_columns(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "atendimentos_clinicos"):
        return

    columns = _column_names(connection, "atendimentos_clinicos")

    new_columns = {
        "peso": ("REAL", "FLOAT"),
        "temperatura": ("REAL", "FLOAT"),
        "frequencia_cardiaca": ("INTEGER", "INTEGER"),
        "frequencia_respiratoria": ("INTEGER", "INTEGER"),
        "pressao_arterial": ("VARCHAR(50)", "TEXT"),
        "saturacao_oxigenio": ("INTEGER", "INTEGER"),
        "escore_condicion_corpo": ("INTEGER", "INTEGER"),
        "mucosas": ("VARCHAR(50)", "TEXT"),
        "hidratacao": ("VARCHAR(50)", "TEXT"),
        "triagem_observacoes": ("TEXT", "TEXT"),
        "diagnostico_principal": ("TEXT", "TEXT"),
        "diagnostico_secundario": ("TEXT", "TEXT"),
        "diagnostico_diferencial": ("TEXT", "TEXT"),
        "prognostico": ("VARCHAR(50)", "TEXT"),
        "motivo_retorno": ("TEXT", "TEXT"),
        "triagem_concluida": ("INTEGER", "INTEGER"),
        "consulta_concluida": ("INTEGER", "INTEGER"),
    }

    for col_name, (pg_type, sqlite_type) in new_columns.items():
        if col_name not in columns:
            col_type = pg_type if dialect == "postgresql" else sqlite_type
            connection.execute(text(f"ALTER TABLE atendimentos_clinicos ADD COLUMN {col_name} {col_type} NULL"))

    # Update status default for new records
    connection.execute(text("UPDATE atendimentos_clinicos SET status = 'Triagem' WHERE status IS NULL OR status = ''"))


def _create_table_evolucoes(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "evolucoes_clinicas"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE evolucoes_clinicas (
                    id SERIAL PRIMARY KEY,
                    atendimento_id INTEGER NOT NULL,
                    data_evolucao TIMESTAMP NOT NULL DEFAULT NOW(),
                    descricao TEXT NOT NULL,
                    sinais_vitais TEXT,
                    responsavel_id INTEGER NULL,
                    responsavel_nome VARCHAR(255) NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE evolucoes_clinicas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    atendimento_id INTEGER NOT NULL,
                    data_evolucao DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    descricao TEXT NOT NULL,
                    sinais_vitais TEXT,
                    responsavel_id INTEGER,
                    responsavel_nome TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_evolucoes_clinicas_atendimento_id ON evolucoes_clinicas (atendimento_id)"))


def _create_table_anexos(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "anexos_atendimentos"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE anexos_atendimentos (
                    id SERIAL PRIMARY KEY,
                    atendimento_id INTEGER NOT NULL,
                    tipo VARCHAR(50) NOT NULL,
                    descricao VARCHAR(255),
                    url VARCHAR(500) NOT NULL,
                    nome_original VARCHAR(255),
                    tamanho INTEGER,
                    mime_type VARCHAR(100),
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE anexos_atendimentos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    atendimento_id INTEGER NOT NULL,
                    tipo TEXT NOT NULL,
                    descricao TEXT,
                    url TEXT NOT NULL,
                    nome_original TEXT,
                    tamanho INTEGER,
                    mime_type TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_anexos_atendimentos_atendimento_id ON anexos_atendimentos (atendimento_id)"))


def _create_table_alertas(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "alertas_clinicos"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE alertas_clinicos (
                    id SERIAL PRIMARY KEY,
                    paciente_id INTEGER NOT NULL,
                    tipo VARCHAR(50) NOT NULL,
                    titulo VARCHAR(255) NOT NULL,
                    descricao TEXT,
                    gravidade VARCHAR(20) DEFAULT 'media',
                    ativo INTEGER NOT NULL DEFAULT 1,
                    data_inicio TIMESTAMP NOT NULL DEFAULT NOW(),
                    data_fim TIMESTAMP NULL,
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
                CREATE TABLE alertas_clinicos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paciente_id INTEGER NOT NULL,
                    tipo TEXT NOT NULL,
                    titulo TEXT NOT NULL,
                    descricao TEXT,
                    gravidade TEXT DEFAULT 'media',
                    ativo INTEGER NOT NULL DEFAULT 1,
                    data_inicio DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    data_fim DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
                """
            )
        )

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_alertas_clinicos_paciente_id ON alertas_clinicos (paciente_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_alertas_clinicos_ativo ON alertas_clinicos (ativo)"))


def upgrade(connection: Connection, dialect: str) -> None:
    _add_triagem_columns(connection, dialect)
    _create_table_evolucoes(connection, dialect)
    _create_table_anexos(connection, dialect)
    _create_table_alertas(connection, dialect)
