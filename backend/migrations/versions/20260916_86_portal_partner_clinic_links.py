"""Link a partner vet to the clinics where they work, with opt-in broadcast."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260916_86"
DESCRIPTION = "Cria portal_partner_clinic_links para vincular veterinario parceiro a varias clinicas"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "portal_partner_clinic_links" not in inspector.get_table_names():
        boolean_default = "FALSE" if dialect == "postgresql" else "0"
        connection.execute(
            text(
                f"""
                CREATE TABLE portal_partner_clinic_links (
                    id SERIAL PRIMARY KEY,
                    partner_id INTEGER NOT NULL,
                    clinica_id INTEGER NOT NULL,
                    receber_todos_laudos BOOLEAN NOT NULL DEFAULT {boolean_default},
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
                if dialect == "postgresql"
                else f"""
                CREATE TABLE portal_partner_clinic_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    partner_id INTEGER NOT NULL,
                    clinica_id INTEGER NOT NULL,
                    receber_todos_laudos BOOLEAN NOT NULL DEFAULT {boolean_default},
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )

    inspector = inspect(connection)
    indexes = {index["name"] for index in inspector.get_indexes("portal_partner_clinic_links")}
    if "uq_portal_partner_clinic_link" not in indexes:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_portal_partner_clinic_link "
                "ON portal_partner_clinic_links (partner_id, clinica_id)"
            )
        )
    if "ix_portal_partner_clinic_links_partner_id" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_partner_clinic_links_partner_id "
                "ON portal_partner_clinic_links (partner_id)"
            )
        )
    if "ix_portal_partner_clinic_links_clinica_id" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_partner_clinic_links_clinica_id "
                "ON portal_partner_clinic_links (clinica_id)"
            )
        )
