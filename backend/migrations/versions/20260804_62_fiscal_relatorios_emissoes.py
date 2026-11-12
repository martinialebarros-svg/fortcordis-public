"""Add the fiscal export emission audit trail."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260804_62"
DESCRIPTION = "Cria historico auditavel de emissoes de relatorios fiscais"


def upgrade(connection: Connection, dialect: str) -> None:
    if "relatorios_fiscais_emissoes" not in inspect(connection).get_table_names():
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE relatorios_fiscais_emissoes (
                        id SERIAL PRIMARY KEY,
                        formato VARCHAR(10) NOT NULL,
                        modo VARCHAR(20) NOT NULL,
                        tipo_emissao VARCHAR(30) NOT NULL DEFAULT 'fechamento_periodo',
                        data_inicio VARCHAR(10),
                        data_fim VARCHAR(10),
                        quantidade_os INTEGER NOT NULL DEFAULT 0,
                        valor_total NUMERIC(12,2) NOT NULL DEFAULT 0,
                        clinicas_json TEXT NOT NULL DEFAULT '[]',
                        os_ids_json TEXT NOT NULL DEFAULT '[]',
                        descricao_servico TEXT,
                        arquivo_nome TEXT,
                        usuario_id INTEGER,
                        usuario_nome TEXT,
                        emitido_em TEXT NOT NULL
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE relatorios_fiscais_emissoes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        formato TEXT NOT NULL,
                        modo TEXT NOT NULL,
                        tipo_emissao TEXT NOT NULL DEFAULT 'fechamento_periodo',
                        data_inicio TEXT,
                        data_fim TEXT,
                        quantidade_os INTEGER NOT NULL DEFAULT 0,
                        valor_total REAL NOT NULL DEFAULT 0,
                        clinicas_json TEXT NOT NULL DEFAULT '[]',
                        os_ids_json TEXT NOT NULL DEFAULT '[]',
                        descricao_servico TEXT,
                        arquivo_nome TEXT,
                        usuario_id INTEGER,
                        usuario_nome TEXT,
                        emitido_em TEXT NOT NULL
                    )
                    """
                )
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_relatorios_fiscais_emissoes_emitido_em "
            "ON relatorios_fiscais_emissoes (emitido_em)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_relatorios_fiscais_emissoes_usuario_id "
            "ON relatorios_fiscais_emissoes (usuario_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_relatorios_fiscais_emissoes_tipo_emissao "
            "ON relatorios_fiscais_emissoes (tipo_emissao)"
        )
    )
