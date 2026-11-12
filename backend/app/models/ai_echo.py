from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class AIEchoSession(Base):
    __tablename__ = "ai_echo_sessions"
    __table_args__ = (
        Index("ix_ai_echo_sessions_user_created", "user_id", "created_at"),
        Index("ix_ai_echo_sessions_user_status", "user_id", "status"),
        Index("ix_ai_echo_sessions_clinic_created", "clinic_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    clinic_id = Column(Integer, nullable=True, index=True)
    patient_id = Column(Integer, nullable=False, index=True)
    laudo_id = Column(Integer, nullable=False, index=True)
    status = Column(String(24), nullable=False, default="created", index=True)
    provider = Column(String(32), nullable=False)
    transcription_model = Column(String(100), nullable=False)
    structuring_model = Column(String(100), nullable=False)
    prompt_version = Column(String(40), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    last_error_code = Column(String(80), nullable=True)
    last_error_message = Column(String(500), nullable=True)
    provider_response_id = Column(String(255), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    estimated_cost = Column(Float, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIEchoAudioAsset(Base):
    __tablename__ = "ai_echo_audio_assets"
    __table_args__ = (
        Index("ix_ai_echo_audio_session_active", "session_id", "deleted_at"),
        Index("ix_ai_echo_audio_expires", "expires_at", "deleted_at"),
    )

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    storage_path = Column(Text, nullable=False)
    mime_type = Column(String(100), nullable=False)
    duration_seconds = Column(Float, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIEchoTranscript(Base):
    __tablename__ = "ai_echo_transcripts"
    __table_args__ = (Index("ix_ai_echo_transcripts_session_created", "session_id", "created_at"),)

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    raw_text = Column(Text, nullable=False)
    edited_text = Column(Text, nullable=False)
    language = Column(String(20), nullable=False, default="pt-BR")
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIEchoFieldSuggestion(Base):
    __tablename__ = "ai_echo_field_suggestions"
    __table_args__ = (
        Index("ix_ai_echo_suggestions_session_field", "session_id", "field_key"),
        Index("ix_ai_echo_suggestions_session_status", "session_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    field_key = Column(String(80), nullable=False)
    suggested_value = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    source_spans_json = Column(Text, nullable=False, default="[]")
    evidence_type = Column(String(32), nullable=False, default="fact")
    status = Column(String(24), nullable=False, default="pending", index=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIEchoMeasurement(Base):
    __tablename__ = "ai_echo_measurements"
    __table_args__ = (
        Index("ix_ai_echo_measurements_session_name", "session_id", "canonical_name"),
    )

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    canonical_name = Column(String(80), nullable=False)
    display_name = Column(String(140), nullable=False)
    numeric_value = Column(Float, nullable=True)
    raw_value = Column(String(80), nullable=True)
    unit = Column(String(40), nullable=True)
    target_field_key = Column(String(80), nullable=True)
    source_text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(String(24), nullable=False, default="pending", index=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIEchoClinicalWarning(Base):
    __tablename__ = "ai_echo_clinical_warnings"
    __table_args__ = (
        Index("ix_ai_echo_warnings_session_severity", "session_id", "severity"),
    )

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    warning_type = Column(String(80), nullable=False)
    severity = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    related_fields_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIEchoFeedback(Base):
    __tablename__ = "ai_echo_feedback"
    __table_args__ = (Index("ix_ai_echo_feedback_session_created", "session_id", "created_at"),)

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    field_key = Column(String(80), nullable=True)
    original_suggestion = Column(Text, nullable=True)
    final_text = Column(Text, nullable=True)
    feedback_type = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIEchoVocabulary(Base):
    __tablename__ = "ai_echo_vocabulary"
    __table_args__ = (
        Index(
            "ix_ai_echo_vocabulary_user_spoken",
            "user_id",
            "spoken_form",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    clinic_id = Column(Integer, nullable=True, index=True)
    spoken_form = Column(String(180), nullable=False)
    canonical_form = Column(String(180), nullable=False)
    category = Column(String(60), nullable=False, default="clinical")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIEchoPhrasePreference(Base):
    __tablename__ = "ai_echo_phrase_preferences"
    __table_args__ = (
        Index("ix_ai_echo_phrases_user_field_active", "user_id", "field_key", "active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    clinic_id = Column(Integer, nullable=True, index=True)
    field_key = Column(String(80), nullable=False)
    phrase_text = Column(Text, nullable=False)
    tags_json = Column(Text, nullable=False, default="[]")
    active = Column(Boolean, nullable=False, default=True)
    usage_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIEchoApplication(Base):
    __tablename__ = "ai_echo_applications"
    __table_args__ = (Index("ix_ai_echo_applications_session_created", "session_id", "created_at"),)

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    mode = Column(String(24), nullable=False)
    accepted_suggestion_ids_json = Column(Text, nullable=False, default="[]")
    accepted_measurement_ids_json = Column(Text, nullable=False, default="[]")
    previous_form_snapshot_json = Column(Text, nullable=False)
    applied_patch_json = Column(Text, nullable=False)
    report_persisted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
