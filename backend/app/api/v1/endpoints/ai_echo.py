from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.ai_echo import (
    EchoApplyRequest,
    EchoFeedbackRequest,
    EchoPreferencesUpdateRequest,
    EchoSessionCreateRequest,
    EchoStructureRequest,
)
from app.services.ai_echo_service import (
    add_feedback,
    apply_suggestions,
    create_session,
    delete_audio,
    feature_config,
    get_owned_session,
    get_preferences,
    prepare_structure,
    prepare_transcription,
    replace_preferences,
    serialize_session,
    store_audio,
)
from app.services.auditoria_service import registrar_auditoria

router = APIRouter()


@router.get("/config")
def get_ai_echo_config(
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = current_user.id
    return feature_config()


@router.get("/preferences")
def list_ai_echo_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return get_preferences(db, user_id=current_user.id)


@router.put("/preferences")
def update_ai_echo_preferences(
    payload: EchoPreferencesUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    result = replace_preferences(db, current_user=current_user, request=payload)
    registrar_auditoria(
        current_user=current_user,
        modulo="ai_echo",
        entidade="preferencias",
        entidade_id=current_user.id,
        acao="AI_ECHO_PREFERENCIAS_ATUALIZADAS",
        descricao="Preferências clínicas do assistente de laudo por voz foram atualizadas.",
        detalhes={
            "vocabulary_count": len(payload.vocabulary),
            "phrase_count": len(payload.phrases),
        },
        request=request,
    )
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
def create_ai_echo_session(
    payload: EchoSessionCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = create_session(db, current_user=current_user, laudo_id=payload.laudo_id)
    registrar_auditoria(
        current_user=current_user,
        modulo="ai_echo",
        entidade="sessao",
        entidade_id=session.id,
        acao="AI_ECHO_SESSAO_CRIADA",
        descricao="Sessão de ditado assistido criada para revisão do médico-veterinário.",
        detalhes={
            "laudo_id": session.laudo_id,
            "clinic_id": session.clinic_id,
            "status": session.status,
            "prompt_version": session.prompt_version,
        },
        request=request,
    )
    return serialize_session(db, session)


@router.get("/{session_id}")
def get_ai_echo_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id=session_id, user_id=current_user.id)
    return serialize_session(db, session)


@router.get("/{session_id}/audit")
def get_ai_echo_audit(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id=session_id, user_id=current_user.id)
    serialized = serialize_session(db, session)
    return {
        "session_id": session.id,
        "status": session.status,
        "applications": serialized["applications"],
        "prompt_version": session.prompt_version,
        "provider": session.provider,
        "models": {
            "transcription": session.transcription_model,
            "structuring": session.structuring_model,
        },
    }


@router.post("/{session_id}/audio", status_code=status.HTTP_201_CREATED)
async def upload_ai_echo_audio(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    duration_seconds: float | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id=session_id, user_id=current_user.id)
    max_bytes = int(settings.AI_ECHO_AUDIO_MAX_BYTES)
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="O áudio excede o limite de tamanho configurado.",
        )
    asset = store_audio(
        db,
        session=session,
        file_name=file.filename,
        content_type=file.content_type,
        content=content,
        duration_seconds=duration_seconds,
    )
    registrar_auditoria(
        current_user=current_user,
        modulo="ai_echo",
        entidade="audio",
        entidade_id=asset.id,
        acao="AI_ECHO_AUDIO_TEMPORARIO_ENVIADO",
        descricao="Áudio temporário enviado para transcrição assistida.",
        detalhes={
            "session_id": session.id,
            "size_bytes": asset.size_bytes,
            "duration_seconds": asset.duration_seconds,
            "mime_type": asset.mime_type,
            "expires_at": asset.expires_at.isoformat(),
        },
        request=request,
    )
    return serialize_session(db, session)


@router.delete("/{session_id}/audio")
def delete_ai_echo_audio(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id=session_id, user_id=current_user.id)
    deleted = delete_audio(db, session=session)
    registrar_auditoria(
        current_user=current_user,
        modulo="ai_echo",
        entidade="audio",
        entidade_id=session.id,
        acao="AI_ECHO_AUDIO_EXCLUIDO",
        descricao="Áudio temporário da sessão foi excluído.",
        detalhes={"session_id": session.id, "deleted": deleted},
        request=request,
    )
    return {"session_id": session.id, "audio_deleted": deleted}


@router.post("/{session_id}/transcribe", status_code=status.HTTP_202_ACCEPTED)
def transcribe_ai_echo_audio(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id=session_id, user_id=current_user.id)
    prepare_transcription(db, session=session)
    return {
        "session_id": session.id,
        "status": "transcribing",
        "message": "Transcrição iniciada. O restante do laudo continua disponível.",
    }


@router.post("/{session_id}/structure", status_code=status.HTTP_202_ACCEPTED)
def structure_ai_echo_transcript(
    session_id: str,
    payload: EchoStructureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id=session_id, user_id=current_user.id)
    prepare_structure(
        db,
        session=session,
        edited_transcript=payload.edited_transcript,
        current_measurements=payload.current_measurements,
    )
    return {
        "session_id": session.id,
        "status": "structuring",
        "message": "Estruturação clínica iniciada.",
    }


@router.post("/{session_id}/apply")
def apply_ai_echo_suggestions(
    session_id: str,
    payload: EchoApplyRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id=session_id, user_id=current_user.id)
    result = apply_suggestions(
        db,
        session=session,
        current_user=current_user,
        request=payload,
    )
    registrar_auditoria(
        current_user=current_user,
        modulo="ai_echo",
        entidade="aplicacao",
        entidade_id=result["application_id"],
        acao="AI_ECHO_SUGESTOES_APLICADAS_AO_FORMULARIO",
        descricao="Sugestões selecionadas foram devolvidas ao formulário como rascunho.",
        detalhes={
            "session_id": session.id,
            "field_keys": sorted(result["patch"]["fields"]),
            "measurement_keys": sorted(result["patch"]["measurements"]),
            "mode": payload.mode,
            "report_persisted": False,
        },
        request=request,
    )
    return result


@router.post("/{session_id}/feedback", status_code=status.HTTP_201_CREATED)
def create_ai_echo_feedback(
    session_id: str,
    payload: EchoFeedbackRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = get_owned_session(db, session_id=session_id, user_id=current_user.id)
    feedback = add_feedback(
        db,
        session=session,
        current_user=current_user,
        request=payload,
    )
    registrar_auditoria(
        current_user=current_user,
        modulo="ai_echo",
        entidade="feedback",
        entidade_id=feedback.id,
        acao="AI_ECHO_FEEDBACK_REGISTRADO",
        descricao="Revisão do médico-veterinário registrada sem conteúdo clínico nos logs.",
        detalhes={
            "session_id": session.id,
            "feedback_type": feedback.feedback_type,
            "field_key": feedback.field_key,
        },
        request=request,
    )
    return {
        "id": feedback.id,
        "session_id": session.id,
        "feedback_type": feedback.feedback_type,
        "status": session.status,
    }
