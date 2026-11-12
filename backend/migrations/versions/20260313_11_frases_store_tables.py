"""Adds versioned tables for the frases store."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260313_11"
DESCRIPTION = "Versiona as tabelas de frases qualitativas e historico"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "frases_qualitativas"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE frases_qualitativas (
                        id SERIAL PRIMARY KEY,
                        chave VARCHAR(255) NOT NULL,
                        patologia VARCHAR(255) NOT NULL,
                        grau VARCHAR(100) NOT NULL DEFAULT 'Normal',
                        valvas TEXT DEFAULT '',
                        camaras TEXT DEFAULT '',
                        funcao TEXT DEFAULT '',
                        pericardio TEXT DEFAULT '',
                        vasos TEXT DEFAULT '',
                        ad_vd TEXT DEFAULT '',
                        conclusao TEXT DEFAULT '',
                        detalhado JSONB,
                        layout VARCHAR(50) DEFAULT 'detalhado',
                        ativo INTEGER DEFAULT 1,
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
                    CREATE TABLE frases_qualitativas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chave VARCHAR(255) NOT NULL,
                        patologia VARCHAR(255) NOT NULL,
                        grau VARCHAR(100) NOT NULL DEFAULT 'Normal',
                        valvas TEXT DEFAULT '',
                        camaras TEXT DEFAULT '',
                        funcao TEXT DEFAULT '',
                        pericardio TEXT DEFAULT '',
                        vasos TEXT DEFAULT '',
                        ad_vd TEXT DEFAULT '',
                        conclusao TEXT DEFAULT '',
                        detalhado JSON,
                        layout VARCHAR(50) DEFAULT 'detalhado',
                        ativo INTEGER DEFAULT 1,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME,
                        created_by INTEGER
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_frases_qualitativas_chave "
            "ON frases_qualitativas (chave)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_qualitativas_id "
            "ON frases_qualitativas (id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_qualitativas_patologia "
            "ON frases_qualitativas (patologia)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_qualitativas_ativo "
            "ON frases_qualitativas (ativo)"
        )
    )

    if not _table_exists(connection, "frases_qualitativas_historico"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE frases_qualitativas_historico (
                        id SERIAL PRIMARY KEY,
                        frase_id INTEGER,
                        chave VARCHAR(255),
                        patologia VARCHAR(255),
                        grau VARCHAR(100),
                        conteudo JSONB,
                        acao VARCHAR(50),
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        created_by INTEGER
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE frases_qualitativas_historico (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        frase_id INTEGER,
                        chave VARCHAR(255),
                        patologia VARCHAR(255),
                        grau VARCHAR(100),
                        conteudo JSON,
                        acao VARCHAR(50),
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        created_by INTEGER
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_qualitativas_historico_id "
            "ON frases_qualitativas_historico (id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_frases_qualitativas_historico_frase_id "
            "ON frases_qualitativas_historico (frase_id)"
        )
    )
