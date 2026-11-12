from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.whatsapp_bot import WhatsAppBotJob

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _debounce_seconds() -> int:
    parsed = _safe_int(settings.WHATSAPP_BOT_DEBOUNCE_SECONDS, 12)
    return parsed if parsed > 0 else 12


def enqueue_job_for_inbound_message(
    db: Session,
    *,
    wa_identity: str,
    conversation_id: str,
    wa_message_id: str,
    message_type: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    """RF-002/RF-003/RF-004: cria um job com debounce para uma mensagem inbound.

    Dedupe por `wa_message_id` (reentrega de webhook da Meta) e supersede do
    job `pending` anterior da mesma conversa (CB-001: job em `processing` nao
    e afetado). Retorna True se um job novo foi criado, False em caso de
    dedupe ou payload incompleto.
    """
    # Reações não são novas solicitações. Não podem substituir um texto
    # ainda aguardando o debounce, nem criar handoff por tipo não suportado.
    if message_type == "reaction":
        return False
    now = now or _utc_now()
    wa_identity = str(wa_identity or "").strip()
    conversation_id = str(conversation_id or "").strip()
    wa_message_id = str(wa_message_id or "").strip()
    if not wa_identity or not conversation_id or not wa_message_id:
        return False

    from app.services.whatsapp_bot_agenda_receipts import confirmacao_agenda_processada
    if confirmacao_agenda_processada(
        db, wa_identity=wa_identity, wa_message_id=wa_message_id, message_type=message_type,
    ):
        # O domínio já tratou o botão (confirmação ou pedido de alteração).
        # Não cria handoff redundante nem substitui outro texto pendente.
        return False

    existing = (
        db.query(WhatsAppBotJob)
        .filter(WhatsAppBotJob.wa_message_id == wa_message_id)
        .first()
    )
    if existing is not None:
        return False

    scheduled_for = now + timedelta(seconds=_debounce_seconds())
    db.query(WhatsAppBotJob).filter(
        WhatsAppBotJob.wa_identity == wa_identity,
        WhatsAppBotJob.status == "pending",
    ).update({"status": "superseded", "updated_at": now}, synchronize_session=False)

    db.add(
        WhatsAppBotJob(
            wa_identity=wa_identity,
            conversation_id=conversation_id,
            wa_message_id=wa_message_id,
            status="pending",
            scheduled_for=scheduled_for,
            attempts=0,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Corrida rara: duas reentregas do mesmo wa_message_id quase simultaneas.
        db.rollback()
        return False
    return True
