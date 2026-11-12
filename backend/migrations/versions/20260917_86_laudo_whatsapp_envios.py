"""Ultimo resultado do aviso por destino, para o seletor saber quem ja recebeu."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260917_86"
DESCRIPTION = "Adiciona whatsapp_envios em laudos: ultimo envio por destino (clinica e cada veterinario)"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "laudos" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("laudos")}
    if "whatsapp_envios" in columns:
        return

    # JSONB no Postgres; no SQLite o tipo JSON do SQLAlchemy grava texto.
    tipo = "JSONB" if dialect == "postgresql" else "TEXT"
    connection.execute(text(f"ALTER TABLE laudos ADD COLUMN whatsapp_envios {tipo}"))
