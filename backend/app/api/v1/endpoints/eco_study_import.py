from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.eco_study_import_jobs import (
    enqueue_eco_study_import_job,
    get_eco_study_import_job_for_user,
    serialize_eco_study_import_job,
)

router = APIRouter()


def _translate_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if message.startswith("Arquivo deve ser imagem ou PDF"):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    if message == "Estudo excede o limite de 30MB":
        return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


@router.post("/jobs", response_model=dict)
def importar_estudo_eco_job(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    try:
        content = arquivo.file.read()
        return enqueue_eco_study_import_job(
            db,
            requested_by_id=current_user.id,
            filename=arquivo.filename,
            content_type=arquivo.content_type,
            content=content,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_error(exc)


@router.get("/jobs/{job_id}", response_model=dict)
def obter_estudo_eco_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    job = get_eco_study_import_job_for_user(db, job_id, current_user.id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job de importacao de estudo nao encontrado",
        )
    return serialize_eco_study_import_job(job)
