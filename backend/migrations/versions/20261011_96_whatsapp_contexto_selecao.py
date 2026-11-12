"""Escolha explicita de cadastro por conversa, inerte ate a equipe selecionar."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20261011_96"
DESCRIPTION = "Selecao auditavel de cadastro WhatsApp e chave de contexto dos rascunhos"


def upgrade(connection: Connection, dialect: str) -> None:
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError(f"Dialeto nao suportado para selecao WhatsApp: {dialect}")
    if "whatsapp_bot_contexto_selecao" not in inspect(connection).get_table_names():
        timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "TIMESTAMP"
        connection.execute(text(f"""
            CREATE TABLE whatsapp_bot_contexto_selecao (
                wa_identity VARCHAR(30) NOT NULL PRIMARY KEY,
                match_type VARCHAR(20),
                cadastro_id INTEGER,
                versao INTEGER NOT NULL DEFAULT 1,
                atualizado_por_id INTEGER,
                updated_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT ck_whatsapp_contexto_selecao_cadastro CHECK (
                    (match_type IS NULL AND cadastro_id IS NULL) OR
                    (match_type IS NOT NULL AND match_type IN ('clinica', 'tutor') AND cadastro_id IS NOT NULL AND cadastro_id > 0)
                ),
                CONSTRAINT ck_whatsapp_contexto_selecao_versao CHECK (versao >= 1)
            )
        """))
    if "whatsapp_bot_respostas" in inspect(connection).get_table_names():
        columns = {column["name"] for column in inspect(connection).get_columns("whatsapp_bot_respostas")}
        if "contexto_chave" not in columns:
            connection.execute(text("ALTER TABLE whatsapp_bot_respostas ADD COLUMN contexto_chave VARCHAR(64) NULL"))
