"""Persist tutor complementary registration fields used by atendimento."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260517_39"
DESCRIPTION = "Adiciona campos complementares de tutor (cpf/endereco/cidade/estado)"

TARGET_TABLE = "tutores"
NEW_COLUMNS = (
    "cpf",
    "cep",
    "endereco",
    "numero",
    "complemento",
    "bairro",
    "cidade",
    "estado",
)


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if TARGET_TABLE not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(TARGET_TABLE)}
    for column_name in NEW_COLUMNS:
        if column_name in existing_columns:
            continue
        connection.execute(text(f"ALTER TABLE {TARGET_TABLE} ADD COLUMN {column_name} TEXT"))

