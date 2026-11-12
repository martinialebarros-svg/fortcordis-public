"""Track last WhatsApp release-notification attempt outcome per laudo."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260821_75"
DESCRIPTION = "Adiciona whatsapp_liberacao_status/_em/_erro em laudos para feedback visual de envio"


def upgrade(connection: Connection, dialect: str) -> None:
    del dialect
    inspector = inspect(connection)
    if "laudos" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("laudos")}
    if "whatsapp_liberacao_status" not in columns:
        connection.execute(text("ALTER TABLE laudos ADD COLUMN whatsapp_liberacao_status VARCHAR(20)"))
    if "whatsapp_liberacao_em" not in columns:
        connection.execute(text("ALTER TABLE laudos ADD COLUMN whatsapp_liberacao_em TIMESTAMP"))
    if "whatsapp_liberacao_erro" not in columns:
        connection.execute(text("ALTER TABLE laudos ADD COLUMN whatsapp_liberacao_erro TEXT"))
