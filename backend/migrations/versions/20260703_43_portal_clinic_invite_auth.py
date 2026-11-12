"""Create clinic invite/password auth tables for the portal."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260703_43"
DESCRIPTION = "Cria tabelas de convite e autenticacao persistente para clinicas do portal"


def _create_table(connection: Connection, dialect: str, *, name: str, postgresql_sql: str, sqlite_sql: str) -> None:
    inspector = inspect(connection)
    if name in inspector.get_table_names():
        return
    sql = postgresql_sql if dialect == "postgresql" else sqlite_sql
    connection.execute(text(sql))


def upgrade(connection: Connection, dialect: str) -> None:
    _create_table(
        connection,
        dialect,
        name="portal_clinic_invites",
        postgresql_sql="""
            CREATE TABLE portal_clinic_invites (
                id SERIAL PRIMARY KEY,
                clinica_id INTEGER NOT NULL,
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                delivery_channel VARCHAR(20) NOT NULL DEFAULT 'whatsapp',
                delivery_target_masked VARCHAR(255) NULL,
                delivered_at TIMESTAMP NULL,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP NULL,
                revoked_at TIMESTAMP NULL,
                created_by_user_id INTEGER NULL,
                contexto_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """,
        sqlite_sql="""
            CREATE TABLE portal_clinic_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinica_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                delivery_channel TEXT NOT NULL DEFAULT 'whatsapp',
                delivery_target_masked TEXT,
                delivered_at DATETIME,
                expires_at DATETIME NOT NULL,
                used_at DATETIME,
                revoked_at DATETIME,
                created_by_user_id INTEGER,
                contexto_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_clinic_accounts",
        postgresql_sql="""
            CREATE TABLE portal_clinic_accounts (
                id SERIAL PRIMARY KEY,
                clinica_id INTEGER NOT NULL,
                email_normalized VARCHAR(255) NOT NULL UNIQUE,
                responsavel_nome VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                email_verified_at TIMESTAMP NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'pending_verification',
                activated_at TIMESTAMP NULL,
                last_login_at TIMESTAMP NULL,
                password_changed_at TIMESTAMP NULL,
                force_mfa_on_next_login BOOLEAN NOT NULL DEFAULT FALSE,
                revoked_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NULL
            )
        """,
        sqlite_sql="""
            CREATE TABLE portal_clinic_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinica_id INTEGER NOT NULL,
                email_normalized TEXT NOT NULL UNIQUE,
                responsavel_nome TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                email_verified_at DATETIME,
                status TEXT NOT NULL DEFAULT 'pending_verification',
                activated_at DATETIME,
                last_login_at DATETIME,
                password_changed_at DATETIME,
                force_mfa_on_next_login BOOLEAN NOT NULL DEFAULT 0,
                revoked_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_clinic_sessions",
        postgresql_sql="""
            CREATE TABLE portal_clinic_sessions (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                clinica_id INTEGER NOT NULL,
                refresh_token_hash VARCHAR(64) NOT NULL UNIQUE,
                device_label VARCHAR(255) NULL,
                user_agent_hash VARCHAR(64) NULL,
                trusted_until TIMESTAMP NOT NULL,
                last_seen_at TIMESTAMP NULL,
                revoked_at TIMESTAMP NULL,
                revoked_reason VARCHAR(255) NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NULL
            )
        """,
        sqlite_sql="""
            CREATE TABLE portal_clinic_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                clinica_id INTEGER NOT NULL,
                refresh_token_hash TEXT NOT NULL UNIQUE,
                device_label TEXT,
                user_agent_hash TEXT,
                trusted_until DATETIME NOT NULL,
                last_seen_at DATETIME,
                revoked_at DATETIME,
                revoked_reason TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_password_reset_tokens",
        postgresql_sql="""
            CREATE TABLE portal_password_reset_tokens (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP NULL,
                revoked_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """,
        sqlite_sql="""
            CREATE TABLE portal_password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                used_at DATETIME,
                revoked_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_auth_challenges",
        postgresql_sql="""
            CREATE TABLE portal_auth_challenges (
                id SERIAL PRIMARY KEY,
                challenge_id VARCHAR(64) NOT NULL UNIQUE,
                account_id INTEGER NOT NULL,
                clinica_id INTEGER NOT NULL,
                challenge_type VARCHAR(40) NOT NULL,
                code_hash VARCHAR(64) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                expires_at TIMESTAMP NOT NULL,
                consumed_at TIMESTAMP NULL,
                contexto_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """,
        sqlite_sql="""
            CREATE TABLE portal_auth_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_id TEXT NOT NULL UNIQUE,
                account_id INTEGER NOT NULL,
                clinica_id INTEGER NOT NULL,
                challenge_type TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                expires_at DATETIME NOT NULL,
                consumed_at DATETIME,
                contexto_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
    )

    indexes = [
        ("ix_portal_clinic_invites_token_hash", "portal_clinic_invites", "token_hash"),
        ("ix_portal_clinic_invites_clinica_id", "portal_clinic_invites", "clinica_id"),
        ("ix_portal_clinic_invites_status", "portal_clinic_invites", "status"),
        ("ix_portal_clinic_invites_expires_at", "portal_clinic_invites", "expires_at"),
        ("ix_portal_clinic_accounts_email_normalized", "portal_clinic_accounts", "email_normalized"),
        ("ix_portal_clinic_accounts_clinica_id", "portal_clinic_accounts", "clinica_id"),
        ("ix_portal_clinic_accounts_status", "portal_clinic_accounts", "status"),
        ("ix_portal_clinic_sessions_refresh_token_hash", "portal_clinic_sessions", "refresh_token_hash"),
        ("ix_portal_clinic_sessions_account_id", "portal_clinic_sessions", "account_id"),
        ("ix_portal_clinic_sessions_clinica_id", "portal_clinic_sessions", "clinica_id"),
        ("ix_portal_clinic_sessions_trusted_until", "portal_clinic_sessions", "trusted_until"),
        ("ix_portal_clinic_sessions_status", "portal_clinic_sessions", "status"),
        ("ix_portal_password_reset_tokens_token_hash", "portal_password_reset_tokens", "token_hash"),
        ("ix_portal_password_reset_tokens_account_id", "portal_password_reset_tokens", "account_id"),
        ("ix_portal_password_reset_tokens_expires_at", "portal_password_reset_tokens", "expires_at"),
        ("ix_portal_auth_challenges_challenge_id", "portal_auth_challenges", "challenge_id"),
        ("ix_portal_auth_challenges_account_id", "portal_auth_challenges", "account_id"),
        ("ix_portal_auth_challenges_clinica_id", "portal_auth_challenges", "clinica_id"),
        ("ix_portal_auth_challenges_type", "portal_auth_challenges", "challenge_type"),
        ("ix_portal_auth_challenges_status", "portal_auth_challenges", "status"),
        ("ix_portal_auth_challenges_expires_at", "portal_auth_challenges", "expires_at"),
    ]
    for index_name, table_name, column_name in indexes:
        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON {table_name} ({column_name})"
            )
        )
