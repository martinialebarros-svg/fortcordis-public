from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, Request
from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.clinica import Clinica
from app.models.user import User
from app.services.assistente_ia_service import (
    AssistenteIAProviderError,
    _safe_provider_error,
    ensure_assistant_available,
)
from app.services.auditoria_service import registrar_auditoria

logger = logging.getLogger(__name__)

ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/flac",
    "audio/m4a",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
}
ALLOWED_AUDIO_EXTENSIONS = {
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}


def _voice_vocabulary_prompt(db: Session) -> str:
    clinic_names = [
        str(row[0]).strip()
        for row in (
            db.query(Clinica.nome)
            .filter(Clinica.ativo.in_([True, 1]))
            .order_by(Clinica.nome.asc())
            .limit(200)
            .all()
        )
        if str(row[0] or "").strip()
    ]
    vocabulary = ", ".join(clinic_names)
    prompt = (
        "Transcreva este comando administrativo em português brasileiro, com pontuação natural. "
        "Preserve datas, horários, números e termos veterinários como FortCordis, ecocardiograma, "
        "eletrocardiograma, consulta, laudo, tutor, paciente, clínica, agendamento e faturamento. "
        f"Nomes de clínicas cadastradas que podem aparecer no áudio: {vocabulary}."
    )
    return prompt[:6000]


def _validated_audio_metadata(
    *,
    file_name: Optional[str],
    content_type: Optional[str],
    audio_bytes: bytes,
) -> tuple[str, str]:
    safe_name = Path(str(file_name or "comando-voz.webm")).name
    normalized_content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    extension = Path(safe_name).suffix.lower()
    if (
        normalized_content_type not in ALLOWED_AUDIO_CONTENT_TYPES
        or extension not in ALLOWED_AUDIO_EXTENSIONS
    ):
        raise HTTPException(
            status_code=415,
            detail="Formato de audio nao suportado. Use webm, mp3, mp4, m4a, ogg, wav ou flac.",
        )
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="O audio enviado esta vazio.")
    max_bytes = max(1, int(settings.ASSISTENTE_IA_VOICE_MAX_BYTES))
    if len(audio_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail="O comando de voz excedeu o limite seguro de tamanho.",
        )
    return safe_name, normalized_content_type


def transcribe_voice_command(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    file_name: Optional[str],
    content_type: Optional[str],
    audio_bytes: bytes,
) -> dict[str, Any]:
    ensure_assistant_available()
    safe_name, normalized_content_type = _validated_audio_metadata(
        file_name=file_name,
        content_type=content_type,
        audio_bytes=audio_bytes,
    )
    model = str(settings.ASSISTENTE_IA_VOICE_TRANSCRIPTION_MODEL or "gpt-4o-transcribe").strip()
    client = OpenAI(
        api_key=str(settings.OPENAI_API_KEY).strip(),
        timeout=90.0,
        max_retries=1,
    )
    try:
        response = client.audio.transcriptions.create(
            model=model,
            file=(safe_name, audio_bytes, normalized_content_type),
            language="pt",
            response_format="json",
            prompt=_voice_vocabulary_prompt(db),
        )
    except Exception as exc:
        logger.exception("Falha na transcricao do comando de voz da Mente FortCordis")
        raise _safe_provider_error(exc) from exc

    transcript = str(getattr(response, "text", "") or "").strip()
    if not transcript:
        raise AssistenteIAProviderError("Nao foi possivel compreender o comando de voz.")

    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="comando_voz",
        entidade_id=None,
        acao="ASSISTENTE_IA_VOZ_TRANSCRITA",
        descricao="Mente FortCordis transcreveu um comando de voz para revisao do administrador.",
        detalhes={
            "modelo": model,
            "bytes": len(audio_bytes),
            "tipo": normalized_content_type,
            "persistiu_audio": False,
            "envio_automatico": False,
        },
        request=request,
    )
    return {
        "transcript": transcript,
        "language": "pt-BR",
        "model": model,
        "requires_review": True,
        "audio_persisted": False,
    }
