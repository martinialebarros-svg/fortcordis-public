"""Add georeference fields to tutors for domiciliary scheduling."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260707_45"
DESCRIPTION = "Adiciona latitude/longitude/place_id/endereco_normalizado em tutores"

TARGET_TABLE = "tutores"
NEW_COLUMNS = {
    "latitude": "ALTER TABLE tutores ADD COLUMN latitude FLOAT",
    "longitude": "ALTER TABLE tutores ADD COLUMN longitude FLOAT",
    "place_id": "ALTER TABLE tutores ADD COLUMN place_id TEXT",
    "endereco_normalizado": "ALTER TABLE tutores ADD COLUMN endereco_normalizado TEXT",
}


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if TARGET_TABLE not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(TARGET_TABLE)}
    for column_name, sql in NEW_COLUMNS.items():
        if column_name in existing_columns:
            continue
        connection.execute(text(sql))
