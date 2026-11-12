"""Preferências fiscais e confirmações manuais, sem emissão ou agendamento de envio."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20261014_98"
DESCRIPTION = "Rotina fiscal por clinica e andamento manual auditavel por OS preparada"


def upgrade(connection: Connection, dialect: str) -> None:
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError(f"Dialeto não suportado para rotina fiscal: {dialect}")
    tables = set(inspect(connection).get_table_names())
    if "fiscal_rotinas_clinicas" not in tables:
        connection.execute(text("""
            CREATE TABLE fiscal_rotinas_clinicas (
                clinica_id INTEGER PRIMARY KEY REFERENCES clinicas (id),
                modo VARCHAR(20) NOT NULL,
                pagamento_depende_nf BOOLEAN NOT NULL DEFAULT FALSE,
                versao INTEGER NOT NULL DEFAULT 1,
                atualizado_em TEXT NOT NULL,
                usuario_id INTEGER,
                usuario_nome TEXT,
                CONSTRAINT ck_fiscal_rotina_modo CHECK (modo IN ('semanal', 'por_servico')),
                CONSTRAINT ck_fiscal_rotina_versao CHECK (versao > 0)
            )
        """))
    if "fiscal_andamento_eventos" not in tables:
        id_type = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        connection.execute(text(f"""
            CREATE TABLE fiscal_andamento_eventos (
                id {id_type},
                os_id INTEGER NOT NULL REFERENCES fiscal_fechamentos_os (os_id),
                versao INTEGER NOT NULL,
                etapa_anterior VARCHAR(32) NOT NULL,
                destino VARCHAR(32) NOT NULL,
                referencia_nota VARCHAR(200),
                observacao TEXT,
                chave_idempotencia VARCHAR(36) NOT NULL UNIQUE,
                fingerprint VARCHAR(64) NOT NULL,
                registrado_em TEXT NOT NULL,
                usuario_id INTEGER,
                usuario_nome TEXT,
                CONSTRAINT uq_fiscal_andamento_os_versao UNIQUE (os_id, versao),
                CONSTRAINT ck_fiscal_andamento_versao CHECK (versao > 0),
                CONSTRAINT ck_fiscal_andamento_transicao CHECK (
                    (etapa_anterior = 'preparado' AND destino = 'enviado_contador') OR
                    (etapa_anterior = 'enviado_contador' AND destino = 'nota_recebida') OR
                    (etapa_anterior = 'nota_recebida' AND destino = 'nota_encaminhada')
                )
            )
        """))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_fiscal_andamento_eventos_registrado_em ON fiscal_andamento_eventos (registrado_em)"))
    if dialect == "postgresql":
        for table in ("fiscal_rotinas_clinicas", "fiscal_andamento_eventos"):
            connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            connection.execute(text(f"REVOKE ALL ON TABLE {table} FROM PUBLIC"))
            for role in ("anon", "authenticated"):
                if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                    connection.execute(text(f"REVOKE ALL ON TABLE {table} FROM {role}"))
