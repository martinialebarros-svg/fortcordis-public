"""Reconhece respostas de botão já tratadas pelo fluxo autenticado de agenda."""
from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.whatsapp_agenda_resposta import WhatsappAgendaResposta
from app.services.whatsapp_contexto_selecao_service import canonical_context_identity


def confirmacao_agenda_processada(
    db: Session, *, wa_identity: str, wa_message_id: str, message_type: str | None,
) -> bool:
    # Texto visível, payload do botão e metadados recebidos não são prova de
    # tratamento. A evidência vem do recibo persistido pela API de agenda.
    if message_type != "button" or not wa_message_id:
        return False
    receipt = db.query(WhatsappAgendaResposta).filter(
        WhatsappAgendaResposta.provider_message_id == wa_message_id,
    ).populate_existing().first()
    if receipt is None:
        return False
    try:
        if canonical_context_identity(receipt.from_phone) != canonical_context_identity(wa_identity):
            return False
        payload = json.loads(receipt.result_json or "{}")
    except (HTTPException, TypeError, ValueError):
        return False
    if not isinstance(payload, dict) or (
        payload.get("action") != receipt.action
        or payload.get("result") != receipt.result
        or type(payload.get("agendamento_id")) is not int
        or not receipt.agendamento_id or receipt.agendamento_id < 1
        or payload.get("agendamento_id") != receipt.agendamento_id
    ):
        return False
    if receipt.action == "confirmar_presenca":
        return receipt.result == "presenca_confirmada" and payload.get("status") in ("Agendado", "Confirmado")
    if receipt.action == "solicitar_alteracao":
        # A API de agenda já gerou o alerta para a equipe. Não criar um segundo
        # handoff genérico pelo tipo de mensagem do clique.
        return receipt.result == "alteracao_solicitada"
    return (
        receipt.action == "confirmar"
        and receipt.result in {"confirmado", "ja_confirmado"}
        and payload.get("status") == "Confirmado"
    )
