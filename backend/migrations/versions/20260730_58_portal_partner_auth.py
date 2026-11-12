"""Create partner portal auth tables for veterinario partner access."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260730_58"
DESCRIPTION = "Cria tabelas de convite, conta e sessao para parceiro externo do portal"


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _create_table(connection: Connection, dialect: str, *, name: str, postgresql_sql: str, sqlite_sql: str) -> None:
    inspector = inspect(connection)
    if _table_exists(inspector, name):
        return
    connection.execute(text(postgresql_sql if dialect == "postgresql" else sqlite_sql))


def upgrade(connection: Connection, dialect: str) -> None:
    _create_table(
        connection,
        dialect,
        name="portal_partner_invites",
        postgresql_sql="""
            CREATE TABLE portal_partner_invites (
                id SERIAL PRIMARY KEY,
                partner_id INTEGER NOT NULL,
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
            CREATE TABLE portal_partner_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                delivery_channel TEXT NOT NULL DEFAULT 'whatsapp',
                delivery_target_masked TEXT NULL,
                delivered_at DATETIME NULL,
                expires_at DATETIME NOT NULL,
                used_at DATETIME NULL,
                revoked_at DATETIME NULL,
                created_by_user_id INTEGER NULL,
                contexto_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_partner_accounts",
        postgresql_sql="""
            CREATE TABLE portal_partner_accounts (
                id SERIAL PRIMARY KEY,
                partner_id INTEGER NOT NULL,
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
            CREATE TABLE portal_partner_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER NOT NULL,
                email_normalized TEXT NOT NULL UNIQUE,
                responsavel_nome TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                email_verified_at DATETIME NULL,
                status TEXT NOT NULL DEFAULT 'pending_verification',
                activated_at DATETIME NULL,
                last_login_at DATETIME NULL,
                password_changed_at DATETIME NULL,
                force_mfa_on_next_login BOOLEAN NOT NULL DEFAULT 0,
                revoked_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_partner_sessions",
        postgresql_sql="""
            CREATE TABLE portal_partner_sessions (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                partner_id INTEGER NOT NULL,
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
            CREATE TABLE portal_partner_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                partner_id INTEGER NOT NULL,
                refresh_token_hash TEXT NOT NULL UNIQUE,
                device_label TEXT NULL,
                user_agent_hash TEXT NULL,
                trusted_until DATETIME NOT NULL,
                last_seen_at DATETIME NULL,
                revoked_at DATETIME NULL,
                revoked_reason TEXT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_partner_password_reset_tokens",
        postgresql_sql="""
            CREATE TABLE portal_partner_password_reset_tokens (
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
            CREATE TABLE portal_partner_password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                used_at DATETIME NULL,
                revoked_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_partner_auth_challenges",
        postgresql_sql="""
            CREATE TABLE portal_partner_auth_challenges (
                id SERIAL PRIMARY KEY,
                challenge_id VARCHAR(64) NOT NULL UNIQUE,
                account_id INTEGER NOT NULL,
                partner_id INTEGER NOT NULL,
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
            CREATE TABLE portal_partner_auth_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_id TEXT NOT NULL UNIQUE,
                account_id INTEGER NOT NULL,
                partner_id INTEGER NOT NULL,
                challenge_type TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                expires_at DATETIME NOT NULL,
                consumed_at DATETIME NULL,
                contexto_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
    )

    indexes = [
        ("ix_portal_partner_invites_partner_id", "portal_partner_invites", "partner_id"),
        ("ix_portal_partner_invites_token_hash", "portal_partner_invites", "token_hash"),
        ("ix_portal_partner_invites_status", "portal_partner_invites", "status"),
        ("ix_portal_partner_invites_expires_at", "portal_partner_invites", "expires_at"),
        ("ix_portal_partner_accounts_partner_id", "portal_partner_accounts", "partner_id"),
        ("ix_portal_partner_accounts_email_normalized", "portal_partner_accounts", "email_normalized"),
        ("ix_portal_partner_accounts_status", "portal_partner_accounts", "status"),
        ("ix_portal_partner_sessions_account_id", "portal_partner_sessions", "account_id"),
        ("ix_portal_partner_sessions_partner_id", "portal_partner_sessions", "partner_id"),
        ("ix_portal_partner_sessions_refresh_token_hash", "portal_partner_sessions", "refresh_token_hash"),
        ("ix_portal_partner_sessions_trusted_until", "portal_partner_sessions", "trusted_until"),
        ("ix_portal_partner_sessions_status", "portal_partner_sessions", "status"),
        ("ix_portal_partner_password_reset_tokens_account_id", "portal_partner_password_reset_tokens", "account_id"),
        ("ix_portal_partner_password_reset_tokens_token_hash", "portal_partner_password_reset_tokens", "token_hash"),
        ("ix_portal_partner_password_reset_tokens_expires_at", "portal_partner_password_reset_tokens", "expires_at"),
        ("ix_portal_partner_auth_challenges_challenge_id", "portal_partner_auth_challenges", "challenge_id"),
        ("ix_portal_partner_auth_challenges_account_id", "portal_partner_auth_challenges", "account_id"),
        ("ix_portal_partner_auth_challenges_partner_id", "portal_partner_auth_challenges", "partner_id"),
        ("ix_portal_partner_auth_challenges_challenge_type", "portal_partner_auth_challenges", "challenge_type"),
        ("ix_portal_partner_auth_challenges_status", "portal_partner_auth_challenges", "status"),
        ("ix_portal_partner_auth_challenges_expires_at", "portal_partner_auth_challenges", "expires_at"),
    ]
    for index_name, table_name, column_name in indexes:
        connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"))
