"""Endpoints para importacao de XML de ecocardiograma."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.image_header_import_service import parse_image_header_import_content
from app.services.xml_import_jobs import (
    decode_xml_import_base64,
    enqueue_xml_import_job,
    get_xml_import_job_for_user,
    parse_xml_import_content,
    serialize_xml_import_job,
)

router = APIRouter()


def _sync_success_payload(filename: str, dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "dados": dados,
        "filename": filename,
    }


def _translate_xml_import_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if message == "Arquivo deve ser um XML":
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    if message == "XML excede o limite de 5MB":
        return HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=message,
        )
    if message == "Conteudo base64 invalido para importacao XML":
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Erro ao processar XML: {message}",
    )


def _translate_image_import_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if message.startswith("Arquivo deve ser uma imagem"):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    if message == "Imagem excede o limite de 15MB":
        return HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=message,
        )
    if message.startswith("Tesseract OCR nao encontrado"):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=message,
        )
    if message in {
        "Nao foi possivel abrir a imagem enviada.",
        "Nao foi possivel reconhecer texto na imagem.",
        "Nao foi possivel identificar os campos do cabecalho na imagem.",
    }:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Erro ao processar imagem: {message}",
    )


@router.post("/importar-eco/jobs", response_model=dict)
def importar_xml_eco_job(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    try:
        content = arquivo.file.read()
        return enqueue_xml_import_job(
            db,
            requested_by_id=current_user.id,
            filename=arquivo.filename,
            xml_content=content,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_xml_import_error(exc)


@router.get("/importar-eco/jobs/{job_id}", response_model=dict)
def obter_xml_eco_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    job = get_xml_import_job_for_user(db, job_id, current_user.id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job de importacao XML nao encontrado",
        )
    return serialize_xml_import_job(job)


@router.post("/importar-eco", response_model=dict)
def importar_xml_eco(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    try:
        content = arquivo.file.read()
        dados = parse_xml_import_content(arquivo.filename, content)
        return _sync_success_payload(arquivo.filename or "exame.xml", dados)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_xml_import_error(exc)


@router.post("/importar-cabecalho-imagem", response_model=dict)
def importar_cabecalho_por_imagem(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    del db, current_user
    try:
        content = arquivo.file.read()
        dados = parse_image_header_import_content(arquivo.filename, content)
        return _sync_success_payload(arquivo.filename or "cabecalho.png", dados)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_image_import_error(exc)


@router.post("/importar-eco/base64/jobs", response_model=dict)
def importar_xml_eco_base64_job(
    dados: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    filename = dados.get("filename", "exame.xml")
    content_b64 = dados.get("content", "")

    try:
        content = decode_xml_import_base64(content_b64)
        return enqueue_xml_import_job(
            db,
            requested_by_id=current_user.id,
            filename=filename,
            xml_content=content,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_xml_import_error(exc)


@router.post("/importar-eco/base64", response_model=dict)
def importar_xml_eco_base64(
    dados: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    filename = dados.get("filename", "exame.xml")
    content_b64 = dados.get("content", "")

    try:
        content = decode_xml_import_base64(content_b64)
        dados_exame = parse_xml_import_content(filename, content)
        return _sync_success_payload(filename, dados_exame)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_xml_import_error(exc)
