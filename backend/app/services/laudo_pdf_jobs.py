from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.laudo_pdf_job import LaudoPdfJob
from app.models.user import User
from app.services.laudo_pdf_service import compute_laudo_pdf_cache_key, render_laudo_pdf

JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_TTL_DAYS = 14

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="laudo-pdf")
_SUBMITTED_JOB_IDS: set[int] = set()
_SUBMIT_LOCK = Lock()


def _fallback_storage_dir() -> str:
    return os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "generated",
            "laudo_pdf_jobs",
        )
    )


def get_laudo_pdf_storage_dir() -> str:
    preferred = str(settings.UPLOAD_DIR or "").strip()
    if os.name == "nt" and preferred.startswith("/"):
        preferred = ""
    candidate = os.path.join(preferred, "laudo_pdf_jobs") if preferred else ""

    for path in [candidate, _fallback_storage_dir()]:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            continue

    raise RuntimeError("Nao foi possivel criar diretorio para PDFs de laudo.")


def _file_exists(job: LaudoPdfJob) -> bool:
    return bool(job.arquivo_caminho and os.path.exists(job.arquivo_caminho))


def _build_payload(job: LaudoPdfJob) -> dict[str, Any]:
    download_url = None
    if job.status == JOB_STATUS_COMPLETED and _file_exists(job):
        download_url = f"/api/v1/laudos/pdf-jobs/{job.id}/download"

    return {
        "job_id": job.id,
        "laudo_id": job.laudo_id,
        "status": job.status,
        "arquivo_nome": job.arquivo_nome,
        "erro": job.erro,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "download_url": download_url,
    }


def serialize_laudo_pdf_job(job: LaudoPdfJob) -> dict[str, Any]:
    return _build_payload(job)


def get_cached_laudo_pdf_job(
    db: Session,
    laudo_id: int,
    requested_by_id: int,
    cache_key: str,
) -> LaudoPdfJob | None:
    jobs = db.query(LaudoPdfJob).filter(
        LaudoPdfJob.laudo_id == laudo_id,
        LaudoPdfJob.requested_by_id == requested_by_id,
        LaudoPdfJob.cache_key == cache_key,
    ).order_by(LaudoPdfJob.id.desc()).all()

    for job in jobs:
        if job.status == JOB_STATUS_COMPLETED and _file_exists(job):
            return job

    for job in jobs:
        if job.status in {JOB_STATUS_PENDING, JOB_STATUS_PROCESSING}:
            return job

    return None


def _get_active_laudo_pdf_job(
    db: Session,
    *,
    laudo_id: int,
    requested_by_id: int,
    cache_key: str,
) -> LaudoPdfJob | None:
    return (
        db.query(LaudoPdfJob)
        .filter(
            LaudoPdfJob.laudo_id == laudo_id,
            LaudoPdfJob.requested_by_id == requested_by_id,
            LaudoPdfJob.cache_key == cache_key,
            LaudoPdfJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_PROCESSING]),
        )
        .order_by(LaudoPdfJob.id.desc())
        .first()
    )


def _write_pdf_file(job_id: int, cache_key: str, pdf_bytes: bytes) -> str:
    storage_dir = get_laudo_pdf_storage_dir()
    target_path = os.path.join(storage_dir, f"laudo_{job_id}_{cache_key[:12]}.pdf")

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix=f"laudo_{job_id}_", dir=storage_dir)
    try:
        with os.fdopen(fd, "wb") as file_obj:
            file_obj.write(pdf_bytes)
        os.replace(tmp_path, target_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target_path


def _mark_job_failed(db: Session, job_id: int, message: str) -> None:
    job = db.query(LaudoPdfJob).filter(LaudoPdfJob.id == job_id).first()
    if not job:
        return

    job.status = JOB_STATUS_FAILED
    job.erro = message[:4000]
    job.finished_at = datetime.utcnow()
    db.commit()


def _process_laudo_pdf_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(LaudoPdfJob).filter(LaudoPdfJob.id == job_id).first()
        if not job:
            return

        job.status = JOB_STATUS_PROCESSING
        job.started_at = datetime.utcnow()
        job.finished_at = None
        job.erro = None
        job.tentativas = int(job.tentativas or 0) + 1
        db.commit()

        current_user = db.query(User).filter(User.id == job.requested_by_id).first()
        if not current_user:
            raise RuntimeError("Usuario solicitante do PDF nao encontrado.")

        pdf = render_laudo_pdf(db, job.laudo_id, current_user)
        arquivo_caminho = _write_pdf_file(job.id, pdf.cache_key, pdf.content)

        job = db.query(LaudoPdfJob).filter(LaudoPdfJob.id == job_id).first()
        if not job:
            return
        job.status = JOB_STATUS_COMPLETED
        job.cache_key = pdf.cache_key
        job.arquivo_nome = pdf.filename
        job.arquivo_caminho = arquivo_caminho
        job.erro = None
        job.finished_at = datetime.utcnow()
        job.expires_at = datetime.utcnow() + timedelta(days=JOB_TTL_DAYS)
        db.commit()
    except Exception as exc:
        db.rollback()
        _mark_job_failed(db, job_id, str(exc))
    finally:
        db.close()
        with _SUBMIT_LOCK:
            _SUBMITTED_JOB_IDS.discard(job_id)


def submit_laudo_pdf_job(job_id: int) -> None:
    with _SUBMIT_LOCK:
        if job_id in _SUBMITTED_JOB_IDS:
            return
        _SUBMITTED_JOB_IDS.add(job_id)

    _EXECUTOR.submit(_process_laudo_pdf_job, job_id)


def enqueue_laudo_pdf_job(db: Session, laudo_id: int, requested_by_id: int) -> dict[str, Any]:
    cache_key = compute_laudo_pdf_cache_key(db, laudo_id, requested_by_id)
    existing = get_cached_laudo_pdf_job(db, laudo_id, requested_by_id, cache_key)
    if existing:
        if existing.status == JOB_STATUS_PENDING:
            submit_laudo_pdf_job(existing.id)
        return serialize_laudo_pdf_job(existing)

    job = LaudoPdfJob(
        laudo_id=laudo_id,
        requested_by_id=requested_by_id,
        status=JOB_STATUS_PENDING,
        cache_key=cache_key,
        erro=None,
        tentativas=0,
    )
    db.add(job)
    try:
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        existing = _get_active_laudo_pdf_job(
            db,
            laudo_id=laudo_id,
            requested_by_id=requested_by_id,
            cache_key=cache_key,
        )
        if existing:
            if existing.status == JOB_STATUS_PENDING:
                submit_laudo_pdf_job(existing.id)
            return serialize_laudo_pdf_job(existing)
        raise

    submit_laudo_pdf_job(job.id)
    return serialize_laudo_pdf_job(job)


def get_laudo_pdf_job_for_user(db: Session, job_id: int, user_id: int) -> LaudoPdfJob | None:
    job = db.query(LaudoPdfJob).filter(
        LaudoPdfJob.id == job_id,
        LaudoPdfJob.requested_by_id == user_id,
    ).first()
    if not job:
        return None

    if job.status == JOB_STATUS_COMPLETED and not _file_exists(job):
        job.status = JOB_STATUS_FAILED
        job.erro = "Arquivo gerado nao encontrado no armazenamento."
        job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
    return job


def restart_incomplete_laudo_pdf_jobs() -> None:
    db = SessionLocal()
    try:
        try:
            jobs = db.query(LaudoPdfJob).filter(
                LaudoPdfJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_PROCESSING])
            ).all()
        except Exception as exc:
            db.rollback()
            print(f"[laudo-pdf-jobs] WARN: nao foi possivel retomar jobs pendentes: {exc}")
            return

        if not jobs:
            return

        for job in jobs:
            job.status = JOB_STATUS_PENDING
            job.erro = None
        db.commit()

        for job in jobs:
            submit_laudo_pdf_job(job.id)
    finally:
        db.close()


def shutdown_laudo_pdf_jobs() -> None:
    _EXECUTOR.shutdown(wait=False, cancel_futures=False)
