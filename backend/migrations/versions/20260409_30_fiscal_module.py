"""Adds fiscal module tables: notas_fiscais and fiscal columns in configuracoes."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260409_30"
DESCRIPTION = "Adiciona modulo fiscal: tabela notas_fiscais e colunas fiscais em configuracoes"


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    # 1. Add fiscal columns to configuracoes
    config_columns = _column_names(connection, "configuracoes")
    fiscal_cols = {
        "inscricao_municipal": "TEXT",
        "inscricao_estadual": "TEXT",
        "cnae": "TEXT",
        "regime_tributario": "INTEGER",
        "codigo_municipio_servico": "TEXT",
    }
    for col_name, col_type in fiscal_cols.items():
        if col_name not in config_columns:
            connection.execute(text(f'ALTER TABLE configuracoes ADD COLUMN "{col_name}" {col_type}'))

    # 2. Create notas_fiscais table
    inspector = inspect(connection)
    if "notas_fiscais" not in inspector.get_table_names():
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE notas_fiscais (
                        id SERIAL PRIMARY KEY,
                        numero VARCHAR(50),
                        serie VARCHAR(10) DEFAULT '1',
                        os_id INTEGER,
                        tipo_cliente VARCHAR(2) CHECK(tipo_cliente IN ('PF','PJ')),
                        cliente_nome TEXT,
                        cliente_documento TEXT,
                        cliente_endereco TEXT,
                        cliente_bairro TEXT,
                        cliente_cidade TEXT,
                        cliente_estado TEXT,
                        cliente_cep TEXT,
                        cliente_telefone TEXT,
                        cliente_email TEXT,
                        valor_servico NUMERIC(12,2) DEFAULT 0,
                        valor_desconto NUMERIC(12,2) DEFAULT 0,
                        valor_final NUMERIC(12,2) DEFAULT 0,
                        aliquota_iss DOUBLE PRECISION DEFAULT 5.0,
                        valor_iss NUMERIC(12,2) DEFAULT 0,
                        atividade_cnae TEXT,
                        descricao_servico TEXT,
                        observacoes TEXT,
                        natureza_operacao TEXT DEFAULT 'Tributacao no municipio',
                        codigo_municipio TEXT,
                        regime_tributario INTEGER,
                        formato_exportado VARCHAR(10),
                        status VARCHAR(20) DEFAULT 'rascunho',
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE notas_fiscais (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        numero TEXT,
                        serie TEXT DEFAULT '1',
                        os_id INTEGER,
                        tipo_cliente TEXT CHECK(tipo_cliente IN ('PF','PJ')),
                        cliente_nome TEXT,
                        cliente_documento TEXT,
                        cliente_endereco TEXT,
                        cliente_bairro TEXT,
                        cliente_cidade TEXT,
                        cliente_estado TEXT,
                        cliente_cep TEXT,
                        cliente_telefone TEXT,
                        cliente_email TEXT,
                        valor_servico REAL DEFAULT 0,
                        valor_desconto REAL DEFAULT 0,
                        valor_final REAL DEFAULT 0,
                        aliquota_iss REAL DEFAULT 5.0,
                        valor_iss REAL DEFAULT 0,
                        atividade_cnae TEXT,
                        descricao_servico TEXT,
                        observacoes TEXT,
                        natureza_operacao TEXT DEFAULT 'Tributacao no municipio',
                        codigo_municipio TEXT,
                        regime_tributario INTEGER,
                        formato_exportado TEXT,
                        status TEXT DEFAULT 'rascunho',
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )

        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_notas_fiscais_os_id ON notas_fiscais (os_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_notas_fiscais_status ON notas_fiscais (status)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_notas_fiscais_created_at ON notas_fiscais (created_at)")
        )
