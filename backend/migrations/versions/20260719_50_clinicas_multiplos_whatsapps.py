"""Add multiple WhatsApp destinations to clinics."""
from __future__ import annotations

import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260719_50"
DESCRIPTION = "Adiciona lista de numeros WhatsApp ao cadastro de clinicas"

TARGET_TABLE = "clinicas"
COLUMN_NAME = "whatsapps"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if TARGET_TABLE not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(TARGET_TABLE)}
    if COLUMN_NAME not in existing_columns:
        if dialect == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE clinicas "
                    "ADD COLUMN whatsapps JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
            )
        else:
            connection.execute(
                text(
                    "ALTER TABLE clinicas "
                    "ADD COLUMN whatsapps JSON NOT NULL DEFAULT '[]'"
                )
            )

    if dialect == "postgresql":
        connection.execute(
            text(
                "UPDATE clinicas "
                "SET whatsapps = jsonb_build_array(telefone) "
                "WHERE COALESCE(BTRIM(telefone), '') <> '' "
                "AND whatsapps = '[]'::jsonb"
            )
        )
    else:
        rows = connection.execute(
            text(
                "SELECT id, telefone FROM clinicas "
                "WHERE telefone IS NOT NULL AND TRIM(telefone) <> ''"
            )
        ).fetchall()
        for row in rows:
            connection.execute(
                text(
                    "UPDATE clinicas SET whatsapps = :payload "
                    "WHERE id = :clinica_id AND whatsapps = '[]'"
                ),
                {
                    "payload": json.dumps([str(row.telefone).strip()], ensure_ascii=False),
                    "clinica_id": row.id,
                },
            )
