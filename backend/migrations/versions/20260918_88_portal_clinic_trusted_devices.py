"""Computador da recepcao conectado ao portal em modo laudos, sem senha."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260918_88"
DESCRIPTION = "Cria portal_clinic_trusted_devices para a confianca de dispositivo da recepcao"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "portal_clinic_trusted_devices" not in inspector.get_table_names():
        connection.execute(
            text(
                """
                CREATE TABLE portal_clinic_trusted_devices (
                    id SERIAL PRIMARY KEY,
                    clinica_id INTEGER NOT NULL,
                    refresh_token_hash VARCHAR(64) NOT NULL,
                    device_label VARCHAR(120),
                    user_agent_hash VARCHAR(64),
                    origin VARCHAR(20) NOT NULL DEFAULT 'exam_link',
                    origin_exam_link_id INTEGER,
                    scope_json TEXT NOT NULL DEFAULT '[]',
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    expires_at TIMESTAMP NOT NULL,
                    last_seen_at TIMESTAMP,
                    revoked_at TIMESTAMP,
                    revoked_reason VARCHAR(255),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
                if dialect == "postgresql"
                else """
                CREATE TABLE portal_clinic_trusted_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clinica_id INTEGER NOT NULL,
                    refresh_token_hash VARCHAR(64) NOT NULL,
                    device_label VARCHAR(120),
                    user_agent_hash VARCHAR(64),
                    origin VARCHAR(20) NOT NULL DEFAULT 'exam_link',
                    origin_exam_link_id INTEGER,
                    scope_json TEXT NOT NULL DEFAULT '[]',
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    expires_at TIMESTAMP NOT NULL,
                    last_seen_at TIMESTAMP,
                    revoked_at TIMESTAMP,
                    revoked_reason VARCHAR(255),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    inspector = inspect(connection)
    indexes = {index["name"] for index in inspector.get_indexes("portal_clinic_trusted_devices")}
    if "ix_portal_clinic_trusted_devices_refresh_token_hash" not in indexes:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX ix_portal_clinic_trusted_devices_refresh_token_hash "
                "ON portal_clinic_trusted_devices (refresh_token_hash)"
            )
        )
    if "ix_portal_clinic_trusted_devices_clinica_id" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_clinic_trusted_devices_clinica_id "
                "ON portal_clinic_trusted_devices (clinica_id)"
            )
        )
    if "ix_portal_clinic_trusted_devices_status" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_clinic_trusted_devices_status "
                "ON portal_clinic_trusted_devices (status)"
            )
        )
    if "ix_portal_clinic_trusted_devices_expires_at" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_clinic_trusted_devices_expires_at "
                "ON portal_clinic_trusted_devices (expires_at)"
            )
        )
    if "ix_portal_clinic_trusted_devices_origin_exam_link_id" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_portal_clinic_trusted_devices_origin_exam_link_id "
                "ON portal_clinic_trusted_devices (origin_exam_link_id)"
            )
        )
