from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.atendimento_clinico import UploadDedupeCleanupRun

logger = logging.getLogger(__name__)

UPLOAD_DEDUPE_CLEANUP_EXECUTOR_MANUAL = "manual"
UPLOAD_DEDUPE_CLEANUP_EXECUTOR_AUTOMATIC = "automatic"
UPLOAD_DEDUPE_CLEANUP_STATUS_SUCCESS = "success"
UPLOAD_DEDUPE_CLEANUP_STATUS_ERROR = "error"
UPLOAD_DEDUPE_CLEANUP_ALERT_FAILURE_THRESHOLD = 3
UPLOAD_DEDUPE_CLEANUP_PG_LOCK_KEY = 80204105

_AUTO_WORKER_THREAD: Optional[threading.Thread] = None
_AUTO_WORKER_LOCK = threading.Lock()
_AUTO_WORKER_STOP_EVENT = threading.Event()
_LOCAL_CLEANUP_LOCK = threading.Lock()
_WORKER_POLL_SECONDS = 60


class UploadDedupeCleanupBusyError(RuntimeError):
    pass


class UploadDedupeCleanupExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        run_id: Optional[int] = None,
        cutoff_date: Optional[str] = None,
        deleted_rows: Optional[int] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.cutoff_date = cutoff_date
        self.deleted_rows = deleted_rows
        self.duration_ms = duration_ms


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return _ensure_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value).isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _parse_int_setting(
    value: Any,
    *,
    name: str,
    min_value: int,
    max_value: Optional[int] = None,
) -> int:
    try:
        parsed = int(value)
    except Exception as exc:
        raise ValueError(f"{name} invalido. Configure numero inteiro.") from exc

    if parsed < min_value:
        raise ValueError(f"{name} invalido. Configure valor >= {min_value}.")
    if max_value is not None and parsed > max_value:
        raise ValueError(f"{name} invalido. Configure valor <= {max_value}.")
    return parsed


def get_upload_dedupe_cleanup_config() -> Dict[str, Any]:
    return {
        "enabled": bool(settings.UPLOAD_DEDUPE_METRICS_AUTOCLEAN_ENABLED),
        "interval_hours": _parse_int_setting(
            settings.UPLOAD_DEDUPE_METRICS_AUTOCLEAN_INTERVAL_HOURS,
            name="UPLOAD_DEDUPE_METRICS_AUTOCLEAN_INTERVAL_HOURS",
            min_value=1,
        ),
        "retention_days": _parse_int_setting(
            settings.UPLOAD_DEDUPE_METRICS_RETENTION_DAYS,
            name="UPLOAD_DEDUPE_METRICS_RETENTION_DAYS",
            min_value=1,
        ),
        "timeout_seconds": _parse_int_setting(
            settings.UPLOAD_DEDUPE_METRICS_AUTOCLEAN_TIMEOUT_SECONDS,
            name="UPLOAD_DEDUPE_METRICS_AUTOCLEAN_TIMEOUT_SECONDS",
            min_value=30,
            max_value=600,
        ),
        "startup_jitter_seconds": _parse_int_setting(
            settings.UPLOAD_DEDUPE_METRICS_AUTOCLEAN_STARTUP_JITTER_SECONDS,
            name="UPLOAD_DEDUPE_METRICS_AUTOCLEAN_STARTUP_JITTER_SECONDS",
            min_value=0,
            max_value=300,
        ),
        "batch_size": _parse_int_setting(
            settings.UPLOAD_DEDUPE_METRICS_CLEANUP_BATCH_SIZE,
            name="UPLOAD_DEDUPE_METRICS_CLEANUP_BATCH_SIZE",
            min_value=100,
        ),
        "runs_retention_days": _parse_int_setting(
            settings.UPLOAD_DEDUPE_CLEANUP_RUNS_RETENTION_DAYS,
            name="UPLOAD_DEDUPE_CLEANUP_RUNS_RETENTION_DAYS",
            min_value=1,
        ),
    }


def _count_consecutive_failures(db: Session) -> int:
    rows = (
        db.query(UploadDedupeCleanupRun.status)
        .order_by(UploadDedupeCleanupRun.id.desc())
        .limit(50)
        .all()
    )
    consecutive = 0
    for row in rows:
        status = None
        if hasattr(row, "_mapping"):
            status = row._mapping.get("status")
            if status is None and row._mapping:
                status = next(iter(row._mapping.values()))
        elif isinstance(row, tuple):
            status = row[0]
        else:
            status = getattr(row, "status", None)
        if status != UPLOAD_DEDUPE_CLEANUP_STATUS_ERROR:
            break
        consecutive += 1
    return consecutive


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind and bind.dialect.name == "postgresql")


def _try_acquire_pg_transaction_lock(db: Session) -> bool:
    # Transaction-scoped advisory lock: released automatically on commit/rollback.
    row = db.execute(
        text("SELECT pg_try_advisory_xact_lock(:lock_key) AS locked"),
        {"lock_key": UPLOAD_DEDUPE_CLEANUP_PG_LOCK_KEY},
    ).fetchone()
    if not row:
        return False
    if hasattr(row, "_mapping"):
        return bool(row._mapping.get("locked"))
    return bool(row[0])


def _delete_rows_in_batches(
    db: Session,
    *,
    table_name: str,
    cutoff_datetime_str: str,
    batch_size: int,
    timeout_seconds: int,
    start_monotonic: float,
) -> int:
    if table_name not in {"upload_dedupe_metricas", "upload_dedupe_cleanup_runs"}:
        raise ValueError("Tabela de cleanup nao suportada.")

    select_sql = text(
        f"""
        SELECT id
        FROM {table_name}
        WHERE created_at < :cutoff_datetime
        ORDER BY id
        LIMIT :batch_size
        """
    )
    delete_sql = text(f"DELETE FROM {table_name} WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )

    total_deleted = 0
    while True:
        if (time.monotonic() - start_monotonic) > timeout_seconds:
            raise TimeoutError("Cleanup excedeu timeout configurado.")

        rows = db.execute(
            select_sql,
            {
                "cutoff_datetime": cutoff_datetime_str,
                "batch_size": batch_size,
            },
        ).fetchall()
        if not rows:
            break

        ids = [
            int(row._mapping["id"]) if hasattr(row, "_mapping") else int(row[0])
            for row in rows
        ]
        db.execute(delete_sql, {"ids": ids})
        total_deleted += len(ids)

    return total_deleted


def _is_automatic_cleanup_due(db: Session, interval_hours: int) -> bool:
    last_success = (
        db.query(UploadDedupeCleanupRun)
        .filter(UploadDedupeCleanupRun.status == UPLOAD_DEDUPE_CLEANUP_STATUS_SUCCESS)
        .order_by(UploadDedupeCleanupRun.id.desc())
        .first()
    )
    if not last_success:
        return True

    last_success_at = _coerce_datetime(last_success.finished_at) or _coerce_datetime(
        last_success.created_at
    )
    if not last_success_at:
        return True

    next_run_at = last_success_at + timedelta(hours=interval_hours)
    return _utc_now() >= next_run_at


def _build_success_payload(
    run: UploadDedupeCleanupRun,
    *,
    consecutive_failures: int,
) -> Dict[str, Any]:
    return {
        "run_id": run.id,
        "executor": run.executor,
        "status": run.status,
        "retention_days": run.retention_days,
        "cutoff_date": run.cutoff_date,
        "deleted_rows": int(run.deleted_rows or 0),
        "duration_ms": run.duration_ms,
        "consecutive_failures": consecutive_failures,
    }


def run_upload_dedupe_cleanup(*, executor: str) -> Dict[str, Any]:
    if executor not in {
        UPLOAD_DEDUPE_CLEANUP_EXECUTOR_MANUAL,
        UPLOAD_DEDUPE_CLEANUP_EXECUTOR_AUTOMATIC,
    }:
        raise ValueError("executor invalido para cleanup.")

    config = get_upload_dedupe_cleanup_config()
    if executor == UPLOAD_DEDUPE_CLEANUP_EXECUTOR_AUTOMATIC and not config["enabled"]:
        return {"executed": False, "reason": "autoclean_disabled"}

    if not _LOCAL_CLEANUP_LOCK.acquire(blocking=False):
        raise UploadDedupeCleanupBusyError("Cleanup de metricas ja esta em execucao.")

    db = SessionLocal()
    try:
        if (
            executor == UPLOAD_DEDUPE_CLEANUP_EXECUTOR_AUTOMATIC
            and not _is_automatic_cleanup_due(db, config["interval_hours"])
        ):
            return {"executed": False, "reason": "interval_not_reached"}

        start_monotonic = time.monotonic()
        started_at = _utc_now()
        cutoff_date = _utc_now().date() - timedelta(days=config["retention_days"])
        cutoff_datetime = datetime.combine(cutoff_date, datetime.min.time())
        cutoff_datetime_str = cutoff_datetime.strftime("%Y-%m-%d %H:%M:%S")
        deleted_rows = 0

        if _is_postgres(db):
            if not _try_acquire_pg_transaction_lock(db):
                raise UploadDedupeCleanupBusyError(
                    "Cleanup de metricas bloqueado por outra instancia ativa."
                )

        deleted_rows = _delete_rows_in_batches(
            db,
            table_name="upload_dedupe_metricas",
            cutoff_datetime_str=cutoff_datetime_str,
            batch_size=config["batch_size"],
            timeout_seconds=config["timeout_seconds"],
            start_monotonic=start_monotonic,
        )

        runs_cutoff_date = _utc_now().date() - timedelta(days=config["runs_retention_days"])
        runs_cutoff_datetime_str = datetime.combine(
            runs_cutoff_date, datetime.min.time()
        ).strftime("%Y-%m-%d %H:%M:%S")
        _delete_rows_in_batches(
            db,
            table_name="upload_dedupe_cleanup_runs",
            cutoff_datetime_str=runs_cutoff_datetime_str,
            batch_size=config["batch_size"],
            timeout_seconds=config["timeout_seconds"],
            start_monotonic=start_monotonic,
        )

        duration_ms = int((time.monotonic() - start_monotonic) * 1000)
        run = UploadDedupeCleanupRun(
            executor=executor,
            status=UPLOAD_DEDUPE_CLEANUP_STATUS_SUCCESS,
            retention_days=config["retention_days"],
            cutoff_date=cutoff_date.isoformat(),
            deleted_rows=deleted_rows,
            error_message=None,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=_utc_now(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        consecutive_failures = _count_consecutive_failures(db)
        logger.info(
            "Cleanup upload dedupe metricas concluido "
            "(executor=%s, run_id=%s, retention_days=%s, cutoff_date=%s, deleted_rows=%s, duration_ms=%s)",
            executor,
            run.id,
            run.retention_days,
            run.cutoff_date,
            run.deleted_rows,
            run.duration_ms,
        )
        return _build_success_payload(run, consecutive_failures=consecutive_failures)
    except UploadDedupeCleanupBusyError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        duration_ms = int((time.monotonic() - start_monotonic) * 1000) if "start_monotonic" in locals() else 0
        run = UploadDedupeCleanupRun(
            executor=executor,
            status=UPLOAD_DEDUPE_CLEANUP_STATUS_ERROR,
            retention_days=config.get("retention_days", 0),
            cutoff_date=(cutoff_date.isoformat() if "cutoff_date" in locals() else ""),
            deleted_rows=deleted_rows if "deleted_rows" in locals() else 0,
            error_message=str(exc)[:4000],
            duration_ms=duration_ms,
            started_at=started_at if "started_at" in locals() else _utc_now(),
            finished_at=_utc_now(),
        )
        run_id = None
        try:
            db.add(run)
            db.commit()
            db.refresh(run)
            run_id = run.id
            consecutive_failures = _count_consecutive_failures(db)
            if consecutive_failures >= UPLOAD_DEDUPE_CLEANUP_ALERT_FAILURE_THRESHOLD:
                logger.warning(
                    "ALERTA cleanup upload dedupe: %s falhas consecutivas (ultimo_run_id=%s, erro=%s)",
                    consecutive_failures,
                    run_id,
                    run.error_message,
                )
        except Exception:
            db.rollback()
            logger.exception("Falha ao registrar erro do cleanup upload dedupe.")

        raise UploadDedupeCleanupExecutionError(
            "Falha ao executar cleanup de metricas de upload.",
            run_id=run_id,
            cutoff_date=(cutoff_date.isoformat() if "cutoff_date" in locals() else None),
            deleted_rows=(deleted_rows if "deleted_rows" in locals() else None),
            duration_ms=duration_ms,
        ) from exc
    finally:
        db.close()
        _LOCAL_CLEANUP_LOCK.release()


def get_upload_dedupe_cleanup_status() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        last_run = db.query(UploadDedupeCleanupRun).order_by(UploadDedupeCleanupRun.id.desc()).first()
        last_success = (
            db.query(UploadDedupeCleanupRun)
            .filter(UploadDedupeCleanupRun.status == UPLOAD_DEDUPE_CLEANUP_STATUS_SUCCESS)
            .order_by(UploadDedupeCleanupRun.id.desc())
            .first()
        )
        consecutive_failures = _count_consecutive_failures(db)

        return {
            "last_run_id": last_run.id if last_run else None,
            "last_run_at": _to_iso(
                (last_run.finished_at or last_run.created_at) if last_run else None
            ),
            "last_success_at": _to_iso(last_success.finished_at if last_success else None),
            "last_status": (last_run.status if last_run else None),
            "last_deleted_rows": int(last_run.deleted_rows or 0) if last_run else 0,
            "last_cutoff_date": last_run.cutoff_date if last_run else None,
            "last_error": (last_run.error_message if last_run else None),
            "last_duration_ms": (last_run.duration_ms if last_run else None),
            "consecutive_failures": consecutive_failures,
            "alert_active": consecutive_failures >= UPLOAD_DEDUPE_CLEANUP_ALERT_FAILURE_THRESHOLD,
        }
    finally:
        db.close()


def maybe_run_automatic_upload_dedupe_cleanup() -> Dict[str, Any]:
    try:
        return run_upload_dedupe_cleanup(executor=UPLOAD_DEDUPE_CLEANUP_EXECUTOR_AUTOMATIC)
    except UploadDedupeCleanupBusyError as exc:
        logger.info("Auto-cleanup upload dedupe ignorado: %s", exc)
        return {"executed": False, "reason": "busy"}
    except UploadDedupeCleanupExecutionError:
        logger.exception("Falha no auto-cleanup upload dedupe.")
        return {"executed": False, "reason": "error"}
    except ValueError as exc:
        logger.error("Configuracao invalida para auto-cleanup upload dedupe: %s", exc)
        return {"executed": False, "reason": "invalid_config"}


def _auto_cleanup_worker_main() -> None:
    try:
        config = get_upload_dedupe_cleanup_config()
    except ValueError as exc:
        logger.error("Auto-cleanup desativado por configuracao invalida: %s", exc)
        return

    if not config["enabled"]:
        logger.info("Auto-cleanup upload dedupe desativado por configuracao.")
        return

    jitter_seconds = config["startup_jitter_seconds"]
    if jitter_seconds > 0:
        wait_seconds = random.randint(0, jitter_seconds)
        if wait_seconds > 0:
            logger.info("Auto-cleanup upload dedupe aguardando jitter de %ss no startup.", wait_seconds)
            if _AUTO_WORKER_STOP_EVENT.wait(wait_seconds):
                return

    while not _AUTO_WORKER_STOP_EVENT.is_set():
        maybe_run_automatic_upload_dedupe_cleanup()
        if _AUTO_WORKER_STOP_EVENT.wait(_WORKER_POLL_SECONDS):
            break


def get_upload_dedupe_cleanup_worker_runtime_state() -> Dict[str, Any]:
    config_error: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    try:
        config = get_upload_dedupe_cleanup_config()
    except ValueError as exc:
        config_error = str(exc)

    with _AUTO_WORKER_LOCK:
        thread = _AUTO_WORKER_THREAD
        thread_alive = bool(thread and thread.is_alive())
        worker_started = thread is not None
        stop_signal_set = _AUTO_WORKER_STOP_EVENT.is_set()

    enabled = bool(config["enabled"]) if config else bool(settings.UPLOAD_DEDUPE_METRICS_AUTOCLEAN_ENABLED)
    if config_error:
        status = "invalid_config"
    elif not enabled:
        status = "disabled"
    elif thread_alive:
        status = "running"
    else:
        status = "stopped"

    return {
        "enabled": enabled,
        "status": status,
        "thread_alive": thread_alive,
        "worker_started": worker_started,
        "stop_signal_set": stop_signal_set,
        "poll_seconds": _WORKER_POLL_SECONDS,
        "config_error": config_error,
    }


def start_upload_dedupe_cleanup_worker() -> None:
    global _AUTO_WORKER_THREAD
    with _AUTO_WORKER_LOCK:
        if _AUTO_WORKER_THREAD and _AUTO_WORKER_THREAD.is_alive():
            return
        _AUTO_WORKER_STOP_EVENT.clear()
        _AUTO_WORKER_THREAD = threading.Thread(
            target=_auto_cleanup_worker_main,
            name="upload-dedupe-cleanup-worker",
            daemon=True,
        )
        _AUTO_WORKER_THREAD.start()


def shutdown_upload_dedupe_cleanup_worker() -> None:
    global _AUTO_WORKER_THREAD
    with _AUTO_WORKER_LOCK:
        thread = _AUTO_WORKER_THREAD
        if not thread:
            return
        _AUTO_WORKER_STOP_EVENT.set()
    thread.join(timeout=5)
    with _AUTO_WORKER_LOCK:
        _AUTO_WORKER_THREAD = None
