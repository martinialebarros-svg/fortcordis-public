from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.agenda_config import NOMES_DIA_SEMANA
from app.services.alerta_interno_service import criar_alerta_interno
from app.services.assistente_ia_tools import LOCAL_TZ, _agenda_configuration_rules, _agenda_day_window
from app.services.push_notifications import send_whatsapp_message_push_notification
from app.services.whatsapp_bot_gates import set_handoff_motivo, pause_conversation

logger = logging.getLogger(__name__)

EMERGENCY_FIXED_MESSAGE = (
    "Isso parece uma emergencia. Ligue agora para a clinica ou va direto para um "
    "pronto-socorro veterinario - nao espere resposta por aqui. Ja avisamos nossa "
    "equipe."
)


def _now_local(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(LOCAL_TZ)
    return now.astimezone(LOCAL_TZ) if now.tzinfo else now.replace(tzinfo=LOCAL_TZ)


def _parse_hhmm(value: Any) -> Optional[tuple[int, int]]:
    try:
        hora, minuto = str(value or "").strip().split(":")
        return int(hora), int(minuto)
    except (ValueError, AttributeError):
        return None


def is_within_operating_window(db: Session, *, now: Optional[datetime] = None) -> bool:
    """RF-033: se a conversa foi passada para a equipe DENTRO do expediente

    (mesma janela operacional da agenda, `_agenda_day_window`).
    """
    reference = _now_local(now)
    exceptions, weekly, holidays = _agenda_configuration_rules(db)
    window = _agenda_day_window(reference.date(), exceptions=exceptions, weekly=weekly, holidays=holidays)
    if not window.get("ativo"):
        return False

    inicio = _parse_hhmm(window.get("inicio"))
    fim = _parse_hhmm(window.get("fim"))
    if inicio is None or fim is None:
        return False

    inicio_dt = reference.replace(hour=inicio[0], minute=inicio[1], second=0, microsecond=0)
    fim_dt = reference.replace(hour=fim[0], minute=fim[1], second=0, microsecond=0)
    return inicio_dt <= reference <= fim_dt


def _describe_next_opening(db: Session, *, now: Optional[datetime] = None, max_days: int = 14) -> Optional[str]:
    reference = _now_local(now)
    exceptions, weekly, holidays = _agenda_configuration_rules(db)

    for offset in range(max_days):
        day = reference.date() + timedelta(days=offset)
        window = _agenda_day_window(day, exceptions=exceptions, weekly=weekly, holidays=holidays)
        if not window.get("ativo"):
            continue

        inicio = _parse_hhmm(window.get("inicio"))
        if inicio is None:
            continue

        if offset == 0:
            abre_em = reference.replace(hour=inicio[0], minute=inicio[1], second=0, microsecond=0)
            if reference >= abre_em:
                continue
            return f"hoje as {window['inicio']}"
        if offset == 1:
            return f"amanha as {window['inicio']}"

        nome_dia = NOMES_DIA_SEMANA.get(str(day.isoweekday()), "")
        return f"{nome_dia} as {window['inicio']}"

    return None


def build_handoff_message(db: Session, *, now: Optional[datetime] = None) -> str:
    """RF-033: todo handoff diz quando uma pessoa responde. Dentro do

    expediente, informa a transferencia; fora dele, informa o proximo
    horario de atendimento (fonte: janela operacional da agenda).
    """
    if is_within_operating_window(db, now=now):
        return "Sua conversa foi passada para a nossa equipe, que dara continuidade ao atendimento."

    proxima_abertura = _describe_next_opening(db, now=now)
    if proxima_abertura:
        return (
            "No momento nao ha ninguem da equipe disponivel por aqui. Assim que "
            f"abrirmos, {proxima_abertura}, alguem vai te responder."
        )
    return "Sua conversa foi passada para a nossa equipe. Assim que possivel, alguem vai te responder."


def _bot_internal_client_config() -> Optional[tuple[str, dict[str, str], int]]:
    base_url = str(settings.WHATSAPP_AGENDA_SERVICE_URL or "").strip().rstrip("/")
    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "").strip()
    if not base_url or not token:
        return None
    timeout = max(1, int(settings.WHATSAPP_AGENDA_TIMEOUT_SECONDS or 15))
    return base_url, {"x-whatsapp-internal-token": token}, timeout


def _mark_conversation_pending(conversation_id: str) -> bool:
    client_config = _bot_internal_client_config()
    if client_config is None:
        return False
    base_url, headers, timeout = client_config
    try:
        response = httpx.patch(
            f"{base_url}/conversations/{conversation_id}/status",
            json={"status": "pending"},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.exception(
            "Falha ao marcar conversa como pendente no servico WhatsApp (conversation_id=%s).",
            conversation_id,
        )
        return False


def trigger_active_handoff(
    db: Session,
    *,
    wa_identity: str,
    conversation_id: str,
    motivo: str,
    nivel: str,
    titulo: str,
    mensagem_alerta: str,
    atualizado_por_id: Optional[int] = None,
    pausar: bool = True,
) -> None:
    """RF-011/RF-023: handoff ativo - conversa vai para `pending` no Node,

    alerta interno e push avisam a equipe. Usado para pedido explicito de
    humano e para emergencia (a unica diferenca entre os dois e o `nivel`
    do alerta e o `motivo` registrado).
    """
    set_handoff_motivo(db, wa_identity, motivo, atualizado_por_id=atualizado_por_id)
    db.flush()
    if pausar:
        pause_conversation(db, wa_identity, atualizado_por_id=atualizado_por_id)
    criar_alerta_interno(
        db,
        tipo=f"whatsapp_bot_{motivo}",
        nivel=nivel,
        titulo=titulo,
        mensagem=mensagem_alerta,
    )
    _mark_conversation_pending(conversation_id)
    try:
        send_whatsapp_message_push_notification(
            db,
            conversation_id=conversation_id,
            contact_label=titulo,
            body_preview=mensagem_alerta,
        )
    except Exception:
        logger.exception(
            "Falha ao enviar push de handoff do bot de atendimento WhatsApp (conversation_id=%s).",
            conversation_id,
        )
