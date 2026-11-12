"""Endereço fiscal separado da localização operacional, sem backfill."""
from sqlalchemy import inspect, text

VERSION = "20261025_100"
DESCRIPTION = "Endereco fiscal das clinicas separado do endereco de rotas"


def upgrade(connection, dialect):
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError("Endereço fiscal requer SQLite ou PostgreSQL")
    if "endereco_fiscal" not in {c["name"] for c in inspect(connection).get_columns("clinicas")}:
        connection.execute(text("ALTER TABLE clinicas ADD COLUMN endereco_fiscal JSON"))
