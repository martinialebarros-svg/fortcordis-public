"""Persists idempotent WhatsApp reservation responses."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260811_66"
DESCRIPTION = "Cria respostas idempotentes dos botoes de reserva do WhatsApp"


def upgrade(connection: Connection, dialect: str) -> None:
    if "whatsapp_agenda_respostas" in inspect(connection).get_table_names():
        return

    if dialect == "postgresql":
        connection.execute(text("""
            CREATE TABLE whatsapp_agenda_respostas (
                id SERIAL PRIMARY KEY,
                provider_message_id VARCHAR(160) NOT NULL UNIQUE,
                outbound_message_id VARCHAR(160),
                agendamento_id INTEGER,
                action VARCHAR(40) NOT NULL,
                from_phone VARCHAR(32) NOT NULL,
                result VARCHAR(80) NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                processed_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
    else:
        connection.execute(text("""
            CREATE TABLE whatsapp_agenda_respostas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_message_id TEXT NOT NULL UNIQUE,
                outbound_message_id TEXT,
                agendamento_id INTEGER,
                action TEXT NOT NULL,
                from_phone TEXT NOT NULL,
                result TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                processed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_whatsapp_agenda_respostas_agendamento "
        "ON whatsapp_agenda_respostas (agendamento_id, processed_at)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_whatsapp_agenda_respostas_outbound "
        "ON whatsapp_agenda_respostas (outbound_message_id)"
    ))
