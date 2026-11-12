import axios from "axios";
import { PoolClient } from "pg";
import { query, queryWithClient } from "./dbService";
import { sendWhatsAppMessageWithRetry } from "./whatsappService";
import { WebhookMessage } from "../types/whatsapp";
import { logger } from "../utils/logger";
import { AgendaButtonReceipt, buildAgendaButtonReceipt } from "./agendaButtonReceipt";
import {
  areEquivalentWhatsAppNumbers,
  canonicalWhatsAppIdentity,
  whatsappGraphRecipient
} from "../utils/phoneNumber";

interface TemplateButtonBinding {
  id: string;
  template_key: string;
  subject_type: string;
  subject_id: string;
  destination: string;
  wa_message_id: string | null;
  action: string;
}

const whatsappAccessToken = process.env.WHATSAPP_ACCESS_TOKEN;
const phoneNumberId = process.env.PHONE_NUMBER_ID;

function apiBackendUrl(): string {
  return String(process.env.API_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

function internalToken(): string {
  const token = String(process.env.WHATSAPP_INTERNAL_API_TOKEN || "").trim();
  if (!token) {
    throw new Error("WHATSAPP_INTERNAL_API_TOKEN is required to process approved template button replies");
  }
  return token;
}

async function sendFreeTextReply(destinationPhone: string, body: string): Promise<void> {
  if (!whatsappAccessToken || !phoneNumberId) {
    throw new Error("Missing WhatsApp API environment configuration");
  }

  const conversation = await query<{ id: string }>(
    `SELECT id FROM conversations WHERE wa_phone_number = $1`,
    [canonicalWhatsAppIdentity(destinationPhone)]
  );
  const conversationId = conversation.rows[0]?.id;
  if (!conversationId) {
    throw new Error("Conversation not found for outbound free-text reply");
  }

  const inserted = await query<{ id: string }>(
    `
      INSERT INTO messages (conversation_id, from_me, body, type, metadata, status, created_at)
      VALUES ($1, true, $2, 'text', $3::jsonb, 'pending', now())
      RETURNING id
    `,
    [conversationId, body, JSON.stringify({ source: "approved_template_button.enviar_dados" })]
  );
  const localMessageId = inserted.rows[0].id;

  try {
    const graphResponse = await sendWhatsAppMessageWithRetry({
      phoneNumberId,
      accessToken: whatsappAccessToken,
      to: whatsappGraphRecipient(destinationPhone),
      body,
      type: "text"
    });
    await query(
      `UPDATE messages SET wa_message_id = $1, status = 'sent' WHERE id = $2`,
      [graphResponse.messages?.[0]?.id ?? null, localMessageId]
    );
  } catch (error) {
    await query(`UPDATE messages SET status = 'failed' WHERE id = $1`, [localMessageId]);
    throw error;
  }
  await query(`UPDATE conversations SET last_activity_at = now(), updated_at = now() WHERE id = $1`, [
    conversationId
  ]);
}

async function handleEnviarDados(binding: TemplateButtonBinding): Promise<Record<string, unknown>> {
  if (binding.subject_type !== "agendamento") {
    throw new Error(`enviar_dados is not supported for subject_type '${binding.subject_type}'`);
  }
  const response = await axios.post(
    `${apiBackendUrl()}/api/v1/integracoes/whatsapp/agenda/${binding.subject_id}/link-formalizacao`,
    {},
    {
      headers: {
        "X-FortCordis-WhatsApp-Token": internalToken(),
        "Content-Type": "application/json"
      },
      timeout: 10000
    }
  );
  const link = String(response.data?.link || "").trim();
  if (!link) {
    throw new Error("Backend did not return a formalizacao link");
  }
  await sendFreeTextReply(
    binding.destination,
    `Segue o link para preencher os dados do paciente e do tutor: ${link}`
  );
  return { link_sent: true };
}

async function handleAgendaResponse(
  binding: TemplateButtonBinding,
  message: WebhookMessage,
  action: "falar_equipe" | "confirmar_presenca" | "solicitar_alteracao"
): Promise<Record<string, unknown>> {
  const response = await axios.post(
    `${apiBackendUrl()}/api/v1/integracoes/whatsapp/agenda/respostas`,
    {
      provider_message_id: message.id,
      outbound_message_id: binding.wa_message_id,
      agendamento_id: Number(binding.subject_id),
      action,
      from_phone: canonicalWhatsAppIdentity(message.from as string)
    },
    {
      headers: {
        "X-FortCordis-WhatsApp-Token": internalToken(),
        "Content-Type": "application/json"
      },
      timeout: 10000
    }
  );
  return response.data ?? {};
}

function changeRequestAcknowledgementInboundAt(message: WebhookMessage): string | null {
  if (!message.timestamp || !/^\d+$/.test(String(message.timestamp))) return null;
  const timestamp = Number(message.timestamp) * 1000;
  const now = Date.now();
  // Signed provider timestamps are the basis for the customer-service window.
  if (!Number.isSafeInteger(timestamp) || timestamp > now + 5 * 60_000
      || timestamp <= now - 24 * 60 * 60_000) return null;
  const inboundAt = new Date(timestamp);
  return Number.isNaN(inboundAt.getTime()) ? null : inboundAt.toISOString();
}

export async function handleApprovedTemplateButtonReply(
  client: PoolClient,
  message: WebhookMessage
): Promise<AgendaButtonReceipt | undefined> {
  if (message.type !== "button" || !message.button?.payload || !message.id || !message.from) {
    return;
  }

  const bindingResult = await queryWithClient<TemplateButtonBinding>(
    client,
    `
      SELECT m.id, m.template_key, m.subject_type, m.subject_id::text AS subject_id,
             m.destination, m.wa_message_id, b.value->>'action' AS action
      FROM approved_template_messages m,
           jsonb_array_elements(m.button_bindings) AS b(value)
      WHERE m.processing_status = 'sent'
        AND b.value->>'payload' = $1
      LIMIT 1
      FOR UPDATE OF m
    `,
    [message.button.payload]
  );
  const binding = bindingResult.rows[0];
  if (!binding) {
    return;
  }

  const eventInsert = await queryWithClient<{ id: string }>(
    client,
    `
      INSERT INTO approved_template_button_events (
        provider_message_id, template_message_id, action, from_phone,
        processing_status, created_at
      ) VALUES ($1, $2, $3, $4, 'processing', now())
      ON CONFLICT (provider_message_id) DO NOTHING
      RETURNING id
    `,
    [message.id, binding.id, binding.action, canonicalWhatsAppIdentity(message.from)]
  );
  if (!eventInsert.rows[0]) {
    return;
  }
  const eventId = eventInsert.rows[0].id;

  if (!areEquivalentWhatsAppNumbers(binding.destination, message.from)) {
    await queryWithClient(
      client,
      `
        UPDATE approved_template_button_events
        SET processing_status = 'rejected',
            processing_error = 'sender does not match template destination',
            processed_at = now()
        WHERE id = $1
      `,
      [eventId]
    );
    logger.warn("Rejected approved template button from unexpected sender", {
      templateMessageId: binding.id,
      providerMessageId: message.id
    });
    return;
  }

  try {
    let result: Record<string, unknown>;
    if (binding.action === "enviar_dados") {
      result = await handleEnviarDados(binding);
    } else if (binding.action === "falar_equipe") {
      result = await handleAgendaResponse(binding, message, "falar_equipe");
    } else if ((binding.template_key === "appointmentReminder" || binding.template_key === "appointmentReminderService")
        && binding.subject_type === "agendamento"
        && (binding.action === "confirmar_presenca" || binding.action === "solicitar_alteracao")) {
      result = await handleAgendaResponse(binding, message, binding.action);
      if (binding.action === "solicitar_alteracao"
          && result.action === "solicitar_alteracao"
          && result.result === "alteracao_solicitada"
          && result.agendamento_id === Number(binding.subject_id)) {
        const inboundAt = changeRequestAcknowledgementInboundAt(message);
        if (inboundAt) {
          // A committed event is a durable send intent. The sender runs after
          // the webhook transaction, when the conversation lock is released.
          result = { ...result, acknowledgement_requested: true, acknowledgement_inbound_at: inboundAt };
        }
      }
    } else {
      await queryWithClient(
        client,
        `
          UPDATE approved_template_button_events
          SET processing_status = 'ignored', processed_at = now()
          WHERE id = $1
        `,
        [eventId]
      );
      return;
    }

    await queryWithClient(
      client,
      `
        UPDATE approved_template_button_events
        SET processing_status = 'processed', response_payload = $2::jsonb, processing_error = NULL, processed_at = now()
        WHERE id = $1
      `,
      [eventId, JSON.stringify(result)]
    );
    return buildAgendaButtonReceipt(binding.template_key, binding.action, Number(binding.subject_id), result);
  } catch (error) {
    await queryWithClient(
      client,
      `
        UPDATE approved_template_button_events
        SET processing_status = 'failed', processing_error = $2, processed_at = now()
        WHERE id = $1
      `,
      [eventId, error instanceof Error ? error.message.slice(0, 2000) : "unknown error"]
    );
    logger.error("Approved template button reply processing failed", {
      templateMessageId: binding.id,
      action: binding.action,
      providerMessageId: message.id,
      message: error instanceof Error ? error.message : String(error)
    });
  }
}
