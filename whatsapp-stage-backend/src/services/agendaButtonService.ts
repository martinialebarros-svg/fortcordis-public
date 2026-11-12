import axios from "axios";
import { PoolClient } from "pg";
import { queryWithClient } from "./dbService";
import { WebhookMessage } from "../types/whatsapp";
import { logger } from "../utils/logger";
import { AgendaButtonReceipt, buildAgendaButtonReceipt } from "./agendaButtonReceipt";
import {
  areEquivalentWhatsAppNumbers,
  canonicalWhatsAppIdentity
} from "../utils/phoneNumber";

interface ReservationBinding {
  id: string;
  reservation_id: string;
  destination: string;
  wa_message_id: string | null;
  action: "confirmar" | "solicitar_alteracao";
}

export async function handleAgendaButtonReply(
  client: PoolClient,
  message: WebhookMessage
): Promise<AgendaButtonReceipt | undefined> {
  if (message.type !== "button" || !message.button?.payload || !message.id || !message.from) {
    return;
  }

  const bindingResult = await queryWithClient<ReservationBinding>(
    client,
    `
      SELECT
        id,
        reservation_id,
        destination,
        wa_message_id,
        CASE
          WHEN confirm_payload = $1 THEN 'confirmar'
          ELSE 'solicitar_alteracao'
        END AS action
      FROM agenda_reservation_messages
      WHERE processing_status = 'sent'
        AND (confirm_payload = $1 OR change_payload = $1)
      LIMIT 1
      FOR UPDATE
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
      INSERT INTO agenda_reservation_button_events (
        provider_message_id, reservation_message_id, action, from_phone,
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
        UPDATE agenda_reservation_button_events
        SET processing_status = 'rejected',
            processing_error = 'sender does not match reservation destination',
            processed_at = now()
        WHERE id = $1
      `,
      [eventId]
    );
    logger.warn("Rejected agenda reservation button from unexpected sender", {
      reservationId: binding.reservation_id,
      providerMessageId: message.id
    });
    return;
  }

  const apiBackendUrl = String(process.env.API_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const internalToken = String(process.env.WHATSAPP_INTERNAL_API_TOKEN || "").trim();
  if (!internalToken) {
    throw new Error("WHATSAPP_INTERNAL_API_TOKEN is required to process agenda button replies");
  }

  const response = await axios.post(
    `${apiBackendUrl}/api/v1/integracoes/whatsapp/agenda/respostas`,
    {
      provider_message_id: message.id,
      outbound_message_id: binding.wa_message_id,
      agendamento_id: Number(binding.reservation_id),
      action: binding.action,
      from_phone: canonicalWhatsAppIdentity(message.from)
    },
    {
      headers: {
        "X-FortCordis-WhatsApp-Token": internalToken,
        "Content-Type": "application/json"
      },
      timeout: 10000
    }
  );

  await queryWithClient(
    client,
    `
      UPDATE agenda_reservation_button_events
      SET processing_status = 'processed',
          response_payload = $2::jsonb,
          processing_error = NULL,
          processed_at = now()
      WHERE id = $1
    `,
    [eventId, JSON.stringify(response.data ?? {})]
  );
  return buildAgendaButtonReceipt("reservation", binding.action, Number(binding.reservation_id), response.data);
}
