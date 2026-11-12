from __future__ import annotations

import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.eco_study_import_job import EcoStudyImportJob
from app.services.eco_study_extraction_service import (
    ECO_STUDY_EXTRACTOR_VERSION,
    normalize_eco_study_filename,
    parse_eco_study_import_content,
    validate_eco_study_filename,
    validate_eco_study_size,
)

JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_TTL_DAYS = 7

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="eco-study-import")
_SUBMITTED_JOB_IDS: set[int] = set()
_SUBMIT_LOCK = Lock()


def _fallback_storage_dir() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "generated", "eco_study_import_jobs")
    )


def get_eco_study_import_storage_dir() -> str:
    preferred = str(settings.UPLOAD_DIR or "").strip()
    if os.name == "nt" and preferred.startswith("/"):
        preferred = ""
    candidate = os.path.join(preferred, "eco_study_import_jobs") if preferred else ""

    for path in [candidate, _fallback_storage_dir()]:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            continue
    raise RuntimeError("Nao foi possivel criar diretorio para importacao de estudos.")


def _parse_result_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _result_uses_current_extractor(value: str | None) -> bool:
    result = _parse_result_json(value)
    metadata = result.get("meta_importacao_estudo") if result else None
    if not isinstance(metadata, dict):
        return False
    return str(metadata.get("versao_extrator") or "") == ECO_STUDY_EXTRACTOR_VERSION


def serialize_eco_study_import_job(job: EcoStudyImportJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "filename": job.arquivo_nome,
        "erro": job.erro,
        "dados": _parse_result_json(job.resultado_json),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _file_exists(job: EcoStudyImportJob) -> bool:
    return bool(job.arquivo_caminho and os.path.exists(job.arquivo_caminho))


def _get_cached_job(
    db: Session,
    *,
    requested_by_id: int,
    content_hash: str,
) -> EcoStudyImportJob | None:
    jobs = (
        db.query(EcoStudyImportJob)
        .filter(
            EcoStudyImportJob.requested_by_id == requested_by_id,
            EcoStudyImportJob.conteudo_hash == content_hash,
        )
        .order_by(EcoStudyImportJob.id.desc())
        .all()
    )
    for job in jobs:
        if job.status == JOB_STATUS_COMPLETED and _result_uses_current_extractor(
            job.resultado_json
        ):
            return job
    for job in jobs:
        if job.status in {JOB_STATUS_PENDING, JOB_STATUS_PROCESSING}:
            return job
    return None


def _write_file(job_id: int, filename: str, content: bytes) -> str:
    storage_dir = get_eco_study_import_storage_dir()
    normalized = normalize_eco_study_filename(filename)
    base, extension = os.path.splitext(normalized)
    safe_base = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in base)
    target = os.path.join(storage_dir, f"study_{job_id}_{safe_base[:40] or 'estudo'}{extension.lower()}")
    fd, temp_path = tempfile.mkstemp(prefix=f"study_{job_id}_", suffix=extension, dir=storage_dir)
    try:
        with os.fdopen(fd, "wb") as file_obj:
            file_obj.write(content)
        os.replace(temp_path, target)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return target


def _mark_failed(db: Session, job_id: int, message: str) -> None:
    job = db.query(EcoStudyImportJob).filter(EcoStudyImportJob.id == job_id).first()
    if not job:
        return
    job.status = JOB_STATUS_FAILED
    job.erro = (message or "Falha ao processar estudo.")[:4000]
    job.finished_at = datetime.utcnow()
    db.commit()


def _process_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(EcoStudyImportJob).filter(EcoStudyImportJob.id == job_id).first()
        if not job:
            return
        if not _file_exists(job):
            raise RuntimeError("Arquivo temporario do estudo nao encontrado.")

        job.status = JOB_STATUS_PROCESSING
        job.started_at = datetime.utcnow()
        job.finished_at = None
        job.erro = None
        job.tentativas = int(job.tentativas or 0) + 1
        db.commit()

        with open(job.arquivo_caminho, "rb") as file_obj:
            content = file_obj.read()
        result = parse_eco_study_import_content(job.arquivo_nome, content)

        job = db.query(EcoStudyImportJob).filter(EcoStudyImportJob.id == job_id).first()
        if not job:
            return
        job.status = JOB_STATUS_COMPLETED
        job.resultado_json = json.dumps(result, ensure_ascii=False)
        job.erro = None
        job.finished_at = datetime.utcnow()
        job.expires_at = datetime.utcnow() + timedelta(days=JOB_TTL_DAYS)
        db.commit()
    except Exception as exc:
        db.rollback()
        _mark_failed(db, job_id, str(exc))
    finally:
        db.close()
        with _SUBMIT_LOCK:
            _SUBMITTED_JOB_IDS.discard(job_id)


def submit_eco_study_import_job(job_id: int) -> None:
    with _SUBMIT_LOCK:
        if job_id in _SUBMITTED_JOB_IDS:
            return
        _SUBMITTED_JOB_IDS.add(job_id)
    _EXECUTOR.submit(_process_job, job_id)


def enqueue_eco_study_import_job(
    db: Session,
    *,
    requested_by_id: int,
    filename: str | None,
    content_type: str | None,
    content: bytes,
) -> dict[str, Any]:
    normalized_filename = validate_eco_study_filename(filename)
    validate_eco_study_size(content)
    content_hash = hashlib.sha256(content).hexdigest()

    existing = _get_cached_job(
        db,
        requested_by_id=requested_by_id,
        content_hash=content_hash,
    )
    if existing:
        if existing.status == JOB_STATUS_PENDING:
            submit_eco_study_import_job(existing.id)
        return serialize_eco_study_import_job(existing)

    job = EcoStudyImportJob(
        requested_by_id=requested_by_id,
        status=JOB_STATUS_PENDING,
        arquivo_nome=normalized_filename,
        arquivo_tipo=(content_type or "application/octet-stream")[:100],
        conteudo_hash=content_hash,
        tentativas=0,
    )
    db.add(job)
    try:
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        existing = _get_cached_job(
            db,
            requested_by_id=requested_by_id,
            content_hash=content_hash,
        )
        if existing:
            return serialize_eco_study_import_job(existing)
        raise

    try:
        job.arquivo_caminho = _write_file(job.id, normalized_filename, content)
        db.commit()
    except Exception as exc:
        db.rollback()
        _mark_failed(db, job.id, str(exc))
        failed = db.query(EcoStudyImportJob).filter(EcoStudyImportJob.id == job.id).first()
        if not failed:
            raise
        return serialize_eco_study_import_job(failed)

    submit_eco_study_import_job(job.id)
    db.refresh(job)
    return serialize_eco_study_import_job(job)


def get_eco_study_import_job_for_user(
    db: Session,
    job_id: int,
    user_id: int,
) -> EcoStudyImportJob | None:
    job = db.query(EcoStudyImportJob).filter(
        EcoStudyImportJob.id == job_id,
        EcoStudyImportJob.requested_by_id == user_id,
    ).first()
    if not job:
        return None
    if job.status in {JOB_STATUS_PENDING, JOB_STATUS_PROCESSING} and not _file_exists(job):
        job.status = JOB_STATUS_FAILED
        job.erro = "Arquivo temporario do estudo nao encontrado."
        job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
    return job


def restart_incomplete_eco_study_import_jobs() -> None:
    db = SessionLocal()
    try:
        if "eco_study_import_jobs" not in inspect(db.get_bind()).get_table_names():
            return
        try:
            jobs = db.query(EcoStudyImportJob).filter(
                EcoStudyImportJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_PROCESSING])
            ).all()
        except Exception as exc:
            db.rollback()
            print(f"[eco-study-import-jobs] WARN: nao foi possivel retomar jobs: {exc}")
            return
        for job in jobs:
            job.status = JOB_STATUS_PENDING
            job.erro = None
        db.commit()
        for job in jobs:
            submit_eco_study_import_job(job.id)
    finally:
        db.close()


def shutdown_eco_study_import_jobs() -> None:
    _EXECUTOR.shutdown(wait=False, cancel_futures=False)
