"""Add the isolated veterinary echocardiography voice-assistant persistence."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260725_56"
DESCRIPTION = "Adiciona sessoes, audio temporario, sugestoes e preferencias do assistente de eco por voz"


def _timestamp(dialect: str) -> tuple[str, str]:
    if dialect == "postgresql":
        return "TIMESTAMP WITH TIME ZONE", "NOW()"
    return "DATETIME", "CURRENT_TIMESTAMP"


def _identity(dialect: str) -> str:
    return "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


def upgrade(connection: Connection, dialect: str) -> None:
    timestamp_type, timestamp_default = _timestamp(dialect)
    identity = _identity(dialect)
    tables = set(inspect(connection).get_table_names())

    if "ai_echo_sessions" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_sessions (
                id VARCHAR(36) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                clinic_id INTEGER NULL,
                patient_id INTEGER NOT NULL,
                laudo_id INTEGER NOT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'created',
                provider VARCHAR(32) NOT NULL,
                transcription_model VARCHAR(100) NOT NULL,
                structuring_model VARCHAR(100) NOT NULL,
                prompt_version VARCHAR(40) NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error_code VARCHAR(80) NULL,
                last_error_message VARCHAR(500) NULL,
                provider_response_id VARCHAR(255) NULL,
                input_tokens INTEGER NULL,
                output_tokens INTEGER NULL,
                estimated_cost FLOAT NULL,
                completed_at {timestamp_type} NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_audio_assets" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_audio_assets (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                storage_path TEXT NOT NULL,
                mime_type VARCHAR(100) NOT NULL,
                duration_seconds FLOAT NULL,
                size_bytes INTEGER NOT NULL,
                expires_at {timestamp_type} NOT NULL,
                deleted_at {timestamp_type} NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_transcripts" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_transcripts (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                raw_text TEXT NOT NULL,
                edited_text TEXT NOT NULL,
                language VARCHAR(20) NOT NULL DEFAULT 'pt-BR',
                confidence FLOAT NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_field_suggestions" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_field_suggestions (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                field_key VARCHAR(80) NOT NULL,
                suggested_value TEXT NOT NULL,
                confidence FLOAT NOT NULL,
                source_spans_json TEXT NOT NULL DEFAULT '[]',
                evidence_type VARCHAR(32) NOT NULL DEFAULT 'fact',
                status VARCHAR(24) NOT NULL DEFAULT 'pending',
                accepted_at {timestamp_type} NULL,
                rejected_at {timestamp_type} NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_measurements" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_measurements (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                canonical_name VARCHAR(80) NOT NULL,
                display_name VARCHAR(140) NOT NULL,
                numeric_value FLOAT NULL,
                raw_value VARCHAR(80) NULL,
                unit VARCHAR(40) NULL,
                target_field_key VARCHAR(80) NULL,
                source_text TEXT NOT NULL,
                confidence FLOAT NOT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'pending',
                accepted_at {timestamp_type} NULL,
                rejected_at {timestamp_type} NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_clinical_warnings" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_clinical_warnings (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                warning_type VARCHAR(80) NOT NULL,
                severity VARCHAR(20) NOT NULL,
                message TEXT NOT NULL,
                related_fields_json TEXT NOT NULL DEFAULT '[]',
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_feedback" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_feedback (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                user_id INTEGER NOT NULL,
                field_key VARCHAR(80) NULL,
                original_suggestion TEXT NULL,
                final_text TEXT NULL,
                feedback_type VARCHAR(32) NOT NULL,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_vocabulary" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_vocabulary (
                id {identity},
                user_id INTEGER NOT NULL,
                clinic_id INTEGER NULL,
                spoken_form VARCHAR(180) NOT NULL,
                canonical_form VARCHAR(180) NOT NULL,
                category VARCHAR(60) NOT NULL DEFAULT 'clinical',
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_phrase_preferences" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_phrase_preferences (
                id {identity},
                user_id INTEGER NOT NULL,
                clinic_id INTEGER NULL,
                field_key VARCHAR(80) NOT NULL,
                phrase_text TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                active BOOLEAN NOT NULL DEFAULT TRUE,
                usage_count INTEGER NOT NULL DEFAULT 0,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default},
                updated_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    if "ai_echo_applications" not in tables:
        connection.execute(text(f"""
            CREATE TABLE ai_echo_applications (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                user_id INTEGER NOT NULL,
                mode VARCHAR(24) NOT NULL,
                accepted_suggestion_ids_json TEXT NOT NULL DEFAULT '[]',
                accepted_measurement_ids_json TEXT NOT NULL DEFAULT '[]',
                previous_form_snapshot_json TEXT NOT NULL,
                applied_patch_json TEXT NOT NULL,
                report_persisted BOOLEAN NOT NULL DEFAULT FALSE,
                created_at {timestamp_type} NOT NULL DEFAULT {timestamp_default}
            )
        """))

    indexes = (
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_sessions_user_id ON ai_echo_sessions (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_sessions_clinic_id ON ai_echo_sessions (clinic_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_sessions_patient_id ON ai_echo_sessions (patient_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_sessions_laudo_id ON ai_echo_sessions (laudo_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_sessions_status ON ai_echo_sessions (status)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_sessions_user_created ON ai_echo_sessions (user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_sessions_user_status ON ai_echo_sessions (user_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_sessions_clinic_created ON ai_echo_sessions (clinic_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_audio_assets_session_id ON ai_echo_audio_assets (session_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_audio_assets_expires_at ON ai_echo_audio_assets (expires_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_audio_session_active ON ai_echo_audio_assets (session_id, deleted_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_audio_expires ON ai_echo_audio_assets (expires_at, deleted_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_transcripts_session_id ON ai_echo_transcripts (session_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_transcripts_session_created ON ai_echo_transcripts (session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_field_suggestions_session_id ON ai_echo_field_suggestions (session_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_suggestions_session_field ON ai_echo_field_suggestions (session_id, field_key)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_suggestions_session_status ON ai_echo_field_suggestions (session_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_measurements_session_id ON ai_echo_measurements (session_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_measurements_session_name ON ai_echo_measurements (session_id, canonical_name)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_warnings_session_severity ON ai_echo_clinical_warnings (session_id, severity)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_feedback_session_created ON ai_echo_feedback (session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_feedback_user_id ON ai_echo_feedback (user_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_echo_vocabulary_user_spoken ON ai_echo_vocabulary (user_id, spoken_form)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_phrases_user_field_active ON ai_echo_phrase_preferences (user_id, field_key, active)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_applications_session_created ON ai_echo_applications (session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_echo_applications_user_id ON ai_echo_applications (user_id)",
    )
    for statement in indexes:
        connection.execute(text(statement))


def downgrade(connection: Connection, dialect: str) -> None:
    del dialect
    for table_name in (
        "ai_echo_applications",
        "ai_echo_phrase_preferences",
        "ai_echo_vocabulary",
        "ai_echo_feedback",
        "ai_echo_clinical_warnings",
        "ai_echo_measurements",
        "ai_echo_field_suggestions",
        "ai_echo_transcripts",
        "ai_echo_audio_assets",
        "ai_echo_sessions",
    ):
        connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
