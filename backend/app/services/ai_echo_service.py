from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.ai_echo import (
    AIEchoApplication,
    AIEchoAudioAsset,
    AIEchoClinicalWarning,
    AIEchoFeedback,
    AIEchoFieldSuggestion,
    AIEchoMeasurement,
    AIEchoPhrasePreference,
    AIEchoSession,
    AIEchoTranscript,
    AIEchoVocabulary,
)
from app.models.laudo import Laudo
from app.models.paciente import Paciente
from app.models.user import User
from app.schemas.ai_echo import (
    EchoApplyRequest,
    EchoFeedbackRequest,
    EchoFieldKey,
    EchoFieldSuggestionOutput,
    EchoMeasurementFieldKey,
    EchoPhrasePreferenceInput,
    EchoPreferencesUpdateRequest,
)
from app.services.ai_echo_prompt import PROMPT_VERSION
from app.services.ai_echo_context import load_echo_reference_context
from app.services.ai_echo_providers import (
    AIEchoProviderError,
    StructuringResult,
    get_clinical_structuring_provider,
    get_speech_to_text_provider,
)
from app.services.ai_echo_validation import (
    build_deterministic_known_case_output,
    can_recover_normality_deterministically,
    validate_and_enrich_clinical_output,
)
from app.utils.paciente_idade import referencia_documento, idade_do_paciente
from app.utils.echo_unit_provenance import clinically_safe_echo_measurements

logger = logging.getLogger(__name__)

ALLOWED_AUDIO_TYPES = {
    "audio/m4a",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
}
ALLOWED_AUDIO_EXTENSIONS = {
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".wav",
    ".webm",
}
PROCESSABLE_STATES = {"created", "awaiting_review", "failed"}
ACTIVE_PROCESSING_STATES = {"uploading", "transcribing", "structuring"}

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-echo")
_SUBMITTED: set[tuple[str, str]] = set()
_SUBMIT_LOCK = Lock()
_CLEANUP_STOP = Event()
_CLEANUP_THREAD: Thread | None = None


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _utcnow() -> datetime:
    return datetime.utcnow()


def _is_expired(value: datetime) -> bool:
    """Compare timestamps returned by SQLite (naive) or PostgreSQL (aware)."""
    if value.tzinfo is None:
        return value < _utcnow()
    return value < datetime.now(timezone.utc)


def _sanitize_error_message(message: str) -> str:
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]+", "[credencial removida]", str(message or ""))
    sanitized = re.sub(r"https?://\S+", "[endereco removido]", sanitized)
    return sanitized[:500] or "Falha técnica no processamento."


def redact_personal_data(text: str) -> str:
    redacted = str(text or "")
    redacted = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[EMAIL REMOVIDO]",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
        "[DOCUMENTO REMOVIDO]",
        redacted,
    )
    redacted = re.sub(
        r"(?<![\d,.])(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?\d{4,5}[-\s]?\d{4}(?![\d,.])",
        "[TELEFONE REMOVIDO]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b(?:tutor(?:a)?|respons[aá]vel|paciente|telefone|whatsapp|cpf|cnpj|"
        r"endere[cç]o)\s*[:\-]?\s*[^,.;\n]{2,100}",
        "[DADO PESSOAL REMOVIDO]",
        redacted,
    )
    return redacted.strip()


def feature_config() -> dict[str, Any]:
    configured = bool(
        str(settings.AI_PROVIDER or "").strip().lower() == "openai"
        and
        str(settings.OPENAI_API_KEY or "").strip()
        and str(settings.AI_TRANSCRIPTION_MODEL or "").strip()
        and str(settings.AI_STRUCTURING_MODEL or "").strip()
    )
    return {
        "enabled": bool(settings.AI_ECHO_ASSISTANT_ENABLED and configured),
        "feature_flag_enabled": bool(settings.AI_ECHO_ASSISTANT_ENABLED),
        "provider_configured": configured,
        "max_audio_bytes": int(settings.AI_ECHO_AUDIO_MAX_BYTES),
        "max_audio_seconds": int(settings.AI_ECHO_AUDIO_MAX_SECONDS),
        "retention_hours": int(settings.AI_AUDIO_RETENTION_HOURS),
        "allowed_extensions": sorted(ALLOWED_AUDIO_EXTENSIONS),
        "manual_flow_available": True,
        "requires_explicit_application": True,
    }


def require_feature_available() -> None:
    if not settings.AI_ECHO_ASSISTANT_ENABLED:
        raise HTTPException(status_code=404, detail="Assistente de laudo por voz desativado.")
    if str(settings.AI_PROVIDER or "").strip().lower() != "openai":
        raise HTTPException(
            status_code=503,
            detail="Provedor do assistente de laudo por voz não suportado.",
        )
    if not str(settings.OPENAI_API_KEY or "").strip():
        raise HTTPException(
            status_code=503,
            detail="Assistente de laudo por voz ainda não configurado neste ambiente.",
        )
    if not str(settings.AI_TRANSCRIPTION_MODEL or "").strip() or not str(
        settings.AI_STRUCTURING_MODEL or ""
    ).strip():
        raise HTTPException(
            status_code=503,
            detail="Modelos do assistente de laudo por voz não configurados.",
        )


def _first_day_of_month(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1)


def create_session(db: Session, *, current_user: User, laudo_id: int) -> AIEchoSession:
    require_feature_available()
    laudo = (
        db.query(Laudo)
        .filter(
            Laudo.id == laudo_id,
            Laudo.tipo == "ecocardiograma",
        )
        .first()
    )
    if not laudo:
        raise HTTPException(status_code=404, detail="Ecocardiograma não encontrado.")

    monthly_limit = max(1, int(settings.AI_ECHO_MONTHLY_SESSION_LIMIT))
    used = (
        db.query(AIEchoSession)
        .filter(
            AIEchoSession.user_id == current_user.id,
            AIEchoSession.created_at >= _first_day_of_month(_utcnow()),
        )
        .count()
    )
    if used >= monthly_limit:
        raise HTTPException(
            status_code=429,
            detail="Limite mensal do assistente atingido. O preenchimento manual continua disponível.",
        )

    session = AIEchoSession(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        clinic_id=laudo.clinic_id,
        patient_id=laudo.paciente_id,
        laudo_id=laudo.id,
        status="created",
        provider=str(settings.AI_PROVIDER or "openai").strip().lower(),
        transcription_model=str(settings.AI_TRANSCRIPTION_MODEL or "").strip(),
        structuring_model=str(settings.AI_STRUCTURING_MODEL or "").strip(),
        prompt_version=PROMPT_VERSION,
        attempts=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_owned_session(db: Session, *, session_id: str, user_id: int) -> AIEchoSession:
    session = (
        db.query(AIEchoSession)
        .filter(
            AIEchoSession.id == session_id,
            AIEchoSession.user_id == user_id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Sessão de ditado não encontrada.")
    return session


def _audio_storage_dir() -> str:
    preferred = str(settings.UPLOAD_DIR or "").strip()
    if os.name == "nt" and preferred.startswith("/"):
        preferred = ""
    candidates = [
        os.path.join(preferred, "ai_echo_audio") if preferred else "",
        str(Path(__file__).resolve().parents[2] / "tmp" / "ai_echo_audio"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            os.makedirs(candidate, mode=0o700, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise RuntimeError("Não foi possível preparar o armazenamento temporário de áudio.")


def _validate_audio(
    *,
    file_name: str | None,
    content_type: str | None,
    content: bytes,
    duration_seconds: float | None,
) -> tuple[str, str]:
    safe_name = Path(str(file_name or "ditado.webm")).name
    extension = Path(safe_name).suffix.lower()
    normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS or normalized_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Formato de áudio inválido. Use webm, mp3, mp4, m4a, mpeg ou wav.",
        )
    if not content:
        raise HTTPException(status_code=422, detail="O arquivo de áudio está vazio.")
    if len(content) > int(settings.AI_ECHO_AUDIO_MAX_BYTES):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="O áudio excede o limite de tamanho configurado.",
        )
    if duration_seconds is not None:
        if duration_seconds <= 0:
            raise HTTPException(status_code=422, detail="Duração do áudio inválida.")
        if duration_seconds > int(settings.AI_ECHO_AUDIO_MAX_SECONDS):
            raise HTTPException(
                status_code=413,
                detail="O áudio excede a duração máxima configurada.",
            )
    return safe_name, normalized_type


def _remove_path(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("Falha ao remover audio temporario ai_echo path_present=true")


def store_audio(
    db: Session,
    *,
    session: AIEchoSession,
    file_name: str | None,
    content_type: str | None,
    content: bytes,
    duration_seconds: float | None,
) -> AIEchoAudioAsset:
    require_feature_available()
    safe_name, normalized_type = _validate_audio(
        file_name=file_name,
        content_type=content_type,
        content=content,
        duration_seconds=duration_seconds,
    )
    session.status = "uploading"
    session.last_error_code = None
    session.last_error_message = None
    db.commit()

    for old_asset in (
        db.query(AIEchoAudioAsset)
        .filter(
            AIEchoAudioAsset.session_id == session.id,
            AIEchoAudioAsset.deleted_at.is_(None),
        )
        .all()
    ):
        _remove_path(old_asset.storage_path)
        old_asset.deleted_at = _utcnow()

    extension = Path(safe_name).suffix.lower()
    fd, temp_path = tempfile.mkstemp(
        prefix=f"echo_{session.id[:8]}_",
        suffix=extension,
        dir=_audio_storage_dir(),
    )
    try:
        with os.fdopen(fd, "wb") as file_obj:
            file_obj.write(content)
        os.chmod(temp_path, 0o600)
    except Exception:
        _remove_path(temp_path)
        session.status = "failed"
        session.last_error_code = "audio_storage_failed"
        session.last_error_message = "Não foi possível armazenar o áudio temporariamente."
        db.commit()
        raise HTTPException(status_code=500, detail=session.last_error_message)

    asset = AIEchoAudioAsset(
        id=str(uuid.uuid4()),
        session_id=session.id,
        storage_path=temp_path,
        mime_type=normalized_type,
        duration_seconds=duration_seconds,
        size_bytes=len(content),
        expires_at=_utcnow() + timedelta(hours=max(1, int(settings.AI_AUDIO_RETENTION_HOURS))),
    )
    db.add(asset)
    session.status = "created"
    db.commit()
    db.refresh(asset)
    return asset


def delete_audio(db: Session, *, session: AIEchoSession) -> bool:
    assets = (
        db.query(AIEchoAudioAsset)
        .filter(
            AIEchoAudioAsset.session_id == session.id,
            AIEchoAudioAsset.deleted_at.is_(None),
        )
        .all()
    )
    for asset in assets:
        _remove_path(asset.storage_path)
        asset.deleted_at = _utcnow()
    db.commit()
    return bool(assets)


def _custom_vocabulary(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(AIEchoVocabulary)
        .filter(
            AIEchoVocabulary.user_id == user_id,
            AIEchoVocabulary.active.is_(True),
        )
        .order_by(AIEchoVocabulary.id.asc())
        .all()
    )
    return [
        {
            "spoken_form": row.spoken_form,
            "canonical_form": row.canonical_form,
            "category": row.category,
        }
        for row in rows
    ]


def _phrase_preferences(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(AIEchoPhrasePreference)
        .filter(
            AIEchoPhrasePreference.user_id == user_id,
            AIEchoPhrasePreference.active.is_(True),
        )
        .order_by(
            AIEchoPhrasePreference.usage_count.desc(),
            AIEchoPhrasePreference.id.asc(),
        )
        .all()
    )
    return [
        {
            "field_key": row.field_key,
            "phrase_text": row.phrase_text,
            "tags": _json_load(row.tags_json, []),
        }
        for row in rows
    ]


def _mark_failed(
    db: Session,
    session_id: str,
    error: Exception,
    *,
    processing_step: str = "provider",
) -> None:
    session = db.query(AIEchoSession).filter(AIEchoSession.id == session_id).first()
    if not session:
        return
    if isinstance(error, AIEchoProviderError):
        code = error.code
        message = str(error)
    else:
        code = f"processing_failed_{processing_step}"
        message = "Falha técnica no processamento. O laudo manual permanece disponível."
    session.status = "failed"
    session.last_error_code = code
    session.last_error_message = _sanitize_error_message(message)
    session.completed_at = _utcnow()
    db.commit()
    logger.warning(
        "ai_echo_processing_failed session_id=%s clinic_id=%s user_id=%s "
        "step=%s code=%s",
        session.id,
        session.clinic_id,
        session.user_id,
        processing_step,
        code,
    )


def _active_audio(db: Session, session_id: str) -> AIEchoAudioAsset | None:
    return (
        db.query(AIEchoAudioAsset)
        .filter(
            AIEchoAudioAsset.session_id == session_id,
            AIEchoAudioAsset.deleted_at.is_(None),
        )
        .order_by(AIEchoAudioAsset.created_at.desc())
        .first()
    )


def _process_transcription(session_id: str) -> None:
    db = SessionLocal()
    started = _utcnow()
    processing_step = "transcription_load"
    try:
        session = db.query(AIEchoSession).filter(AIEchoSession.id == session_id).first()
        if not session:
            return
        processing_step = "transcription_audio_validation"
        asset = _active_audio(db, session.id)
        if not asset or _is_expired(asset.expires_at) or not os.path.isfile(asset.storage_path):
            raise AIEchoProviderError(
                "O áudio expirou ou foi excluído. Grave ou envie um novo arquivo.",
                code="audio_expired",
            )
        if int(session.attempts or 0) >= int(settings.AI_ECHO_MAX_ATTEMPTS):
            raise AIEchoProviderError(
                "O limite de tentativas desta sessão foi atingido. Crie uma nova sessão.",
                code="attempt_limit",
            )
        processing_step = "transcription_attempt"
        session.status = "transcribing"
        session.attempts = int(session.attempts or 0) + 1
        session.last_error_code = None
        session.last_error_message = None
        db.commit()

        with open(asset.storage_path, "rb") as file_obj:
            audio_bytes = file_obj.read()
        processing_step = "transcription_vocabulary"
        vocabulary = _custom_vocabulary(db, session.user_id)
        processing_step = "transcription_provider"
        provider = get_speech_to_text_provider()
        result = provider.transcribe(
            file_name=f"ditado{Path(asset.storage_path).suffix}",
            content_type=asset.mime_type,
            audio_bytes=audio_bytes,
            vocabulary=vocabulary,
        )

        processing_step = "transcription_persistence"
        db.query(AIEchoTranscript).filter(AIEchoTranscript.session_id == session.id).delete(
            synchronize_session=False
        )
        db.add(
            AIEchoTranscript(
                id=str(uuid.uuid4()),
                session_id=session.id,
                raw_text=result.text,
                edited_text=result.text,
                language=result.language,
                confidence=result.confidence,
            )
        )
        session.transcription_model = result.model
        session.status = "awaiting_review"
        session.completed_at = _utcnow()
        db.commit()
        logger.info(
            "ai_echo_step_completed session_id=%s clinic_id=%s user_id=%s "
            "step=transcription duration_ms=%s provider=%s model=%s prompt_version=%s",
            session.id,
            session.clinic_id,
            session.user_id,
            int((_utcnow() - started).total_seconds() * 1000),
            session.provider,
            session.transcription_model,
            session.prompt_version,
        )
    except Exception as exc:
        db.rollback()
        _mark_failed(
            db,
            session_id,
            exc,
            processing_step=processing_step,
        )
    finally:
        db.close()
        with _SUBMIT_LOCK:
            _SUBMITTED.discard(("transcribe", session_id))


def submit_transcription(session_id: str) -> None:
    with _SUBMIT_LOCK:
        key = ("transcribe", session_id)
        if key in _SUBMITTED:
            return
        _SUBMITTED.add(key)
    _EXECUTOR.submit(_process_transcription, session_id)


def prepare_transcription(db: Session, *, session: AIEchoSession) -> None:
    require_feature_available()
    asset = _active_audio(db, session.id)
    if not asset:
        raise HTTPException(status_code=409, detail="Envie um áudio antes de transcrever.")
    if session.status in ACTIVE_PROCESSING_STATES:
        raise HTTPException(status_code=409, detail="A sessão já está sendo processada.")
    session.status = "transcribing"
    session.last_error_code = None
    session.last_error_message = None
    db.commit()
    submit_transcription(session.id)


def _estimated_cost(input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None and output_tokens is None:
        return None
    input_rate = float(settings.AI_ECHO_STRUCTURING_INPUT_COST_PER_MILLION)
    output_rate = float(settings.AI_ECHO_STRUCTURING_OUTPUT_COST_PER_MILLION)
    if input_rate <= 0 and output_rate <= 0:
        return None
    return ((input_tokens or 0) * input_rate + (output_tokens or 0) * output_rate) / 1_000_000


def _process_structure(
    session_id: str,
    current_measurements: dict[str, str] | None = None,
) -> None:
    current_measurements = clinically_safe_echo_measurements(current_measurements or {})
    db = SessionLocal()
    started = _utcnow()
    processing_step = "structuring_load"
    try:
        session = db.query(AIEchoSession).filter(AIEchoSession.id == session_id).first()
        if not session:
            return
        transcript = (
            db.query(AIEchoTranscript)
            .filter(AIEchoTranscript.session_id == session.id)
            .order_by(AIEchoTranscript.created_at.desc())
            .first()
        )
        if not transcript or not transcript.edited_text.strip():
            raise AIEchoProviderError(
                "A transcrição está vazia. Revise ou grave novamente.",
                code="empty_transcription",
            )
        if int(session.attempts or 0) >= int(settings.AI_ECHO_MAX_ATTEMPTS):
            raise AIEchoProviderError(
                "O limite de tentativas desta sessão foi atingido. Crie uma nova sessão.",
                code="attempt_limit",
            )
        processing_step = "structuring_attempt"
        session.status = "structuring"
        session.attempts = int(session.attempts or 0) + 1
        session.last_error_code = None
        session.last_error_message = None
        db.commit()

        minimized_transcript = redact_personal_data(transcript.edited_text)
        processing_step = "structuring_preferences"
        phrase_preferences = _phrase_preferences(db, session.user_id)
        report = db.query(Laudo).filter(Laudo.id == session.laudo_id).first()
        patient = (
            db.query(Paciente).filter(Paciente.id == report.paciente_id).first()
            if report
            else None
        )
        patient_age = (
            idade_do_paciente(patient,
                **({"data_referencia": referencia_documento(report.data_exame, report.data_laudo),
                    "data_calendario": bool(report.data_exame)}
                   if report and (report.tipo or "").lower() == "ecocardiograma" else {}),
            )
            if patient else None
        ) or None
        reference_context = load_echo_reference_context(
            db,
            species=patient.especie if patient else None,
            weight_kg=patient.peso_kg if patient else None,
            current_measurements=current_measurements,
            age=patient_age,
        )
        exam_context = {
            "species": patient.especie if patient else None,
            "breed": patient.raca if patient else None,
            "age": patient_age,
            "weight_kg": patient.peso_kg if patient else None,
        }
        processing_step = "structuring_provider"
        if can_recover_normality_deterministically(transcript.edited_text):
            logger.info(
                "ai_echo_known_case_structured session_id=%s clinic_id=%s "
                "user_id=%s prompt_version=%s",
                session.id,
                session.clinic_id,
                session.user_id,
                PROMPT_VERSION,
            )
            result = StructuringResult(
                output=build_deterministic_known_case_output(exam_context),
                model="fortcordis-deterministic-clinical-rules",
                provider_response_id=None,
                input_tokens=None,
                output_tokens=None,
            )
        else:
            provider = get_clinical_structuring_provider()
            result = provider.structure(
                transcript=minimized_transcript,
                phrase_preferences=phrase_preferences,
                safety_user_id=session.user_id,
                current_measurements=current_measurements,
                exam_context=exam_context,
                reference_context=reference_context,
            )
        processing_step = "structuring_validation"
        output = validate_and_enrich_clinical_output(
            result.output,
            transcript.edited_text,
            species=patient.especie if patient else None,
            current_measurements=current_measurements,
            exam_context=exam_context,
            reference_context=reference_context,
        )

        processing_step = "structuring_persistence"
        db.query(AIEchoFieldSuggestion).filter(
            AIEchoFieldSuggestion.session_id == session.id
        ).delete(synchronize_session=False)
        db.query(AIEchoMeasurement).filter(AIEchoMeasurement.session_id == session.id).delete(
            synchronize_session=False
        )
        db.query(AIEchoClinicalWarning).filter(
            AIEchoClinicalWarning.session_id == session.id
        ).delete(synchronize_session=False)

        field_suggestions = list(output.field_suggestions)
        conclusion_text = "\n".join(
            item.strip()
            for item in output.conclusion_suggestion
            if item.strip()
        )
        if conclusion_text and not any(
            item.field_key == "conclusao" for item in field_suggestions
        ):
            field_suggestions.append(
                EchoFieldSuggestionOutput(
                    field_key="conclusao",
                    text=conclusion_text,
                    confidence=0.75,
                    source_spans=[],
                    evidence_type="diagnostic_suggestion",
                )
            )

        for suggestion in field_suggestions:
            db.add(
                AIEchoFieldSuggestion(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    field_key=suggestion.field_key,
                    suggested_value=suggestion.text,
                    confidence=suggestion.confidence,
                    source_spans_json=_json_dump(suggestion.source_spans),
                    evidence_type=suggestion.evidence_type,
                    status="pending",
                )
            )
        for measurement in output.measurements:
            db.add(
                AIEchoMeasurement(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    canonical_name=measurement.canonical_name,
                    display_name=measurement.display_name,
                    numeric_value=measurement.value,
                    raw_value=measurement.raw_value,
                    unit=measurement.unit,
                    target_field_key=measurement.target_field_key,
                    source_text=measurement.source_text,
                    confidence=measurement.confidence,
                    status="pending",
                )
            )
        for warning in output.warnings:
            db.add(
                AIEchoClinicalWarning(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    warning_type=warning.warning_type,
                    severity=warning.severity,
                    message=warning.message,
                    related_fields_json=_json_dump(warning.related_fields),
                )
            )

        session.structuring_model = result.model
        session.provider_response_id = result.provider_response_id
        session.input_tokens = result.input_tokens
        session.output_tokens = result.output_tokens
        session.estimated_cost = _estimated_cost(result.input_tokens, result.output_tokens)
        session.status = "awaiting_review"
        session.completed_at = _utcnow()
        db.commit()
        logger.info(
            "ai_echo_step_completed session_id=%s clinic_id=%s user_id=%s "
            "step=structuring duration_ms=%s "
            "provider=%s model=%s prompt_version=%s",
            session.id,
            session.clinic_id,
            session.user_id,
            int((_utcnow() - started).total_seconds() * 1000),
            session.provider,
            session.structuring_model,
            session.prompt_version,
        )
    except Exception as exc:
        db.rollback()
        _mark_failed(
            db,
            session_id,
            exc,
            processing_step=processing_step,
        )
    finally:
        db.close()
        with _SUBMIT_LOCK:
            _SUBMITTED.discard(("structure", session_id))


def submit_structure(
    session_id: str,
    current_measurements: dict[str, str] | None = None,
) -> None:
    with _SUBMIT_LOCK:
        key = ("structure", session_id)
        if key in _SUBMITTED:
            return
        _SUBMITTED.add(key)
    _EXECUTOR.submit(_process_structure, session_id, current_measurements)


def prepare_structure(
    db: Session,
    *,
    session: AIEchoSession,
    edited_transcript: str,
    current_measurements: dict[str, str] | None = None,
) -> None:
    require_feature_available()
    if session.status in ACTIVE_PROCESSING_STATES:
        raise HTTPException(status_code=409, detail="A sessão já está sendo processada.")
    transcript = (
        db.query(AIEchoTranscript)
        .filter(AIEchoTranscript.session_id == session.id)
        .order_by(AIEchoTranscript.created_at.desc())
        .first()
    )
    if not transcript:
        raise HTTPException(status_code=409, detail="Transcreva o áudio antes de estruturar.")
    transcript.edited_text = edited_transcript.strip()
    session.status = "structuring"
    session.last_error_code = None
    session.last_error_message = None
    db.commit()
    submit_structure(session.id, current_measurements)


def _serialize_timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_session(db: Session, session: AIEchoSession) -> dict[str, Any]:
    audio = _active_audio(db, session.id)
    transcript = (
        db.query(AIEchoTranscript)
        .filter(AIEchoTranscript.session_id == session.id)
        .order_by(AIEchoTranscript.created_at.desc())
        .first()
    )
    suggestions = (
        db.query(AIEchoFieldSuggestion)
        .filter(AIEchoFieldSuggestion.session_id == session.id)
        .order_by(AIEchoFieldSuggestion.created_at.asc())
        .all()
    )
    measurements = (
        db.query(AIEchoMeasurement)
        .filter(AIEchoMeasurement.session_id == session.id)
        .order_by(AIEchoMeasurement.created_at.asc())
        .all()
    )
    warnings = (
        db.query(AIEchoClinicalWarning)
        .filter(AIEchoClinicalWarning.session_id == session.id)
        .order_by(AIEchoClinicalWarning.created_at.asc())
        .all()
    )
    applications = (
        db.query(AIEchoApplication)
        .filter(AIEchoApplication.session_id == session.id)
        .order_by(AIEchoApplication.created_at.asc())
        .all()
    )
    return {
        "id": session.id,
        "laudo_id": session.laudo_id,
        "patient_id": session.patient_id,
        "clinic_id": session.clinic_id,
        "status": session.status,
        "provider": session.provider,
        "transcription_model": session.transcription_model,
        "structuring_model": session.structuring_model,
        "prompt_version": session.prompt_version,
        "attempts": session.attempts,
        "last_error": (
            {
                "code": session.last_error_code,
                "message": session.last_error_message,
            }
            if session.last_error_code
            else None
        ),
        "audio": (
            {
                "id": audio.id,
                "mime_type": audio.mime_type,
                "duration_seconds": audio.duration_seconds,
                "size_bytes": audio.size_bytes,
                "expires_at": _serialize_timestamp(audio.expires_at),
            }
            if audio
            else None
        ),
        "transcript": (
            {
                "id": transcript.id,
                "raw_text": transcript.raw_text,
                "edited_text": transcript.edited_text,
                "language": transcript.language,
                "confidence": transcript.confidence,
            }
            if transcript
            else None
        ),
        "field_suggestions": [
            {
                "id": item.id,
                "field_key": item.field_key,
                "suggested_value": item.suggested_value,
                "confidence": item.confidence,
                "source_spans": _json_load(item.source_spans_json, []),
                "evidence_type": item.evidence_type,
                "status": item.status,
            }
            for item in suggestions
        ],
        "measurements": [
            {
                "id": item.id,
                "canonical_name": item.canonical_name,
                "display_name": item.display_name,
                "numeric_value": item.numeric_value,
                "raw_value": item.raw_value,
                "unit": item.unit,
                "target_field_key": item.target_field_key,
                "source_text": item.source_text,
                "confidence": item.confidence,
                "status": item.status,
            }
            for item in measurements
        ],
        "warnings": [
            {
                "id": item.id,
                "warning_type": item.warning_type,
                "severity": item.severity,
                "message": item.message,
                "related_fields": _json_load(item.related_fields_json, []),
            }
            for item in warnings
        ],
        "usage": {
            "input_tokens": session.input_tokens,
            "output_tokens": session.output_tokens,
            "estimated_cost": session.estimated_cost,
        },
        "applications": [
            {
                "id": item.id,
                "mode": item.mode,
                "report_persisted": bool(item.report_persisted),
                "previous_form_snapshot": _json_load(item.previous_form_snapshot_json, {}),
                "applied_patch": _json_load(item.applied_patch_json, {}),
                "created_at": _serialize_timestamp(item.created_at),
            }
            for item in applications
        ],
        "created_at": _serialize_timestamp(session.created_at),
        "updated_at": _serialize_timestamp(session.updated_at),
        "completed_at": _serialize_timestamp(session.completed_at),
    }


def _selected_rows(
    rows: Iterable[Any],
    ids: list[str],
    *,
    label: str,
) -> list[Any]:
    requested = set(ids)
    selected = [row for row in rows if row.id in requested]
    if len(selected) != len(requested):
        raise HTTPException(status_code=422, detail=f"{label} inválida ou de outra sessão.")
    return selected


def apply_suggestions(
    db: Session,
    *,
    session: AIEchoSession,
    current_user: User,
    request: EchoApplyRequest,
) -> dict[str, Any]:
    if session.status != "awaiting_review":
        raise HTTPException(status_code=409, detail="A sessão não está pronta para revisão.")
    all_suggestions = (
        db.query(AIEchoFieldSuggestion)
        .filter(
            AIEchoFieldSuggestion.session_id == session.id,
            AIEchoFieldSuggestion.status == "pending",
        )
        .all()
    )
    all_measurements = (
        db.query(AIEchoMeasurement)
        .filter(
            AIEchoMeasurement.session_id == session.id,
            AIEchoMeasurement.status == "pending",
        )
        .all()
    )
    suggestions = _selected_rows(
        all_suggestions,
        request.accepted_suggestion_ids,
        label="Sugestão selecionada",
    )
    measurements = _selected_rows(
        all_measurements,
        request.accepted_measurement_ids,
        label="Medida selecionada",
    )
    if not set(request.suggestion_overrides).issubset(
        set(request.accepted_suggestion_ids)
    ):
        raise HTTPException(
            status_code=422,
            detail="Só é permitido editar sugestões selecionadas desta sessão.",
        )
    allowed_fields = set(EchoFieldKey.__args__)
    allowed_measurement_fields = set(EchoMeasurementFieldKey.__args__)
    field_patch: dict[str, str] = {}
    measurement_patch: dict[str, str] = {}
    skipped: list[str] = []
    accepted_suggestion_ids: list[str] = []
    accepted_measurement_ids: list[str] = []

    for suggestion in suggestions:
        if suggestion.field_key not in allowed_fields:
            raise HTTPException(status_code=422, detail="Campo de sugestão não permitido.")
        applied_text = request.suggestion_overrides.get(
            suggestion.id,
            suggestion.suggested_value,
        ).strip()
        current = str(request.current_fields.get(suggestion.field_key, "") or "")
        if request.mode == "empty_only" and current.strip():
            skipped.append(suggestion.field_key)
            continue
        if request.mode == "append" and current.strip():
            next_value = f"{current.rstrip()}\n{applied_text}"
        else:
            next_value = applied_text
        field_patch[suggestion.field_key] = next_value
        suggestion.status = "accepted"
        suggestion.accepted_at = _utcnow()
        accepted_suggestion_ids.append(suggestion.id)
        edited = applied_text != suggestion.suggested_value.strip()
        db.add(
            AIEchoFeedback(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=current_user.id,
                field_key=suggestion.field_key,
                original_suggestion=suggestion.suggested_value,
                final_text=applied_text,
                feedback_type="edited" if edited else "accepted",
            )
        )

        matching_phrase = (
            db.query(AIEchoPhrasePreference)
            .filter(
                AIEchoPhrasePreference.user_id == current_user.id,
                AIEchoPhrasePreference.field_key == suggestion.field_key,
                AIEchoPhrasePreference.phrase_text == applied_text,
            )
            .first()
        )
        if matching_phrase:
            matching_phrase.usage_count = int(matching_phrase.usage_count or 0) + 1

    for measurement in measurements:
        target = str(measurement.target_field_key or "")
        if not target or target not in allowed_measurement_fields:
            skipped.append(measurement.canonical_name)
            continue
        current = str(request.current_measurements.get(target, "") or "")
        if request.mode == "empty_only" and current.strip():
            skipped.append(target)
            continue
        value = measurement.raw_value
        if not value and measurement.numeric_value is not None:
            value = format(measurement.numeric_value, "g")
        if not value:
            skipped.append(target)
            continue
        measurement_patch[target] = str(value)
        measurement.status = "accepted"
        measurement.accepted_at = _utcnow()
        accepted_measurement_ids.append(measurement.id)

    if not field_patch and not measurement_patch:
        raise HTTPException(
            status_code=422,
            detail="Nenhum campo selecionado pôde ser aplicado com o modo escolhido.",
        )

    previous_snapshot = {
        "fields": request.current_fields,
        "measurements": request.current_measurements,
    }
    patch = {
        "fields": field_patch,
        "measurements": measurement_patch,
        "skipped": skipped,
    }
    application = AIEchoApplication(
        id=str(uuid.uuid4()),
        session_id=session.id,
        user_id=current_user.id,
        mode=request.mode,
        accepted_suggestion_ids_json=_json_dump(accepted_suggestion_ids),
        accepted_measurement_ids_json=_json_dump(accepted_measurement_ids),
        previous_form_snapshot_json=_json_dump(previous_snapshot),
        applied_patch_json=_json_dump(patch),
        report_persisted=False,
    )
    db.add(application)
    session.status = "applied"
    session.completed_at = _utcnow()
    db.commit()
    return {
        "application_id": application.id,
        "patch": patch,
        "report_persisted": False,
        "report_status": "Rascunho",
        "requires_normal_save": True,
    }


def add_feedback(
    db: Session,
    *,
    session: AIEchoSession,
    current_user: User,
    request: EchoFeedbackRequest,
) -> AIEchoFeedback:
    suggestion: AIEchoFieldSuggestion | None = None
    if request.suggestion_id:
        suggestion = (
            db.query(AIEchoFieldSuggestion)
            .filter(
                AIEchoFieldSuggestion.id == request.suggestion_id,
                AIEchoFieldSuggestion.session_id == session.id,
            )
            .first()
        )
        if not suggestion:
            raise HTTPException(status_code=404, detail="Sugestão não encontrada.")
    if request.feedback_type == "rejected":
        if session.status != "awaiting_review":
            raise HTTPException(status_code=409, detail="A sessão não está em revisão.")
        if not suggestion:
            raise HTTPException(
                status_code=422,
                detail="Informe a sugestão que deve ser rejeitada.",
            )
        suggestion.status = "rejected"
        suggestion.rejected_at = _utcnow()

    feedback = AIEchoFeedback(
        id=str(uuid.uuid4()),
        session_id=session.id,
        user_id=current_user.id,
        field_key=suggestion.field_key if suggestion else request.field_key,
        original_suggestion=(
            suggestion.suggested_value
            if suggestion
            else request.original_suggestion
        ),
        final_text=request.final_text,
        feedback_type=request.feedback_type,
    )
    db.add(feedback)
    if request.feedback_type == "reject_session":
        session.status = "rejected"
        session.completed_at = _utcnow()
        for suggestion in (
            db.query(AIEchoFieldSuggestion)
            .filter(
                AIEchoFieldSuggestion.session_id == session.id,
                AIEchoFieldSuggestion.status == "pending",
            )
            .all()
        ):
            suggestion.status = "rejected"
            suggestion.rejected_at = _utcnow()
        for measurement in (
            db.query(AIEchoMeasurement)
            .filter(
                AIEchoMeasurement.session_id == session.id,
                AIEchoMeasurement.status == "pending",
            )
            .all()
        ):
            measurement.status = "rejected"
            measurement.rejected_at = _utcnow()
    db.commit()
    db.refresh(feedback)
    return feedback


def get_preferences(db: Session, *, user_id: int) -> dict[str, Any]:
    vocabulary = (
        db.query(AIEchoVocabulary)
        .filter(AIEchoVocabulary.user_id == user_id)
        .order_by(AIEchoVocabulary.id.asc())
        .all()
    )
    phrases = (
        db.query(AIEchoPhrasePreference)
        .filter(AIEchoPhrasePreference.user_id == user_id)
        .order_by(AIEchoPhrasePreference.field_key.asc(), AIEchoPhrasePreference.id.asc())
        .all()
    )
    return {
        "vocabulary": [
            {
                "id": item.id,
                "spoken_form": item.spoken_form,
                "canonical_form": item.canonical_form,
                "category": item.category,
                "active": bool(item.active),
            }
            for item in vocabulary
        ],
        "phrases": [
            {
                "id": item.id,
                "field_key": item.field_key,
                "phrase_text": item.phrase_text,
                "tags": _json_load(item.tags_json, []),
                "active": bool(item.active),
                "usage_count": item.usage_count,
            }
            for item in phrases
        ],
    }


def replace_preferences(
    db: Session,
    *,
    current_user: User,
    request: EchoPreferencesUpdateRequest,
) -> dict[str, Any]:
    db.query(AIEchoVocabulary).filter(AIEchoVocabulary.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(AIEchoPhrasePreference).filter(
        AIEchoPhrasePreference.user_id == current_user.id
    ).delete(synchronize_session=False)
    unique_vocabulary: dict[str, Any] = {}
    for item in request.vocabulary:
        unique_vocabulary[item.spoken_form.casefold()] = item
    for item in unique_vocabulary.values():
        db.add(
            AIEchoVocabulary(
                user_id=current_user.id,
                spoken_form=item.spoken_form,
                canonical_form=item.canonical_form,
                category=item.category,
                active=item.active,
            )
        )
    for item in request.phrases:
        db.add(
            AIEchoPhrasePreference(
                user_id=current_user.id,
                field_key=item.field_key,
                phrase_text=item.phrase_text,
                tags_json=_json_dump(item.tags),
                active=item.active,
                usage_count=0,
            )
        )
    db.commit()
    return get_preferences(db, user_id=current_user.id)


def cleanup_expired_audio() -> int:
    db = SessionLocal()
    removed = 0
    try:
        if not inspect(db.get_bind()).has_table(AIEchoAudioAsset.__tablename__):
            return 0
        assets = (
            db.query(AIEchoAudioAsset)
            .filter(
                AIEchoAudioAsset.deleted_at.is_(None),
                AIEchoAudioAsset.expires_at <= _utcnow(),
            )
            .all()
        )
        for asset in assets:
            _remove_path(asset.storage_path)
            asset.deleted_at = _utcnow()
            removed += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Falha na limpeza de audios temporarios ai_echo")
    finally:
        db.close()
    return removed


def _cleanup_loop() -> None:
    interval_seconds = max(60, int(settings.AI_ECHO_CLEANUP_INTERVAL_MINUTES) * 60)
    while not _CLEANUP_STOP.is_set():
        cleanup_expired_audio()
        _CLEANUP_STOP.wait(interval_seconds)


def start_ai_echo_cleanup_worker() -> None:
    global _CLEANUP_THREAD
    if not settings.AI_ECHO_ASSISTANT_ENABLED:
        return
    if _CLEANUP_THREAD and _CLEANUP_THREAD.is_alive():
        return
    _CLEANUP_STOP.clear()
    _CLEANUP_THREAD = Thread(
        target=_cleanup_loop,
        name="ai-echo-cleanup",
        daemon=True,
    )
    _CLEANUP_THREAD.start()


def shutdown_ai_echo_cleanup_worker() -> None:
    global _CLEANUP_THREAD
    _CLEANUP_STOP.set()
    if _CLEANUP_THREAD and _CLEANUP_THREAD.is_alive():
        _CLEANUP_THREAD.join(timeout=5)
    _CLEANUP_THREAD = None


def restart_incomplete_ai_echo_sessions() -> int:
    db = SessionLocal()
    count = 0
    try:
        if not inspect(db.get_bind()).has_table(AIEchoSession.__tablename__):
            return 0
        rows = (
            db.query(AIEchoSession)
            .filter(AIEchoSession.status.in_(sorted(ACTIVE_PROCESSING_STATES)))
            .all()
        )
        for session in rows:
            session.status = "failed"
            session.last_error_code = "process_interrupted"
            session.last_error_message = (
                "O processamento foi interrompido por uma reinicialização. Tente novamente."
            )
            session.completed_at = _utcnow()
            count += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Falha ao recuperar sessoes ai_echo interrompidas")
    finally:
        db.close()
    return count
