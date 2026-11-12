"""Link direto por exame para a clinica abrir o laudo sem conta nem senha."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260918_87"
DESCRIPTION = "Cria portal_clinic_exam_links para o link de laudo enviado no WhatsApp da clinica"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "portal_clinic_exam_links" not in inspector.get_table_names():
        connection.execute(
            text(
                """
                CREATE TABLE portal_clinic_exam_links (
                    id SERIAL PRIMARY KEY,
                    token_hash VARCHAR(64) NOT NULL,
                    token_nonce VARCHAR(32) NOT NULL,
                    exame_id INTEGER NOT NULL,
                    laudo_id INTEGER,
                    clinica_id INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_by_user_id INTEGER,
                    delivery_channel VARCHAR(20) NOT NULL DEFAULT 'whatsapp',
                    delivery_target_masked VARCHAR(255),
                    delivered_at TIMESTAMP,
                    first_opened_at TIMESTAMP,
                    last_opened_at TIMESTAMP,
                    open_count INTEGER NOT NULL DEFAULT 0,
                    revoked_at TIMESTAMP,
                    revoked_reason VARCHAR(255),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
                if dialect == "postgresql"
                else """
                CREATE TABLE portal_clinic_exam_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_hash VARCHAR(64) NOT NULL,
                    token_nonce VARCHAR(32) NOT NULL,
                    exame_id INTEGER NOT NULL,
                    laudo_id INTEGER,
                    clinica_id INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_by_user_id INTEGER,
                    delivery_channel VARCHAR(20) NOT NULL DEFAULT 'whatsapp',
                    delivery_target_masked VARCHAR(255),
                    delivered_at TIMESTAMP,
                    first_opened_at TIMESTAMP,
                    last_opened_at TIMESTAMP,
                    open_count INTEGER NOT NULL DEFAULT 0,
                    revoked_at TIMESTAMP,
                    revoked_reason VARCHAR(255),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    inspector = inspect(connection)
    indexes = {index["name"] for index in inspector.get_indexes("portal_clinic_exam_links")}
    if "ix_portal_clinic_exam_links_token_hash" not in indexes:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX ix_portal_clinic_exam_links_token_hash "
                "ON portal_clinic_exam_links (token_hash)"
            )
        )
    if "ix_portal_clinic_exam_links_exame_id" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_clinic_exam_links_exame_id "
                "ON portal_clinic_exam_links (exame_id)"
            )
        )
    if "ix_portal_clinic_exam_links_clinica_id" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_clinic_exam_links_clinica_id "
                "ON portal_clinic_exam_links (clinica_id)"
            )
        )
    if "ix_portal_clinic_exam_links_status" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_clinic_exam_links_status "
                "ON portal_clinic_exam_links (status)"
            )
        )
