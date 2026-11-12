export interface RetryableWhatsAppMessage {
  body: string | null;
  type: string;
  from_me: boolean;
  status: string;
  metadata?: unknown;
}

export function reviewedBotResponseId(message: { metadata?: unknown }): string | null {
  if (!message.metadata || typeof message.metadata !== "object" || Array.isArray(message.metadata)) return null;
  const metadata = message.metadata as Record<string, unknown>;
  const respostaId = metadata.resposta_id;
  if (metadata.source !== "bot_suggest_reviewed" || typeof respostaId !== "string" || !/^\d{1,20}$/.test(respostaId)) return null;
  return respostaId;
}

export function shouldOfferMessageResend(
  message: Pick<RetryableWhatsAppMessage, "from_me" | "status" | "type" | "metadata">,
): boolean {
  if (!message.from_me || message.status !== "failed" || message.type !== "text") return false;
  if (!message.metadata || typeof message.metadata !== "object" || Array.isArray(message.metadata)) return true;
  const metadata = message.metadata as Record<string, unknown>;
  if (metadata.source === "bot_auto") return false;
  return typeof metadata.superseded_by_message_id !== "string";
}

export function buildMessageResendRequest(
  message: Pick<RetryableWhatsAppMessage, "body" | "type" | "metadata">,
  conversationId: string,
) {
  const respostaId = reviewedBotResponseId(message);
  return respostaId ? {
    url: `/api/v1/whatsapp/bot/respostas/${respostaId}/enviar`,
    body: { texto: message.body },
    botReviewed: true,
  } : {
    url: `/whatsapp/conversations/${conversationId}/messages`,
    body: { body: message.body, type: message.type },
    botReviewed: false,
  };
}
