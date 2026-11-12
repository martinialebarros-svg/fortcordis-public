import { query, queryWithClient, withTransaction } from "./dbService";
import { describeCustomerServiceWindow } from "./customerServiceWindow";
import { sendWhatsAppMessageWithRetry } from "./whatsappService";
import { areEquivalentWhatsAppNumbers, whatsappGraphRecipient } from "../utils/phoneNumber";
import { logger } from "../utils/logger";

export const CHANGE_REQUEST_ACK_SOURCE = "approved_template_button.solicitar_alteracao_ack";
export const CHANGE_REQUEST_ACK_TEXT =
  "Recebemos sua solicitação de alteração do agendamento. Nossa equipe vai analisar o pedido e entrar em contato para confirmar os ajustes. Se ainda não informou o que precisa mudar, responda com os detalhes.";

interface PendingAcknowledgement {
  provider_message_id: string;
  template_message_id: string;
  agendamento_id: string;
  destination: string;
  from_phone: string;
  inbound_at: string;
}

interface ReservedAcknowledgement {
  messageId: string;
  destination: string;
  conversationId: string;
}

let workerTimer: NodeJS.Timeout | null = null;
let activeRun: Promise<void> | null = null;
let shuttingDown = false;

function idempotencyKey(providerMessageId: string): string {
  return `appointment-change-ack:${providerMessageId}`;
}

async function findPendingAcknowledgements(limit: number): Promise<PendingAcknowledgement[]> {
  const result = await query<PendingAcknowledgement>(
    `
      SELECT e.provider_message_id, e.template_message_id::text,
             m.subject_id::text AS agendamento_id, m.destination, e.from_phone,
             e.response_payload->>'acknowledgement_inbound_at' AS inbound_at
      FROM approved_template_button_events e
      JOIN approved_template_messages m ON m.id = e.template_message_id
      WHERE e.processing_status = 'processed'
        AND e.action = 'solicitar_alteracao'
        AND e.response_payload->>'acknowledgement_requested' = 'true'
        AND NOT e.response_payload ? 'acknowledgement_skipped'
        AND e.response_payload->>'action' = 'solicitar_alteracao'
        AND e.response_payload->>'result' = 'alteracao_solicitada'
        AND e.response_payload->>'agendamento_id' = m.subject_id::text
        AND m.template_key IN ('appointmentReminder', 'appointmentReminderService')
        AND m.subject_type = 'agendamento'
        AND e.created_at > now() - interval '24 hours'
        AND (e.response_payload->>'acknowledgement_inbound_at')::timestamptz > now() - interval '24 hours'
        AND NOT EXISTS (
          SELECT 1 FROM messages reply
          WHERE reply.metadata->>'idempotency_key' = 'appointment-change-ack:' || e.provider_message_id
        )
      ORDER BY e.created_at ASC, e.id ASC
      LIMIT $1
    `,
    [limit]
  );
  return result.rows;
}

async function markStaleReservations(): Promise<void> {
  const stale = await query<{ id: string }>(
    `UPDATE messages SET status = 'failed',
       metadata = COALESCE(metadata, '{}'::jsonb)
         || '{"ack_delivery_outcome":"uncertain_after_restart"}'::jsonb
     WHERE from_me = TRUE AND status = 'pending'
       AND metadata->>'source' = $1
       AND created_at < now() - interval '5 minutes'
     RETURNING id`,
    [CHANGE_REQUEST_ACK_SOURCE]
  );
  if (stale.rowCount) {
    logger.warn("Stale change-request acknowledgements require operator review", {
      count: stale.rowCount
    });
  }
}

async function reserveAcknowledgement(candidate: PendingAcknowledgement): Promise<ReservedAcknowledgement | null> {
  const key = idempotencyKey(candidate.provider_message_id);
  return withTransaction(async (client) => {
    await queryWithClient(client, "SELECT pg_advisory_xact_lock(hashtext($1))", [key]);
    const existing = await queryWithClient<{ id: string }>(client,
      "SELECT id FROM messages WHERE metadata->>'idempotency_key' = $1 LIMIT 1", [key]);
    if (existing.rowCount) return null;

    const conversation = await queryWithClient<{
      id: string;
      wa_phone_number: string;
      last_inbound_at: Date | string | null;
    }>(client, `SELECT id, wa_phone_number, last_inbound_at
                FROM conversations WHERE wa_phone_number = $1 FOR UPDATE`, [candidate.from_phone]);
    const row = conversation.rows[0];
    const inboundAt = new Date(candidate.inbound_at);
    const now = new Date();
    let skipReason: string | null = null;
    if (!row || !areEquivalentWhatsAppNumbers(candidate.destination, candidate.from_phone)) {
      skipReason = "invalid_destination";
    } else if (Number.isNaN(inboundAt.getTime()) || inboundAt.getTime() > now.getTime() + 5 * 60_000
        || !describeCustomerServiceWindow(inboundAt, now).is_open
        || !describeCustomerServiceWindow(row.last_inbound_at, now).is_open) {
      skipReason = "customer_window_closed";
    }

    if (!skipReason && row) {
      const inbound = await queryWithClient<{ id: string; created_at: Date | string }>(client,
        `SELECT id, created_at FROM messages WHERE conversation_id = $1 AND wa_message_id = $2
           AND from_me = FALSE LIMIT 1`, [row.id, candidate.provider_message_id]);
      if (!inbound.rows[0]) {
        skipReason = "inbound_not_found";
      } else {
        const humanReply = await queryWithClient<{ id: string }>(client,
          `SELECT id FROM messages WHERE conversation_id = $1
             AND (created_at, id) > ($2::timestamptz, $3::bigint)
             AND from_me = TRUE AND status IN ('sent', 'delivered', 'read')
             AND metadata->>'source' IS DISTINCT FROM $4 LIMIT 1`,
          [row.id, inbound.rows[0].created_at, inbound.rows[0].id, CHANGE_REQUEST_ACK_SOURCE]);
        if (humanReply.rows[0]) skipReason = "human_already_replied";
      }
    }
    if (skipReason) {
      await queryWithClient(client,
        `UPDATE approved_template_button_events
         SET response_payload = response_payload || jsonb_build_object('acknowledgement_skipped', $2::text)
         WHERE provider_message_id = $1`, [candidate.provider_message_id, skipReason]);
      return null;
    }

    const metadata = {
      source: CHANGE_REQUEST_ACK_SOURCE,
      origem: "bot",
      idempotency_key: key,
      inbound_wa_message_id: candidate.provider_message_id,
      template_message_id: candidate.template_message_id,
      agendamento_id: candidate.agendamento_id
    };
    const inserted = await queryWithClient<{ id: string }>(client,
      `INSERT INTO messages (conversation_id, from_me, body, type, metadata, status, created_at)
       VALUES ($1, TRUE, $2, 'text', $3::jsonb, 'pending', now()) RETURNING id`,
      [row!.id, CHANGE_REQUEST_ACK_TEXT, JSON.stringify(metadata)]);
    return { messageId: inserted.rows[0].id, destination: candidate.destination, conversationId: row!.id };
  });
}

async function sendAcknowledgement(candidate: PendingAcknowledgement): Promise<void> {
  const reservation = await reserveAcknowledgement(candidate);
  if (!reservation) return;
  const phoneNumberId = String(process.env.PHONE_NUMBER_ID || "").trim();
  const accessToken = String(process.env.WHATSAPP_ACCESS_TOKEN || "").trim();
  if (!phoneNumberId || !accessToken) {
    await query("UPDATE messages SET status = 'failed' WHERE id = $1", [reservation.messageId]);
    logger.error("WhatsApp change-request acknowledgement credentials unavailable", {
      providerMessageId: candidate.provider_message_id
    });
    return;
  }

  try {
    // A timeout is ambiguous: one attempt only, and an existing reservation
    // is never sent again automatically, even if its status becomes failed.
    const response = await sendWhatsAppMessageWithRetry({
      phoneNumberId, accessToken,
      to: whatsappGraphRecipient(reservation.destination),
      body: CHANGE_REQUEST_ACK_TEXT, type: "text", maxAttempts: 1
    });
    const waMessageId = response.messages?.[0]?.id;
    if (!waMessageId) throw new Error("Graph response has no message id");
    await query("UPDATE messages SET status = 'sent', wa_message_id = $2 WHERE id = $1",
      [reservation.messageId, waMessageId]);
  } catch (error) {
    await query("UPDATE messages SET status = 'failed' WHERE id = $1", [reservation.messageId]);
    logger.error("WhatsApp change-request acknowledgement send failed", {
      providerMessageId: candidate.provider_message_id,
      message: error instanceof Error ? error.message : String(error)
    });
    return;
  }
  try {
    await query("UPDATE conversations SET last_activity_at = now(), updated_at = now() WHERE id = $1",
      [reservation.conversationId]);
  } catch (error) {
    // The provider and message record already succeeded; a failed activity
    // update must not relabel the delivery as failed.
    logger.warn("WhatsApp change-request acknowledgement activity update failed", {
      providerMessageId: candidate.provider_message_id,
      message: error instanceof Error ? error.message : String(error)
    });
  }
}

/** Reconcile committed intents after webhook commit or process restart. */
export function runPendingChangeRequestAcknowledgements(): Promise<void> {
  if (shuttingDown) return Promise.resolve();
  if (activeRun) return activeRun;
  const run = (async () => {
    // A reserved message may have reached Graph before a process crashed.
    // Surface it for review, never send it a second time automatically.
    await markStaleReservations();
    for (const candidate of await findPendingAcknowledgements(50)) {
      if (shuttingDown) break;
      try {
        await sendAcknowledgement(candidate);
      } catch (error) {
        logger.error("WhatsApp change-request acknowledgement processing failed", {
          providerMessageId: candidate.provider_message_id,
          message: error instanceof Error ? error.message : String(error)
        });
      }
    }
  })();
  activeRun = run.finally(() => { activeRun = null; });
  return activeRun;
}

export function startChangeRequestAcknowledgementWorker(): void {
  if (workerTimer) return;
  shuttingDown = false;
  workerTimer = setInterval(() => {
    void runPendingChangeRequestAcknowledgements().catch((error) => {
      logger.error("WhatsApp change-request acknowledgement worker failed", {
        message: error instanceof Error ? error.message : String(error)
      });
    });
  }, 15_000);
  void runPendingChangeRequestAcknowledgements().catch((error) => {
    logger.error("WhatsApp change-request acknowledgement worker failed on startup", {
      message: error instanceof Error ? error.message : String(error)
    });
  });
}

export async function shutdownChangeRequestAcknowledgementWorker(): Promise<void> {
  shuttingDown = true;
  if (workerTimer) clearInterval(workerTimer);
  workerTimer = null;
  if (activeRun) {
    try {
      await activeRun;
    } catch (error) {
      logger.error("Change-request acknowledgement worker failed during shutdown", {
        message: error instanceof Error ? error.message : String(error)
      });
    }
  }
}
