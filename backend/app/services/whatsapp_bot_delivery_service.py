"""Envio automatico de uma resposta persistida, sempre com a mesma chave.

Falha/resultado incerto vai para a equipe, nunca para um novo envio cego.
O Node revalida a revisao da conversa antes de reservar a mensagem.
"""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.whatsapp_bot import WhatsAppBotJob, WhatsAppBotResposta
from app.services.whatsapp_bot_gates import (
    is_whatsapp_bot_enabled, is_locally_paused, resolve_conversation_state,
    resolve_conversation_mode, resolve_modo_efetivo,
)
from app.services.whatsapp_bot_handoff_service import trigger_active_handoff
from app.services.whatsapp_bot_generation import IDENTITY_HANDOFF_REASONS
from app.services.whatsapp_contexto_selecao_service import lock_contexto, resposta_contexto_vigente


def deliver_automatic_reply(db: Session, job: WhatsAppBotJob, resposta: WhatsAppBotResposta) -> None:
    aviso_identidade = resposta.motivo in IDENTITY_HANDOFF_REASONS
    estado = resolve_conversation_state(db, job.wa_identity)
    modo, bloqueio = resolve_modo_efetivo(
        db, wa_identity=job.wa_identity, match_type=resposta.match_type,
        clinica_id=resposta.clinica_id, estado=estado,
        modo_atual=resolve_conversation_mode(db, job.wa_identity, estado=estado),
    )
    from app.services.whatsapp_bot_continuidade import pedido_assumido
    from app.services.whatsapp_bot_opcoes_agenda import envio_vigente
    if (not settings.WHATSAPP_BOT_AUTO_SEND_ENABLED or not is_whatsapp_bot_enabled()
            or modo != "auto" or bloqueio or is_locally_paused(estado)
            or pedido_assumido(db, job.wa_identity, job.conversation_id) or not envio_vigente(resposta)):
        # Um envio que ja comecou nao volta a ser um rascunho editavel.
        resposta.decisao = "handoff" if aviso_identidade or resposta.decisao == "sending" else "draft"
        if not aviso_identidade:
            resposta.motivo = "auto_interrompido"
        return

    resposta.decisao = "sending"
    db.commit()  # identidade duravel ANTES de qualquer efeito externo
    lock_contexto(db, job.wa_identity)
    if not resposta_contexto_vigente(db, resposta):
        resposta.decisao = "suppressed"
        resposta.motivo = "contexto_alterado"
        return
    base_url = str(settings.WHATSAPP_AGENDA_SERVICE_URL or "").rstrip("/")
    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "")
    motivo = "envio_auto_incerto"
    try:
        if not base_url or not token:
            raise ValueError("Servico interno nao configurado")
        response = httpx.post(
            f"{base_url}/conversations/{job.conversation_id}/messages",
            headers={"x-whatsapp-internal-token": token},
            json={"body": resposta.texto_gerado, "type": "text", "metadata": {
                "origem": "bot", "source": "bot_auto",
                "resposta_id": str(resposta.id),
                "idempotency_key": f"whatsapp-bot-resposta-{resposta.id}",
                "inbound_wa_message_id": job.wa_message_id,
            }},
            timeout=max(1, int(settings.WHATSAPP_AGENDA_TIMEOUT_SECONDS or 15)),
        )
        payload = response.json()
        if response.status_code in (200, 201) and payload.get("status") == "sent":
            resposta.decisao = "handoff" if aviso_identidade else "sent"
            resposta.texto_enviado = resposta.texto_gerado
            if not aviso_identidade:
                resposta.motivo = "enviado_auto"
            return
        if response.status_code == 409 and payload.get("code") == "BOT_CONVERSATION_CHANGED":
            resposta.decisao = "suppressed"
            resposta.motivo = "conversa_atualizada"
            return
    except Exception:
        # Nao registrar corpo/URL da excecao: podem conter dados pessoais.
        pass
    resposta.decisao = "handoff"
    resposta.motivo = motivo
    trigger_active_handoff(
        db, wa_identity=job.wa_identity, conversation_id=job.conversation_id,
        motivo=motivo, nivel="aviso", titulo="Conferir envio automatico do WhatsApp",
        mensagem_alerta=f"Confira a entrega na conversa {job.conversation_id} antes de responder novamente.",
    )
