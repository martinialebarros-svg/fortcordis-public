from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.push_scheduled_notification import PushScheduledNotification

logger = logging.getLogger(__name__)

PUSH_SCHEDULE_KIND_PENDING_OS = "pending_os_payment"
PUSH_SCHEDULE_KIND_SNOOZE = "snoozed_notification"

PUSH_SCHEDULE_STATUS_PENDING = "pending"
PUSH_SCHEDULE_STATUS_SENT = "sent"
PUSH_SCHEDULE_STATUS_CANCELLED = "cancelled"
PUSH_SCHEDULE_STATUS_ERROR = "error"

ALLOWED_SNOOZE_MINUTES = {15, 30, 60}
MAX_RETRY_ATTEMPTS = 3

_SCHEDULER_THREAD: Optional[threading.Thread] = None
_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STOP_EVENT = threading.Event()
_SCHEDULER_RUN_LOCK = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind and bind.dialect.name == "postgresql")


def _scheduler_distributed_lock_enabled() -> bool:
    return bool(settings.WEB_PUSH_SCHEDULER_DISTRIBUTED_LOCK_ENABLED)


def _scheduler_distributed_lock_key() -> int:
    parsed = _safe_int(settings.WEB_PUSH_SCHEDULER_DISTRIBUTED_LOCK_KEY, 80433001)
    if parsed <= 0:
        return 80433001
    return parsed


def _clamp_hours(value: Any) -> int:
    parsed = _safe_int(value, int(settings.WEB_PUSH_PENDING_REMINDER_DEFAULT_HOURS or 6))
    if parsed < 1:
        return 1
    if parsed > 168:
        return 168
    return parsed


def _clamp_minutes(value: Any) -> int:
    parsed = _safe_int(value, 15)
    if parsed in ALLOWED_SNOOZE_MINUTES:
        return parsed
    return 15


def _serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


def _deserialize_payload(payload_json: Optional[str]) -> dict[str, Any]:
    raw = _safe_text(payload_json)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return {}
    return {}


def schedule_pending_os_payment_reminder(
    db: Session,
    *,
    os_id: int,
    reminder_hours: int,
    data: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> PushScheduledNotification:
    due_at = _utc_now() + timedelta(hours=_clamp_hours(reminder_hours))
    payload_json = _serialize_payload(data or {})

    row = (
        db.query(PushScheduledNotification)
        .filter(
            PushScheduledNotification.kind == PUSH_SCHEDULE_KIND_PENDING_OS,
            PushScheduledNotification.resource_type == "ordem_servico",
            PushScheduledNotification.resource_id == int(os_id),
            PushScheduledNotification.status == PUSH_SCHEDULE_STATUS_PENDING,
        )
        .order_by(PushScheduledNotification.id.desc())
        .first()
    )

    if row is None:
        row = PushScheduledNotification(
            kind=PUSH_SCHEDULE_KIND_PENDING_OS,
            status=PUSH_SCHEDULE_STATUS_PENDING,
            module="financeiro",
            action="payment_pending",
            resource_type="ordem_servico",
            resource_id=int(os_id),
            url=f"/financeiro?aba=ordens&os_id={int(os_id)}&push_action=payment_pending",
            payload_json=payload_json,
            send_at=due_at,
            attempts=0,
        )
        db.add(row)
    else:
        row.status = PUSH_SCHEDULE_STATUS_PENDING
        row.payload_json = payload_json
        row.send_at = due_at
        row.attempts = 0
        row.last_error = None
        row.processed_at = None

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()

    return row


def cancel_pending_os_payment_reminder(
    db: Session,
    *,
    os_id: int,
    reason: str = "Removido por atualizacao da OS.",
    commit: bool = True,
) -> int:
    rows = (
        db.query(PushScheduledNotification)
        .filter(
            PushScheduledNotification.kind == PUSH_SCHEDULE_KIND_PENDING_OS,
            PushScheduledNotification.resource_type == "ordem_servico",
            PushScheduledNotification.resource_id == int(os_id),
            PushScheduledNotification.status == PUSH_SCHEDULE_STATUS_PENDING,
        )
        .all()
    )
    if not rows:
        return 0

    now = _utc_now()
    for row in rows:
        row.status = PUSH_SCHEDULE_STATUS_CANCELLED
        row.last_error = _safe_text(reason)[:800]
        row.processed_at = now
        row.updated_at = now

    if commit:
        db.commit()
    else:
        db.flush()
    return len(rows)


def schedule_push_snooze(
    db: Session,
    *,
    user_id: int,
    minutes: int,
    title: str,
    body: str,
    url: str,
    module: Optional[str],
    action: Optional[str],
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    priority: Optional[str] = None,
    source_notification_id: Optional[str] = None,
    commit: bool = True,
) -> PushScheduledNotification:
    snooze_minutes = _clamp_minutes(minutes)
    send_at = _utc_now() + timedelta(minutes=snooze_minutes)
    notification_id = _safe_text(source_notification_id) or uuid4().hex
    priority_value = _safe_text(priority).lower() or "normal"

    module_value = _safe_text(module) or "financeiro"
    action_value = _safe_text(action) or "payment_pending"
    url_value = _safe_text(url) or "/financeiro"

    payload = {
        "title": _safe_text(title) or "Lembrete FortCordis",
        "body": _safe_text(body) or "Voce possui uma notificacao adiada.",
        "url": url_value,
        "priority": priority_value,
        "stack_notifications": True,
        "require_interaction": True,
        "allow_snooze": True,
        "notification_id": notification_id,
        "tag": f"snooze-{module_value}-{action_value}-{resource_type or 'item'}-{resource_id or 0}",
        "data": {
            "module": module_value,
            "action": action_value,
            "notification_id": notification_id,
            "resource_type": _safe_text(resource_type),
            "resource_id": int(resource_id) if resource_id is not None else None,
        },
    }

    row = PushScheduledNotification(
        kind=PUSH_SCHEDULE_KIND_SNOOZE,
        status=PUSH_SCHEDULE_STATUS_PENDING,
        user_id=int(user_id),
        module=module_value,
        action=action_value,
        resource_type=_safe_text(resource_type) or None,
        resource_id=(int(resource_id) if resource_id is not None else None),
        title=_safe_text(title) or None,
        body=_safe_text(body) or None,
        url=url_value,
        priority=priority_value,
        payload_json=_serialize_payload(payload),
        source_notification_id=notification_id,
        snooze_minutes=snooze_minutes,
        send_at=send_at,
        attempts=0,
    )
    db.add(row)

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def _mark_row_processed(
    row: PushScheduledNotification,
    *,
    status: str,
    error: Optional[str] = None,
) -> None:
    now = _utc_now()
    row.status = status
    row.last_error = (_safe_text(error)[:800] if error else None)
    row.processed_at = now
    row.updated_at = now


def _reschedule_row(row: PushScheduledNotification, *, minutes: int, error: str) -> None:
    now = _utc_now()
    row.attempts = int(row.attempts or 0) + 1
    row.last_error = _safe_text(error)[:800]
    row.send_at = now + timedelta(minutes=minutes)
    row.updated_at = now


def _try_acquire_pg_scheduler_lock(db: Session, *, lock_key: int) -> bool:
    row = db.execute(
        text("SELECT pg_try_advisory_lock(:lock_key) AS locked"),
        {"lock_key": lock_key},
    ).fetchone()
    if not row:
        return False
    if hasattr(row, "_mapping"):
        return bool(row._mapping.get("locked"))
    return bool(row[0])


def _release_pg_scheduler_lock(db: Session, *, lock_key: int) -> None:
    db.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": lock_key},
    )


def _fetch_next_due_row(db: Session, *, now: datetime) -> Optional[PushScheduledNotification]:
    query = (
        db.query(PushScheduledNotification)
        .filter(
            PushScheduledNotification.status == PUSH_SCHEDULE_STATUS_PENDING,
            PushScheduledNotification.send_at <= now,
        )
        .order_by(PushScheduledNotification.send_at.asc(), PushScheduledNotification.id.asc())
    )
    if _is_postgres(db):
        query = query.with_for_update(skip_locked=True)
    return query.first()


def _process_pending_os_row(db: Session, row: PushScheduledNotification) -> None:
    from app.models.clinica import Clinica
    from app.models.ordem_servico import OrdemServico
    from app.models.paciente import Paciente
    from app.models.servico import Servico
    from app.services.push_notifications import send_financeiro_push_notification

    os_id = int(row.resource_id or 0)
    if os_id <= 0:
        _mark_row_processed(row, status=PUSH_SCHEDULE_STATUS_ERROR, error="OS invalida no agendamento.")
        return

    os_row = (
        db.query(
            OrdemServico,
            Paciente.nome.label("paciente_nome"),
            Clinica.nome.label("clinica_nome"),
            Servico.nome.label("servico_nome"),
        )
        .outerjoin(Paciente, OrdemServico.paciente_id == Paciente.id)
        .outerjoin(Clinica, OrdemServico.clinica_id == Clinica.id)
        .outerjoin(Servico, OrdemServico.servico_id == Servico.id)
        .filter(OrdemServico.id == os_id)
        .first()
    )

    if not os_row:
        _mark_row_processed(row, status=PUSH_SCHEDULE_STATUS_CANCELLED, error="OS nao encontrada.")
        return

    os_data, paciente_nome, clinica_nome, servico_nome = os_row
    if _safe_text(os_data.status) != "Pendente":
        _mark_row_processed(
            row,
            status=PUSH_SCHEDULE_STATUS_CANCELLED,
            error=f"OS com status {os_data.status}; lembrete cancelado.",
        )
        return

    payload_base = _deserialize_payload(row.payload_json)
    clinica_label = (
        str(clinica_nome or "").strip()
        or (
            "Atendimento domiciliar"
            if str(getattr(os_data, "origem_atendimento", None) or "").strip().lower() == "domiciliar"
            else ""
        )
    )
    data_payload = {
        "numero_os": os_data.numero_os,
        "paciente_nome": paciente_nome,
        "clinica_nome": clinica_label,
        "servico_nome": servico_nome,
        "valor_final": f"{float(os_data.valor_final or 0):.2f}",
    }
    if isinstance(payload_base, dict):
        data_payload.update({k: v for k, v in payload_base.items() if v is not None})
    # O lembrete pode ter sido agendado antes de um ajuste: o valor persistido
    # na OS prevalece sobre o snapshot do payload agendado.
    data_payload["valor_final"] = f"{float(os_data.valor_final or 0):.2f}"

    result = send_financeiro_push_notification(
        db,
        action="payment_pending",
        os_id=os_id,
        data=data_payload,
    )
    if int(result.get("sent") or 0) > 0:
        _mark_row_processed(row, status=PUSH_SCHEDULE_STATUS_SENT)
        return

    failed_count = int(result.get("failed") or 0)
    if failed_count > 0:
        if int(row.attempts or 0) + 1 >= MAX_RETRY_ATTEMPTS:
            _mark_row_processed(
                row,
                status=PUSH_SCHEDULE_STATUS_ERROR,
                error=f"Falha ao enviar lembrete apos {MAX_RETRY_ATTEMPTS} tentativas.",
            )
        else:
            _reschedule_row(row, minutes=20, error="Falha tecnica ao enviar lembrete pendente.")
        return

    if int(row.attempts or 0) + 1 >= MAX_RETRY_ATTEMPTS:
        _mark_row_processed(
            row,
            status=PUSH_SCHEDULE_STATUS_CANCELLED,
            error="Sem assinaturas push ativas para enviar lembrete.",
        )
    else:
        _reschedule_row(row, minutes=30, error="Sem assinaturas push ativas no momento.")


def _process_snooze_row(db: Session, row: PushScheduledNotification) -> None:
    from app.services.push_notifications import send_web_push_payload

    if row.user_id is None:
        _mark_row_processed(row, status=PUSH_SCHEDULE_STATUS_ERROR, error="Soneca sem user_id.")
        return

    payload = _deserialize_payload(row.payload_json)
    if not payload:
        _mark_row_processed(row, status=PUSH_SCHEDULE_STATUS_ERROR, error="Payload da soneca invalido.")
        return

    result = send_web_push_payload(
        db,
        payload=payload,
        notification_action=_safe_text(row.action) or None,
        include_user_ids={int(row.user_id)},
    )
    if int(result.get("sent") or 0) > 0:
        _mark_row_processed(row, status=PUSH_SCHEDULE_STATUS_SENT)
        return

    failed_count = int(result.get("failed") or 0)
    if failed_count > 0:
        if int(row.attempts or 0) + 1 >= MAX_RETRY_ATTEMPTS:
            _mark_row_processed(
                row,
                status=PUSH_SCHEDULE_STATUS_ERROR,
                error=f"Falha ao enviar soneca apos {MAX_RETRY_ATTEMPTS} tentativas.",
            )
        else:
            _reschedule_row(row, minutes=5, error="Falha tecnica ao enviar soneca.")
        return

    if int(row.attempts or 0) + 1 >= MAX_RETRY_ATTEMPTS:
        _mark_row_processed(
            row,
            status=PUSH_SCHEDULE_STATUS_CANCELLED,
            error="Sem assinaturas push ativas para o usuario da soneca.",
        )
    else:
        _reschedule_row(row, minutes=10, error="Sem assinaturas push ativas no momento.")


def run_push_scheduler_due_once(*, limit: int = 50) -> dict[str, int]:
    if not _SCHEDULER_RUN_LOCK.acquire(blocking=False):
        return {"processed": 0, "sent": 0, "cancelled": 0, "errors": 0}

    db = SessionLocal()
    pg_lock_key: Optional[int] = None
    pg_lock_acquired = False
    sent = 0
    cancelled = 0
    errors = 0
    processed = 0
    try:
        if _scheduler_distributed_lock_enabled() and _is_postgres(db):
            pg_lock_key = _scheduler_distributed_lock_key()
            pg_lock_acquired = _try_acquire_pg_scheduler_lock(db, lock_key=pg_lock_key)
            if not pg_lock_acquired:
                logger.info(
                    "Worker de push agendado ignorou ciclo: lock distribuido ocupado (key=%s).",
                    pg_lock_key,
                )
                return {"processed": 0, "sent": 0, "cancelled": 0, "errors": 0}

        max_rows = max(1, int(limit))
        while processed < max_rows:
            row = _fetch_next_due_row(db, now=_utc_now())
            if row is None:
                break
            processed += 1
            try:
                if row.kind == PUSH_SCHEDULE_KIND_PENDING_OS:
                    _process_pending_os_row(db, row)
                elif row.kind == PUSH_SCHEDULE_KIND_SNOOZE:
                    _process_snooze_row(db, row)
                else:
                    _mark_row_processed(row, status=PUSH_SCHEDULE_STATUS_ERROR, error="Tipo de agendamento push desconhecido.")
            except Exception as exc:
                logger.exception("Falha ao processar push agendado id=%s", row.id)
                if int(row.attempts or 0) + 1 >= MAX_RETRY_ATTEMPTS:
                    _mark_row_processed(row, status=PUSH_SCHEDULE_STATUS_ERROR, error=str(exc))
                else:
                    _reschedule_row(row, minutes=10, error=str(exc))

            if row.status == PUSH_SCHEDULE_STATUS_SENT:
                sent += 1
            elif row.status == PUSH_SCHEDULE_STATUS_CANCELLED:
                cancelled += 1
            elif row.status == PUSH_SCHEDULE_STATUS_ERROR:
                errors += 1

            db.commit()

        return {
            "processed": processed,
            "sent": sent,
            "cancelled": cancelled,
            "errors": errors,
        }
    finally:
        if pg_lock_key is not None and pg_lock_acquired:
            try:
                _release_pg_scheduler_lock(db, lock_key=pg_lock_key)
            except Exception:
                logger.exception("Falha ao liberar lock distribuido do scheduler de push.")
        db.close()
        _SCHEDULER_RUN_LOCK.release()


def _worker_poll_seconds() -> int:
    parsed = _safe_int(settings.WEB_PUSH_SCHEDULER_POLL_SECONDS, 30)
    if parsed < 10:
        return 10
    if parsed > 300:
        return 300
    return parsed


def _scheduler_worker_main() -> None:
    if not bool(settings.WEB_PUSH_SCHEDULER_ENABLED):
        logger.info("Worker de push agendado desativado por configuracao.")
        return

    while not _SCHEDULER_STOP_EVENT.is_set():
        try:
            run_push_scheduler_due_once(limit=80)
        except Exception:
            logger.exception("Falha no worker de push agendado.")
        if _SCHEDULER_STOP_EVENT.wait(_worker_poll_seconds()):
            break


def get_push_scheduler_worker_runtime_state() -> dict[str, Any]:
    distributed_lock_enabled = _scheduler_distributed_lock_enabled()
    distributed_lock_mode = "disabled"
    if distributed_lock_enabled:
        distributed_lock_mode = "postgres_advisory_lock"

    with _SCHEDULER_LOCK:
        thread = _SCHEDULER_THREAD
        thread_alive = bool(thread and thread.is_alive())
        worker_started = thread is not None
        stop_signal_set = _SCHEDULER_STOP_EVENT.is_set()

    enabled = bool(settings.WEB_PUSH_SCHEDULER_ENABLED)
    if not enabled:
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
        "poll_seconds": _worker_poll_seconds(),
        "distributed_lock": {
            "enabled": distributed_lock_enabled,
            "mode": distributed_lock_mode,
            "lock_key": _scheduler_distributed_lock_key() if distributed_lock_enabled else None,
        },
    }


def start_push_scheduler_worker() -> None:
    global _SCHEDULER_THREAD
    with _SCHEDULER_LOCK:
        if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
            return
        _SCHEDULER_STOP_EVENT.clear()
        _SCHEDULER_THREAD = threading.Thread(
            target=_scheduler_worker_main,
            name="push-scheduler-worker",
            daemon=True,
        )
        _SCHEDULER_THREAD.start()


def shutdown_push_scheduler_worker() -> None:
    global _SCHEDULER_THREAD
    with _SCHEDULER_LOCK:
        thread = _SCHEDULER_THREAD
        if not thread:
            return
        _SCHEDULER_STOP_EVENT.set()
    thread.join(timeout=5)
    with _SCHEDULER_LOCK:
        _SCHEDULER_THREAD = None
