"""Create agenda_formalizacao_invites table for the patient/tutor completion link."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260820_74"
DESCRIPTION = "Cria tabela de convite de link unico para formalizar reserva (paciente/tutor)"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "agenda_formalizacao_invites" not in inspector.get_table_names():
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE agenda_formalizacao_invites (
                        id SERIAL PRIMARY KEY,
                        agendamento_id INTEGER NOT NULL,
                        token_hash VARCHAR(64) NOT NULL UNIQUE,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        expires_at TIMESTAMP NOT NULL,
                        used_at TIMESTAMP NULL,
                        revoked_at TIMESTAMP NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE agenda_formalizacao_invites (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agendamento_id INTEGER NOT NULL,
                        token_hash TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL DEFAULT 'pending',
                        expires_at DATETIME NOT NULL,
                        used_at DATETIME,
                        revoked_at DATETIME,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

    indexes = [
        ("ix_agenda_formalizacao_invites_agendamento_id", "agenda_formalizacao_invites", "agendamento_id"),
        ("ix_agenda_formalizacao_invites_token_hash", "agenda_formalizacao_invites", "token_hash"),
        ("ix_agenda_formalizacao_invites_status", "agenda_formalizacao_invites", "status"),
        ("ix_agenda_formalizacao_invites_expires_at", "agenda_formalizacao_invites", "expires_at"),
    ]
    for index_name, table_name, column_name in indexes:
        connection.execute(
            text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})")
        )
