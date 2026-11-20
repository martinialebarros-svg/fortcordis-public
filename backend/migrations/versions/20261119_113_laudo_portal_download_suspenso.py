"""Permite pausar os downloads externos de um laudo durante a correção."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20261119_113"
DESCRIPTION = "Adiciona suspensão de download por laudo no portal"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if inspector.has_table("laudos") and not any(
        column["name"] == "portal_download_suspenso" for column in inspector.get_columns("laudos")
    ):
        connection.execute(text(
            "ALTER TABLE laudos ADD COLUMN portal_download_suspenso BOOLEAN NOT NULL DEFAULT FALSE"
        ))
