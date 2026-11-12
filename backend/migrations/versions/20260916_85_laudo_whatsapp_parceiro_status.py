"""Track last WhatsApp release-notification attempt outcome per partner vet."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260916_85"
DESCRIPTION = "Adiciona whatsapp_parceiro_status/_em/_erro em laudos para o aviso do veterinario parceiro"


def upgrade(connection: Connection, dialect: str) -> None:
    del dialect
    inspector = inspect(connection)
    if "laudos" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("laudos")}
    if "whatsapp_parceiro_status" not in columns:
        connection.execute(text("ALTER TABLE laudos ADD COLUMN whatsapp_parceiro_status VARCHAR(20)"))
    if "whatsapp_parceiro_em" not in columns:
        connection.execute(text("ALTER TABLE laudos ADD COLUMN whatsapp_parceiro_em TIMESTAMP"))
    if "whatsapp_parceiro_erro" not in columns:
        connection.execute(text("ALTER TABLE laudos ADD COLUMN whatsapp_parceiro_erro TEXT"))
