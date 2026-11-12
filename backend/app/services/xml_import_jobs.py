from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from binascii import Error as BinasciiError
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.xml_import_job import XmlImportJob

JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_TTL_DAYS = 7
MAX_XML_IMPORT_SIZE = 5 * 1024 * 1024
# Re-importing the same XML must use the current measurement interpretation.
# Version the cache key without changing historical jobs or their saved results.
XML_IMPORT_PARSER_VERSION = "2"

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="xml-import")
_SUBMITTED_JOB_IDS: set[int] = set()
_SUBMIT_LOCK = Lock()


def _fallback_storage_dir() -> str:
    return os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "generated",
            "xml_import_jobs",
        )
    )


def get_xml_import_storage_dir() -> str:
    preferred = str(settings.UPLOAD_DIR or "").strip()
    if os.name == "nt" and preferred.startswith("/"):
        preferred = ""
    candidate = os.path.join(preferred, "xml_import_jobs") if preferred else ""

    for path in [candidate, _fallback_storage_dir()]:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            continue

    raise RuntimeError("Nao foi possivel criar diretorio para imports XML.")


def normalize_xml_filename(filename: str | None) -> str:
    raw_name = os.path.basename((filename or "").strip()) or "exame.xml"
    return raw_name


def validate_xml_import_filename(filename: str | None) -> str:
    normalized = normalize_xml_filename(filename)
    if not normalized.lower().endswith(".xml"):
        raise ValueError("Arquivo deve ser um XML")
    return normalized


def validate_xml_import_size(content: bytes) -> None:
    if len(content) > MAX_XML_IMPORT_SIZE:
        raise ValueError("XML excede o limite de 5MB")


def decode_xml_import_base64(content_b64: str) -> bytes:
    try:
        return base64.b64decode(content_b64 or "", validate=True)
    except (BinasciiError, ValueError) as exc:
        raise ValueError("Conteudo base64 invalido para importacao XML") from exc


def parse_xml_import_content(filename: str | None, content: bytes) -> dict[str, Any]:
    validate_xml_import_filename(filename)
    validate_xml_import_size(content)
    from app.utils.xml_parser import parse_xml_eco

    return parse_xml_eco(content)


def _parse_result_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _file_exists(job: XmlImportJob) -> bool:
    return bool(job.arquivo_caminho and os.path.exists(job.arquivo_caminho))


def _build_payload(job: XmlImportJob) -> dict[str, Any]:
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


def serialize_xml_import_job(job: XmlImportJob) -> dict[str, Any]:
    return _build_payload(job)


def _compute_xml_content_hash(xml_content: bytes) -> str:
    namespace = f"xml-parser:{XML_IMPORT_PARSER_VERSION}\0".encode("utf-8")
    return hashlib.sha256(namespace + xml_content).hexdigest()


def _get_cached_xml_import_job(
    db: Session,
    *,
    requested_by_id: int,
    conteudo_hash: str,
) -> XmlImportJob | None:
    jobs = (
        db.query(XmlImportJob)
        .filter(
            XmlImportJob.requested_by_id == requested_by_id,
            XmlImportJob.conteudo_hash == conteudo_hash,
        )
        .order_by(XmlImportJob.id.desc())
        .all()
    )

    for job in jobs:
        if job.status == JOB_STATUS_COMPLETED and _parse_result_json(job.resultado_json):
            return job

    for job in jobs:
        if job.status in {JOB_STATUS_PENDING, JOB_STATUS_PROCESSING}:
            return job

    return None


def _write_xml_file(job_id: int, filename: str, xml_content: bytes) -> str:
    storage_dir = get_xml_import_storage_dir()
    safe_name = os.path.splitext(normalize_xml_filename(filename))[0]
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in safe_name) or "exame"
    target_path = os.path.join(storage_dir, f"xml_{job_id}_{safe_name[:40]}.xml")

    fd, tmp_path = tempfile.mkstemp(suffix=".xml", prefix=f"xml_{job_id}_", dir=storage_dir)
    try:
        with os.fdopen(fd, "wb") as file_obj:
            file_obj.write(xml_content)
        os.replace(tmp_path, target_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target_path


def _mark_job_failed(db: Session, job_id: int, message: str) -> None:
    job = db.query(XmlImportJob).filter(XmlImportJob.id == job_id).first()
    if not job:
        return

    job.status = JOB_STATUS_FAILED
    job.erro = message[:4000]
    job.finished_at = datetime.utcnow()
    db.commit()


def _process_xml_import_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(XmlImportJob).filter(XmlImportJob.id == job_id).first()
        if not job:
            return

        if not _file_exists(job):
            raise RuntimeError("Arquivo XML temporario nao encontrado para processamento.")

        job.status = JOB_STATUS_PROCESSING
        job.started_at = datetime.utcnow()
        job.finished_at = None
        job.erro = None
        job.tentativas = int(job.tentativas or 0) + 1
        db.commit()

        with open(job.arquivo_caminho, "rb") as file_obj:
            xml_content = file_obj.read()
        dados = parse_xml_import_content(job.arquivo_nome, xml_content)

        job = db.query(XmlImportJob).filter(XmlImportJob.id == job_id).first()
        if not job:
            return
        job.status = JOB_STATUS_COMPLETED
        job.resultado_json = json.dumps(dados, ensure_ascii=False)
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


def submit_xml_import_job(job_id: int) -> None:
    with _SUBMIT_LOCK:
        if job_id in _SUBMITTED_JOB_IDS:
            return
        _SUBMITTED_JOB_IDS.add(job_id)

    _EXECUTOR.submit(_process_xml_import_job, job_id)


def enqueue_xml_import_job(
    db: Session,
    requested_by_id: int,
    filename: str | None,
    xml_content: bytes,
) -> dict[str, Any]:
    normalized_filename = validate_xml_import_filename(filename)
    validate_xml_import_size(xml_content)
    conteudo_hash = _compute_xml_content_hash(xml_content)

    existing = _get_cached_xml_import_job(
        db,
        requested_by_id=requested_by_id,
        conteudo_hash=conteudo_hash,
    )
    if existing:
        if existing.status == JOB_STATUS_PENDING:
            submit_xml_import_job(existing.id)
        return serialize_xml_import_job(existing)

    job = XmlImportJob(
        requested_by_id=requested_by_id,
        status=JOB_STATUS_PENDING,
        arquivo_nome=normalized_filename,
        conteudo_hash=conteudo_hash,
        erro=None,
        tentativas=0,
    )
    db.add(job)
    try:
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        existing = _get_cached_xml_import_job(
            db,
            requested_by_id=requested_by_id,
            conteudo_hash=conteudo_hash,
        )
        if existing:
            if existing.status == JOB_STATUS_PENDING:
                submit_xml_import_job(existing.id)
            return serialize_xml_import_job(existing)
        raise

    try:
        job.arquivo_caminho = _write_xml_file(job.id, normalized_filename, xml_content)
        db.commit()
    except Exception as exc:
        db.rollback()
        _mark_job_failed(db, job.id, str(exc))
        job = db.query(XmlImportJob).filter(XmlImportJob.id == job.id).first()
        if not job:
            raise
        return serialize_xml_import_job(job)

    submit_xml_import_job(job.id)
    db.refresh(job)
    return serialize_xml_import_job(job)


def get_xml_import_job_for_user(db: Session, job_id: int, user_id: int) -> XmlImportJob | None:
    job = db.query(XmlImportJob).filter(
        XmlImportJob.id == job_id,
        XmlImportJob.requested_by_id == user_id,
    ).first()
    if not job:
        return None

    if job.status == JOB_STATUS_COMPLETED and not job.resultado_json:
        job.status = JOB_STATUS_FAILED
        job.erro = "Resultado do import nao encontrado."
        job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job

    if job.status in {JOB_STATUS_PENDING, JOB_STATUS_PROCESSING} and not _file_exists(job):
        job.status = JOB_STATUS_FAILED
        job.erro = "Arquivo XML temporario nao encontrado para processamento."
        job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)

    return job


def restart_incomplete_xml_import_jobs() -> None:
    db = SessionLocal()
    try:
        try:
            jobs = db.query(XmlImportJob).filter(
                XmlImportJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_PROCESSING])
            ).all()
        except Exception as exc:
            db.rollback()
            print(f"[xml-import-jobs] WARN: nao foi possivel retomar jobs pendentes: {exc}")
            return

        if not jobs:
            return

        for job in jobs:
            job.status = JOB_STATUS_PENDING
            job.erro = None
        db.commit()

        for job in jobs:
            submit_xml_import_job(job.id)
    finally:
        db.close()


def shutdown_xml_import_jobs() -> None:
    _EXECUTOR.shutdown(wait=False, cancel_futures=False)
