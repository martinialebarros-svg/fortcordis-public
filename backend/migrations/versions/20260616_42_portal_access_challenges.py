"""Create portal access challenge table for tutor/clinic portal access."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260616_42"
DESCRIPTION = "Cria tabela de desafios temporarios de acesso do portal"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "portal_access_challenges" in inspector.get_table_names():
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE portal_access_challenges (
                    id SERIAL PRIMARY KEY,
                    challenge_id VARCHAR(64) NOT NULL UNIQUE,
                    actor_type VARCHAR(20) NOT NULL,
                    actor_id INTEGER NOT NULL,
                    paciente_id INTEGER NULL,
                    clinica_id INTEGER NULL,
                    responsavel_nome VARCHAR(255) NULL,
                    canal VARCHAR(20) NOT NULL,
                    contato_mascarado VARCHAR(255) NOT NULL,
                    scope_json TEXT NOT NULL DEFAULT '[]',
                    contexto_json TEXT NOT NULL DEFAULT '{}',
                    code_hash VARCHAR(64) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    expires_at TIMESTAMP NOT NULL,
                    consumed_at TIMESTAMP NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE portal_access_challenges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    challenge_id TEXT NOT NULL UNIQUE,
                    actor_type TEXT NOT NULL,
                    actor_id INTEGER NOT NULL,
                    paciente_id INTEGER,
                    clinica_id INTEGER,
                    responsavel_nome TEXT,
                    canal TEXT NOT NULL,
                    contato_mascarado TEXT NOT NULL,
                    scope_json TEXT NOT NULL DEFAULT '[]',
                    contexto_json TEXT NOT NULL DEFAULT '{}',
                    code_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    expires_at DATETIME NOT NULL,
                    consumed_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_portal_access_challenges_actor_type "
            "ON portal_access_challenges (actor_type)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_portal_access_challenges_actor_id "
            "ON portal_access_challenges (actor_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_portal_access_challenges_paciente_id "
            "ON portal_access_challenges (paciente_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_portal_access_challenges_clinica_id "
            "ON portal_access_challenges (clinica_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_portal_access_challenges_status "
            "ON portal_access_challenges (status)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_portal_access_challenges_expires_at "
            "ON portal_access_challenges (expires_at)"
        )
    )
