"""Durable, default-deny Google Maps action grants and expenditure ledger."""
from sqlalchemy import text

VERSION = "20261018_99"
DESCRIPTION = "Limites e consentimento por acao para chamadas Google Maps"


def upgrade(connection, dialect):
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError("Google Maps cost control requires SQLite or PostgreSQL")
    from app.models.google_maps_cost_control import COST_TABLES

    # Deliberately no configuration seed: owner must choose explicit ceilings.
    for table in COST_TABLES:
        table.create(bind=connection, checkfirst=True)
        if dialect == "postgresql":
            connection.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
            connection.execute(text(f'REVOKE ALL ON TABLE "{table.name}" FROM PUBLIC'))
            for role in ("anon", "authenticated"):
                if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                    connection.execute(text(f'REVOKE ALL ON TABLE "{table.name}" FROM "{role}"'))
