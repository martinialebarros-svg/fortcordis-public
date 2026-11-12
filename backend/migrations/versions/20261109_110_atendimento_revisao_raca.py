"""Persist explicit breed-only veterinary reviews outside source readings."""
from sqlalchemy import inspect, text

VERSION = "20261109_110"
DESCRIPTION = "Revisao veterinaria de raca pendente nos lotes privados do atendimento"


def upgrade(connection, dialect):
    table = "atendimento_assistente_lotes"
    columns = {column["name"] for column in inspect(connection).get_columns(table)}
    if "revisoes_identidade_json" not in columns:
        connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN revisoes_identidade_json TEXT'))
    if dialect == "postgresql":
        connection.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        connection.execute(text(f'REVOKE ALL ON "{table}" FROM PUBLIC'))
        for role in ("anon", "authenticated"):
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                connection.execute(text(f'REVOKE ALL ON "{table}" FROM "{role}"'))
