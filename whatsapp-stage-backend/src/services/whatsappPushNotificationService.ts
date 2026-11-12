import axios from "axios";
import { logger } from "../utils/logger";

export async function notifyPushForInboundMessage(params: {
  conversationId: string;
  contactLabel: string | null;
  bodyPreview: string;
  waPhoneNumber?: string | null;
  waMessageId?: string | null;
  messageType?: string | null;
  messageTimestamp?: string | null;
}): Promise<void> {
  const apiBackendUrl = String(process.env.API_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const internalToken = String(process.env.WHATSAPP_INTERNAL_API_TOKEN || "").trim();
  if (!internalToken) {
    return;
  }

  try {
    await axios.post(
      `${apiBackendUrl}/api/v1/integracoes/whatsapp/notificacoes/mensagem-recebida`,
      {
        conversation_id: params.conversationId,
        contact_label: params.contactLabel ?? "",
        body_preview: params.bodyPreview,
        // Opcionais (RF-001): usados pelo bot de atendimento para enfileirar
        // um job por mensagem recebida. Um backend Python antigo os ignora;
        // a reconciliacao do bot cobre o caso de um Node antigo nao envia-los.
        wa_phone_number: params.waPhoneNumber ?? undefined,
        wa_message_id: params.waMessageId ?? undefined,
        message_type: params.messageType ?? undefined,
        message_timestamp: params.messageTimestamp ?? undefined
      },
      {
        headers: {
          "X-FortCordis-WhatsApp-Token": internalToken,
          "Content-Type": "application/json"
        },
        timeout: 5000
      }
    );
  } catch (error) {
    // Notificacao push nunca deve bloquear o processamento do webhook.
    logger.warn("Falha ao notificar push de mensagem recebida do WhatsApp", {
      conversationId: params.conversationId,
      message: error instanceof Error ? error.message : String(error)
    });
  }
}
