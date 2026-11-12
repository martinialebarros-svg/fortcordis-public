"""Pacotes informativos mensais imutáveis, com exclusividade por ordem de serviço."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20261014_97"
DESCRIPTION = "Fechamentos fiscais por competencia com pacote persistido e OS exclusiva"


def upgrade(connection: Connection, dialect: str) -> None:
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError(f"Dialeto não suportado para fechamento fiscal: {dialect}")
    tables = set(inspect(connection).get_table_names())
    if "fiscal_fechamentos" not in tables:
        id_type = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        binary_type = "BYTEA" if dialect == "postgresql" else "BLOB"
        connection.execute(text(f"""
            CREATE TABLE fiscal_fechamentos (
                id {id_type},
                competencia VARCHAR(7) NOT NULL,
                chave_idempotencia VARCHAR(36) NOT NULL UNIQUE,
                fingerprint VARCHAR(64) NOT NULL,
                data_inicio VARCHAR(10) NOT NULL,
                data_fim VARCHAR(10) NOT NULL,
                quantidade_os INTEGER NOT NULL CHECK (quantidade_os > 0),
                valor_total NUMERIC(12,2) NOT NULL,
                snapshot_json TEXT NOT NULL,
                arquivo_nome TEXT NOT NULL,
                pacote_bytes {binary_type} NOT NULL,
                checksum VARCHAR(64) NOT NULL,
                usuario_id INTEGER,
                usuario_nome TEXT,
                preparado_em TEXT NOT NULL
            )
        """))
    if "fiscal_fechamentos_os" not in tables:
        connection.execute(text("""
            CREATE TABLE fiscal_fechamentos_os (
                os_id INTEGER NOT NULL PRIMARY KEY,
                fechamento_id INTEGER NOT NULL REFERENCES fiscal_fechamentos (id)
            )
        """))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_fiscal_fechamentos_competencia ON fiscal_fechamentos (competencia)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_fiscal_fechamentos_os_fechamento_id ON fiscal_fechamentos_os (fechamento_id)"))
    if dialect == "postgresql":
        for table in ("fiscal_fechamentos", "fiscal_fechamentos_os"):
            connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            connection.execute(text(f"REVOKE ALL ON TABLE {table} FROM PUBLIC"))
            for role in ("anon", "authenticated"):
                exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}).scalar()
                if exists:
                    connection.execute(text(f"REVOKE ALL ON TABLE {table} FROM {role}"))
