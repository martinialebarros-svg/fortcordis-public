from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.agendamento import Agendamento

logger = logging.getLogger(__name__)

REMINDER_TEMPLATE_KEY = "appointmentReminder"
ELIGIBLE_STATUSES = {"Agendado", "Reservado", "Confirmado"}

_SCHEDULER_THREAD: Optional[threading.Thread] = None
_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STOP_EVENT = threading.Event()
_SCHEDULER_RUN_LOCK = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind and bind.dialect.name == "postgresql")


def _distributed_lock_enabled() -> bool:
    return bool(settings.WHATSAPP_REMINDER_SCHEDULER_DISTRIBUTED_LOCK_ENABLED)


def _distributed_lock_key() -> int:
    parsed = _safe_int(settings.WHATSAPP_REMINDER_SCHEDULER_DISTRIBUTED_LOCK_KEY, 80433002)
    return parsed if parsed > 0 else 80433002


def _try_acquire_pg_lock(db: Session, *, lock_key: int) -> bool:
    row = db.execute(
        text("SELECT pg_try_advisory_lock(:lock_key) AS locked"),
        {"lock_key": lock_key},
    ).fetchone()
    if not row:
        return False
    if hasattr(row, "_mapping"):
        return bool(row._mapping.get("locked"))
    return bool(row[0])


def _release_pg_lock(db: Session, *, lock_key: int) -> None:
    db.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})


def _min_lead_minutes() -> int:
    parsed = _safe_int(settings.WHATSAPP_REMINDER_MIN_LEAD_MINUTES, 45)
    return parsed if parsed > 0 else 45


def _window_hours() -> int:
    parsed = _safe_int(settings.WHATSAPP_REMINDER_WINDOW_HOURS, 24)
    return parsed if parsed > 0 else 24


def _max_attempts() -> int:
    parsed = _safe_int(settings.WHATSAPP_REMINDER_MAX_ATTEMPTS, 3)
    return parsed if parsed > 0 else 3


def _recipient_type() -> str:
    value = str(settings.WHATSAPP_REMINDER_RECIPIENT_TYPE or "clinica").strip().lower()
    return value if value in {"clinica", "tutor"} else "clinica"


def _eligibility_filters(now: datetime) -> list:
    janela_min = now + timedelta(minutes=_min_lead_minutes())
    janela_max = now + timedelta(hours=_window_hours())
    statuses = {"Agendado", "Confirmado"} if settings.WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED else ELIGIBLE_STATUSES
    return [
        Agendamento.status.in_(statuses),
        Agendamento.whatsapp_reminder_sent_at.is_(None),
        Agendamento.whatsapp_reminder_attempts < _max_attempts(),
        Agendamento.inicio >= janela_min,
        Agendamento.inicio <= janela_max,
    ]


def _fetch_next_due_agendamento(db: Session, *, now: datetime) -> Optional[Agendamento]:
    query = (
        db.query(Agendamento)
        .filter(*_eligibility_filters(now))
        .order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
    )
    if _is_postgres(db):
        query = query.with_for_update(skip_locked=True)
    return query.first()


def list_eligible_agendamentos_preview(
    db: Session, *, now: datetime, limit: int = 200
) -> list[dict[str, Any]]:
    """Lista (somente leitura, sem enviar nada) os agendamentos que o worker

    consideraria elegiveis agora, para inspecao manual antes de habilitar o
    envio automatico de fato.
    """
    from app.models.clinica import Clinica
    from app.models.tutor import Tutor

    recipient_type = _recipient_type()
    rows = (
        db.query(Agendamento)
        .filter(*_eligibility_filters(now))
        .order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
        .limit(max(1, int(limit)))
        .all()
    )

    preview: list[dict[str, Any]] = []
    for agendamento in rows:
        destination = _resolve_destination(db, agendamento, recipient_type)
        recipient_nome = None
        if recipient_type == "clinica" and agendamento.clinica_id:
            clinica = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first()
            recipient_nome = clinica.nome if clinica else None
        elif recipient_type == "tutor" and agendamento.tutor_id:
            tutor = db.query(Tutor).filter(Tutor.id == agendamento.tutor_id).first()
            recipient_nome = tutor.nome if tutor else None

        preview.append({
            "agendamento_id": agendamento.id,
            "status": agendamento.status,
            "inicio": agendamento.inicio.isoformat() if agendamento.inicio else None,
            "recipient_type": recipient_type,
            "recipient_nome": recipient_nome,
            "has_valid_destination": bool(destination),
            "destination_last4": destination[-4:] if destination else None,
        })
    return preview


def list_clinicas_prontidao_whatsapp_lembrete(
    db: Session, *, janela_dias: int = 60
) -> dict[str, Any]:
    """Audita, para cada clinica parceira ativa, se o numero de WhatsApp

    que o lembrete automatico usaria (mesma resolucao de _resolve_destination:
    primeiro item nao-vazio de `whatsapps`, com fallback para `telefone`)
    passa na validacao usada no envio real (`normalize_whatsapp_number`), e
    quantos agendamentos a clinica solicitou nos ultimos `janela_dias` dias
    (por `created_at`, nao pela data da consulta), para o usuario priorizar
    a revisao pelas clinicas de maior movimento. Somente leitura, nao envia
    nada - serve para revisao manual antes de habilitar o lembrete
    automatico em Configuracoes.
    """
    from app.models.clinica import Clinica
    from app.services.whatsapp_agenda_service import normalize_whatsapp_number

    clinicas = db.query(Clinica).filter(Clinica.ativo.is_(True)).all()

    cutoff = _utc_now() - timedelta(days=max(1, int(janela_dias)))
    contagem_por_clinica = dict(
        db.query(Agendamento.clinica_id, func.count(Agendamento.id))
        .filter(Agendamento.clinica_id.isnot(None), Agendamento.created_at >= cutoff)
        .group_by(Agendamento.clinica_id)
        .all()
    )

    clinicas_info: list[dict[str, Any]] = []
    total_prontas = 0
    for clinica in clinicas:
        candidates = clinica.whatsapps if isinstance(clinica.whatsapps, list) else []
        destino = next((str(value).strip() for value in candidates if str(value or "").strip()), None)
        destino = destino or (str(clinica.telefone).strip() if clinica.telefone else None)

        motivo: Optional[str] = None
        valor_cadastrado: Optional[str] = None
        if not destino:
            motivo = "sem_numero"
        else:
            try:
                normalize_whatsapp_number(destino)
                total_prontas += 1
            except HTTPException:
                motivo = "numero_invalido"
                valor_cadastrado = destino

        clinicas_info.append({
            "clinica_id": clinica.id,
            "clinica_nome": clinica.nome,
            "motivo": motivo,
            "valor_cadastrado": valor_cadastrado,
            "agendamentos_60_dias": int(contagem_por_clinica.get(clinica.id, 0)),
        })

    clinicas_info.sort(key=lambda item: (-item["agendamentos_60_dias"], item["clinica_nome"] or ""))
    problemas = [item for item in clinicas_info if item["motivo"]]

    return {
        "janela_dias": janela_dias,
        "total_clinicas_ativas": len(clinicas),
        "total_prontas": total_prontas,
        "total_com_problema": len(problemas),
        "clinicas": clinicas_info,
        "problemas": problemas,
    }


def _mark_error(agendamento: Agendamento, error: str) -> None:
    agendamento.whatsapp_reminder_attempts = int(agendamento.whatsapp_reminder_attempts or 0) + 1
    agendamento.whatsapp_reminder_last_error = str(error or "").strip()[:800]


def _resolve_destination(db: Session, agendamento: Agendamento, recipient_type: str) -> Optional[str]:
    if recipient_type == "clinica":
        from app.models.clinica import Clinica

        clinica = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first()
        if clinica is None:
            return None
        candidates = clinica.whatsapps if isinstance(clinica.whatsapps, list) else []
        first_whatsapp = next((str(value).strip() for value in candidates if str(value or "").strip()), None)
        return first_whatsapp or (str(clinica.telefone).strip() if clinica.telefone else None)

    from app.models.tutor import Tutor

    tutor = db.query(Tutor).filter(Tutor.id == agendamento.tutor_id).first()
    if tutor is None:
        return None
    return (str(tutor.whatsapp).strip() if tutor.whatsapp else None) or (
        str(tutor.telefone).strip() if tutor.telefone else None
    )


def _process_agendamento(db: Session, agendamento: Agendamento) -> str:
    """Processa um agendamento elegivel. Retorna "sent" ou "error"."""
    from app.services.whatsapp_agenda_service import (
        WhatsAppAgendaDeliveryError,
        build_agenda_utility_template,
        send_agenda_utility_template,
    )

    recipient_type = _recipient_type()
    destination = _resolve_destination(db, agendamento, recipient_type)
    if not destination:
        _mark_error(agendamento, f"Nenhum WhatsApp valido cadastrado para {recipient_type}.")
        return "error"

    try:
        template = build_agenda_utility_template(
            db,
            agendamento=agendamento,
            destination=destination,
            recipient_type=recipient_type,
            template_key=(
                "appointmentReminderService"
                if settings.WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED
                else REMINDER_TEMPLATE_KEY
            ),
        )
        send_agenda_utility_template(
            agendamento_id=agendamento.id,
            template=template,
            idempotency_key=f"appointment-reminder-{agendamento.id}",
        )
    except (HTTPException, WhatsAppAgendaDeliveryError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _mark_error(agendamento, str(detail))
        return "error"

    agendamento.whatsapp_reminder_sent_at = _utc_now()
    return "sent"


def run_whatsapp_reminder_scheduler_due_once(*, limit: int = 50) -> dict[str, int]:
    if not _SCHEDULER_RUN_LOCK.acquire(blocking=False):
        return {"processed": 0, "sent": 0, "errors": 0}

    db = SessionLocal()
    pg_lock_key: Optional[int] = None
    pg_lock_acquired = False
    sent = 0
    errors = 0
    processed = 0
    try:
        if _distributed_lock_enabled() and _is_postgres(db):
            pg_lock_key = _distributed_lock_key()
            pg_lock_acquired = _try_acquire_pg_lock(db, lock_key=pg_lock_key)
            if not pg_lock_acquired:
                logger.info(
                    "Worker de lembrete WhatsApp ignorou ciclo: lock distribuido ocupado (key=%s).",
                    pg_lock_key,
                )
                return {"processed": 0, "sent": 0, "errors": 0}

        max_rows = max(1, int(limit))
        while processed < max_rows:
            agendamento = _fetch_next_due_agendamento(db, now=_utc_now())
            if agendamento is None:
                break
            processed += 1
            try:
                result = _process_agendamento(db, agendamento)
            except Exception as exc:
                logger.exception(
                    "Falha inesperada ao processar lembrete WhatsApp do agendamento id=%s",
                    agendamento.id,
                )
                _mark_error(agendamento, str(exc))
                result = "error"

            if result == "sent":
                sent += 1
            else:
                errors += 1

            db.commit()

        return {"processed": processed, "sent": sent, "errors": errors}
    finally:
        if pg_lock_key is not None and pg_lock_acquired:
            try:
                _release_pg_lock(db, lock_key=pg_lock_key)
            except Exception:
                logger.exception("Falha ao liberar lock distribuido do worker de lembrete WhatsApp.")
        db.close()
        _SCHEDULER_RUN_LOCK.release()


def _worker_poll_seconds() -> int:
    parsed = _safe_int(settings.WHATSAPP_REMINDER_SCHEDULER_POLL_SECONDS, 300)
    if parsed < 60:
        return 60
    if parsed > 3600:
        return 3600
    return parsed


def is_reminder_scheduler_enabled_in_db() -> bool:
    """Fonte de verdade do liga/desliga: coluna gravavel via Configuracoes

    (admin), nao mais uma env var fixa no deploy. Falha fecha (retorna
    False) se a consulta der erro, para nunca disparar envio por acidente.
    """
    from app.models.configuracao import Configuracao

    db = SessionLocal()
    try:
        config = db.query(Configuracao).first()
        return bool(config and config.whatsapp_lembrete_automatico_habilitado)
    except Exception:
        logger.exception("Falha ao consultar configuracao do lembrete automatico do WhatsApp.")
        return False
    finally:
        db.close()


def _scheduler_worker_main() -> None:
    while not _SCHEDULER_STOP_EVENT.is_set():
        try:
            if is_reminder_scheduler_enabled_in_db():
                run_whatsapp_reminder_scheduler_due_once(limit=50)
        except Exception:
            logger.exception("Falha no worker de lembrete automatico do WhatsApp.")
        if _SCHEDULER_STOP_EVENT.wait(_worker_poll_seconds()):
            break


def get_whatsapp_reminder_scheduler_worker_runtime_state() -> dict[str, Any]:
    with _SCHEDULER_LOCK:
        thread = _SCHEDULER_THREAD
        thread_alive = bool(thread and thread.is_alive())
        worker_started = thread is not None
        stop_signal_set = _SCHEDULER_STOP_EVENT.is_set()

    enabled = is_reminder_scheduler_enabled_in_db()
    if not thread_alive:
        status = "stopped"
    elif enabled:
        status = "running"
    else:
        status = "idle"

    return {
        "enabled": enabled,
        "status": status,
        "thread_alive": thread_alive,
        "worker_started": worker_started,
        "stop_signal_set": stop_signal_set,
        "poll_seconds": _worker_poll_seconds(),
    }


def start_whatsapp_reminder_scheduler_worker() -> None:
    global _SCHEDULER_THREAD
    with _SCHEDULER_LOCK:
        if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
            return
        _SCHEDULER_STOP_EVENT.clear()
        _SCHEDULER_THREAD = threading.Thread(
            target=_scheduler_worker_main,
            name="whatsapp-reminder-scheduler-worker",
            daemon=True,
        )
        _SCHEDULER_THREAD.start()


def shutdown_whatsapp_reminder_scheduler_worker() -> None:
    global _SCHEDULER_THREAD
    with _SCHEDULER_LOCK:
        thread = _SCHEDULER_THREAD
        if not thread:
            return
        _SCHEDULER_STOP_EVENT.set()
    thread.join(timeout=5)
    with _SCHEDULER_LOCK:
        _SCHEDULER_THREAD = None
