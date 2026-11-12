import { Request, Response } from "express";
import { PoolClient } from "pg";
import {
  extractDbErrorDetails,
  query,
  queryWithClient,
  withTransaction
} from "../services/dbService";
import { verifyXHubSignature } from "../utils/signature";
import { logger } from "../utils/logger";
import { sha256HexFromBuffer } from "../utils/hash";
import {
  WebhookChangeValue,
  WebhookContact,
  WebhookMessage,
  WebhookPayload,
  WebhookStatusEvent
} from "../types/whatsapp";
import { handleAgendaButtonReply } from "../services/agendaButtonService";
import { handleApprovedTemplateButtonReply } from "../services/approvedTemplateButtonService";
import { runPendingChangeRequestAcknowledgements } from "../services/changeRequestAcknowledgementService";
import { notifyPushForInboundMessage } from "../services/whatsappPushNotificationService";
import { canonicalWhatsAppIdentity } from "../utils/phoneNumber";

interface WebhookEventRow {
  id: string;
  payload: WebhookPayload;
  processing_status: string;
}

interface StoredWebhookEventResult {
  eventId: string;
  inserted: boolean;
}

const verifyToken = process.env.WHATSAPP_VERIFY_TOKEN;
const appSecret = process.env.WHATSAPP_APP_SECRET;
const allowUnsigned = process.env.WEBHOOK_ALLOW_UNSIGNED === "true" && process.env.NODE_ENV !== "production";

export function extractMessageBody(message: WebhookMessage): string {
  const type = message.type;

  switch (type) {
    case "text":
      return message.text?.body ?? "";
    case "button":
      return message.button?.text ?? "";
    case "interactive":
      return JSON.stringify(message.interactive ?? {});
    case "image":
      return message.image?.caption ?? "[image]";
    case "audio":
      return "[audio]";
    case "video":
      return message.video?.caption ?? "[video]";
    case "document":
      return message.document?.filename ?? "[document]";
    case "reaction": {
      const emoji = message.reaction?.emoji;
      return emoji ? `Reagiu com ${emoji}` : "Removeu a reação";
    }
    default:
      return "";
  }
}

function normalizeObjectType(payload: WebhookPayload): string | null {
  if (typeof payload.object === "string") {
    return payload.object;
  }

  return null;
}

function normalizeProviderTimestamp(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.trunc(value);
  }

  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }

  return null;
}

function formatProcessingError(error: unknown): string {
  const details = extractDbErrorDetails(error);
  const text = JSON.stringify(details);
  return text.length > 4000 ? text.slice(0, 4000) : text;
}

async function touchConversation(
  conversationId: string,
  client: PoolClient,
  lastInboundAt: Date | null = null
): Promise<void> {
  await queryWithClient(
    client,
    `
      UPDATE conversations
      SET updated_at = now(),
          last_activity_at = now(),
          status = CASE
            WHEN $2::timestamptz IS NOT NULL AND status IN ('pending', 'closed') THEN 'open'
            ELSE status
          END,
          last_inbound_at = CASE
            WHEN $2::timestamptz IS NULL THEN last_inbound_at
            WHEN last_inbound_at IS NULL OR last_inbound_at < $2::timestamptz THEN $2::timestamptz
            ELSE last_inbound_at
          END
      WHERE id = $1
    `,
    [conversationId, lastInboundAt]
  );
}

function inboundMessageObservedAt(timestamp: unknown): Date {
  const providerTimestamp = normalizeProviderTimestamp(timestamp);
  if (providerTimestamp === null) {
    return new Date();
  }

  const providerDate = new Date(providerTimestamp * 1000);
  return Number.isNaN(providerDate.getTime()) ? new Date() : providerDate;
}

async function upsertConversation(
  client: PoolClient,
  phone: string,
  waPsid?: string | null,
  subject?: string | null
): Promise<{ id: string }> {
  try {
    const upsertResult = await queryWithClient<{ id: string }>(
      client,
      `
        INSERT INTO conversations (
          wa_phone_number,
          wa_psid,
          subject,
          status,
          last_activity_at,
          created_at,
          updated_at
        )
        VALUES ($1, $2, $3, 'open', now(), now(), now())
        ON CONFLICT (wa_phone_number)
        DO UPDATE SET
          wa_psid = COALESCE(EXCLUDED.wa_psid, conversations.wa_psid),
          subject = COALESCE(conversations.subject, EXCLUDED.subject),
          updated_at = now(),
          last_activity_at = now()
        RETURNING id
      `,
      [phone, waPsid ?? null, subject ?? null]
    );

    return { id: upsertResult.rows[0].id };
  } catch (error) {
    const details = extractDbErrorDetails(error);
    const code = typeof details.code === "string" ? details.code : "";

    if (code === "23505" && waPsid) {
      const existingByPsid = await queryWithClient<{ id: string }>(
        client,
        `
          SELECT id
          FROM conversations
          WHERE wa_psid = $1
          LIMIT 1
        `,
        [waPsid]
      );

      if (existingByPsid.rowCount && existingByPsid.rows[0]) {
        const existingId = existingByPsid.rows[0].id;

        await queryWithClient(
          client,
          `
            UPDATE conversations
            SET subject = COALESCE(subject, $2),
                updated_at = now(),
                last_activity_at = now()
            WHERE id = $1
          `,
          [existingId, subject ?? null]
        );

        return { id: existingId };
      }
    }

    throw error;
  }
}

async function insertInboundMessage(
  client: PoolClient,
  params: {
    conversationId: string;
    waMessageId: string | null;
    body: string;
    type: string;
    metadata: Record<string, unknown>;
  }
): Promise<boolean> {
  const result = await queryWithClient<{ id: string }>(
    client,
    `
      INSERT INTO messages (
        conversation_id,
        wa_message_id,
        from_me,
        body,
        type,
        metadata,
        status,
        created_at
      )
      VALUES ($1, $2, false, $3, $4, $5::jsonb, 'received', now())
      ON CONFLICT (wa_message_id)
      DO NOTHING
      RETURNING id
    `,
    [
      params.conversationId,
      params.waMessageId,
      params.body,
      params.type,
      JSON.stringify(params.metadata)
    ]
  );

  if (result.rowCount === 0) {
    logger.debug("Ignoring duplicate webhook message based on wa_message_id", {
      waMessageId: params.waMessageId
    });
    return false;
  }

  return true;
}

async function handleContacts(value: WebhookChangeValue, client: PoolClient): Promise<void> {
  const contacts = value.contacts ?? [];

  for (const contact of contacts) {
    const waId = contact.wa_id;
    if (!waId) {
      continue;
    }

    const identity = canonicalWhatsAppIdentity(waId);
    const conversation = await upsertConversation(
      client,
      identity,
      identity,
      contact.profile?.name ?? null
    );

    await queryWithClient(
      client,
      `
        INSERT INTO audit_logs (conversation_id, action, payload, created_at)
        VALUES ($1, 'contact_update', $2::jsonb, now())
      `,
      [
        conversation.id,
        JSON.stringify({
          source: "webhook.contacts",
          wa_id: contact.wa_id ?? null,
          profile_name: contact.profile?.name ?? null
        })
      ]
    );
  }
}

async function handleInboundMessages(value: WebhookChangeValue, client: PoolClient): Promise<void> {
  const messages = value.messages ?? [];
  const contactsByWaId = new Map<string, WebhookContact>();

  for (const contact of value.contacts ?? []) {
    if (contact.wa_id) {
      contactsByWaId.set(canonicalWhatsAppIdentity(contact.wa_id), contact);
    }
  }

  for (const message of messages) {
    const from = message.from;
    if (!from) {
      continue;
    }

    const identity = canonicalWhatsAppIdentity(from);
    const contact = contactsByWaId.get(identity);
    const conversation = await upsertConversation(
      client,
      identity,
      contact?.wa_id ? canonicalWhatsAppIdentity(contact.wa_id) : identity,
      contact?.profile?.name ?? null
    );

    const inserted = await insertInboundMessage(client, {
      conversationId: conversation.id,
      waMessageId: message.id ?? null,
      body: extractMessageBody(message),
      type: message.type ?? "text",
      metadata: {
        contact,
        message,
        metadata: value.metadata
      }
    });

    if (inserted) {
      // The conversation upsert already holds the same lock used by scheduling.
      // Only a newly persisted inbound bumps the version; provider retries do not.
      await client.query(`UPDATE conversation_follow_ups
        SET inbound_received_at = COALESCE(inbound_received_at, now()), revision = revision + 1, updated_at = now()
        WHERE conversation_id = $1 AND status = 'pending'`, [conversation.id]);
      const reservationReceipt = await handleAgendaButtonReply(client, message);
      const templateReceipt = await handleApprovedTemplateButtonReply(client, message);
      const agendaReceipt = reservationReceipt ?? templateReceipt;
      if (agendaReceipt) {
        // This annotation is ours, never copied from the provider payload.
        await queryWithClient(client, `UPDATE messages
          SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('agenda_receipt', $2::jsonb)
          WHERE wa_message_id = $1 AND conversation_id = $3 AND from_me = FALSE`,
        [message.id, JSON.stringify(agendaReceipt), conversation.id]);
      }
      await touchConversation(
        conversation.id,
        client,
        inboundMessageObservedAt(message.timestamp)
      );
      void notifyPushForInboundMessage({
        conversationId: conversation.id,
        contactLabel: contact?.profile?.name ?? identity,
        bodyPreview: extractMessageBody(message),
        waPhoneNumber: identity,
        waMessageId: message.id ?? null,
        messageType: message.type ?? "text",
        messageTimestamp: inboundMessageObservedAt(message.timestamp).toISOString()
      });
    }
  }
}

async function recordStatusEvent(client: PoolClient, statusEvent: WebhookStatusEvent): Promise<void> {
  const waMessageId = statusEvent.id;
  if (!waMessageId) {
    return;
  }

  const status = statusEvent.status ?? "received";
  const providerTimestamp = normalizeProviderTimestamp(statusEvent.timestamp);

  const updatedMessage = await queryWithClient<{ conversation_id: string | null }>(
    client,
    `
      UPDATE messages
      SET status = $1,
          metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb
      WHERE wa_message_id = $3
      RETURNING conversation_id
    `,
    [status, JSON.stringify({ latest_status_event: statusEvent }), waMessageId]
  );

  const conversationId = updatedMessage.rows[0]?.conversation_id ?? null;

  await queryWithClient(
    client,
    `
      INSERT INTO message_status_events (
        wa_message_id,
        conversation_id,
        status,
        provider_timestamp,
        payload,
        created_at
      )
      VALUES ($1, $2, $3, $4, $5::jsonb, now())
      ON CONFLICT (wa_message_id, status, provider_timestamp)
      DO NOTHING
    `,
    [waMessageId, conversationId, status, providerTimestamp, JSON.stringify(statusEvent)]
  );

  if (conversationId) {
    await touchConversation(conversationId, client);
  }
}

async function handleStatuses(value: WebhookChangeValue, client: PoolClient): Promise<void> {
  for (const statusEvent of value.statuses ?? []) {
    await recordStatusEvent(client, statusEvent);
  }
}

async function processWebhookPayload(payload: WebhookPayload, client: PoolClient): Promise<void> {
  if (payload.object !== "whatsapp_business_account") {
    logger.warn("Ignoring unsupported webhook object", { object: payload.object });
    return;
  }

  for (const entry of payload.entry ?? []) {
    for (const change of entry.changes ?? []) {
      if (change.field !== "messages" || !change.value) {
        continue;
      }

      const configuredPhoneNumberId = String(process.env.PHONE_NUMBER_ID || "").trim();
      const eventPhoneNumberId = String(change.value.metadata?.phone_number_id || "").trim();
      if (configuredPhoneNumberId && eventPhoneNumberId && configuredPhoneNumberId !== eventPhoneNumberId) {
        logger.warn("Ignoring webhook event for an unexpected phone_number_id", {
          phoneNumberId: eventPhoneNumberId
        });
        continue;
      }

      await handleContacts(change.value, client);
      await handleInboundMessages(change.value, client);
      await handleStatuses(change.value, client);
    }
  }
}

async function storeWebhookEvent(params: {
  payload: WebhookPayload;
  rawBody: Buffer;
  signatureHeader?: string;
}): Promise<StoredWebhookEventResult> {
  const payloadHash = sha256HexFromBuffer(params.rawBody);
  const insertResult = await query<{ id: string }>(
    `
      INSERT INTO webhook_events (
        payload,
        raw_body,
        payload_hash,
        signature_header,
        object_type,
        processing_status,
        received_at
      )
      VALUES ($1::jsonb, $2, $3, $4, $5, 'pending', now())
      ON CONFLICT (payload_hash)
      DO NOTHING
      RETURNING id
    `,
    [
      JSON.stringify(params.payload),
      params.rawBody.toString("utf8"),
      payloadHash,
      params.signatureHeader ?? null,
      normalizeObjectType(params.payload)
    ]
  );

  if (insertResult.rowCount && insertResult.rows[0]) {
    return {
      eventId: insertResult.rows[0].id,
      inserted: true
    };
  }

  const existingResult = await query<{ id: string }>(
    `
      SELECT id
      FROM webhook_events
      WHERE payload_hash = $1
      LIMIT 1
    `,
    [payloadHash]
  );

  if (existingResult.rowCount && existingResult.rows[0]) {
    return {
      eventId: existingResult.rows[0].id,
      inserted: false
    };
  }

  throw new Error("Unable to persist webhook event and existing hash row was not found");
}

async function processWebhookEvent(eventId: string): Promise<void> {
  try {
    const status = await withTransaction(async (client) => {
      const eventResult = await queryWithClient<WebhookEventRow>(
        client,
        `
          SELECT id, payload, processing_status
          FROM webhook_events
          WHERE id = $1
          FOR UPDATE
        `,
        [eventId]
      );

      if (eventResult.rowCount === 0 || !eventResult.rows[0]) {
        return "missing" as const;
      }

      const event = eventResult.rows[0];

      if (event.processing_status === "processed") {
        return "already_processed" as const;
      }

      if (event.processing_status === "processing") {
        return "already_processing" as const;
      }

      await queryWithClient(
        client,
        `
          UPDATE webhook_events
          SET processing_status = 'processing',
              processing_error = NULL
          WHERE id = $1
        `,
        [eventId]
      );

      await processWebhookPayload(event.payload, client);

      await queryWithClient(
        client,
        `
          UPDATE webhook_events
          SET processing_status = 'processed',
              processing_error = NULL,
              processed_at = now()
          WHERE id = $1
        `,
        [eventId]
      );

      return "processed" as const;
    });

    if (status === "processed") {
      // The callback and inbound message are committed before any external send.
      void runPendingChangeRequestAcknowledgements().catch((error) => {
        logger.error("Failed to dispatch pending change-request acknowledgement", {
          message: error instanceof Error ? error.message : String(error)
        });
      });
    }

    if (status === "already_processed") {
      logger.debug("Webhook event already processed", { eventId });
    }

    if (status === "already_processing") {
      logger.debug("Webhook event is already being processed", { eventId });
    }

    if (status === "missing") {
      logger.warn("Webhook event row not found during processing", { eventId });
    }
  } catch (error) {
    const processingError = formatProcessingError(error);

    try {
      await query(
        `
          UPDATE webhook_events
          SET processing_status = 'failed',
              processing_error = $2
          WHERE id = $1
            AND processing_status <> 'processed'
        `,
        [eventId, processingError]
      );
    } catch (markError) {
      logger.error("Failed to mark webhook event as failed", {
        eventId,
        details: extractDbErrorDetails(markError)
      });
    }

    logger.error("Webhook background processing failed", {
      eventId,
      details: extractDbErrorDetails(error)
    });
  }
}

export function verifyWebhook(req: Request, res: Response): void {
  const mode = req.query["hub.mode"];
  const token = req.query["hub.verify_token"];
  const challenge = req.query["hub.challenge"];

  if (mode === "subscribe" && token === verifyToken && typeof challenge === "string") {
    res.status(200).type("text/plain").send(challenge);
    return;
  }

  res.sendStatus(403);
}

export function receiveWebhook(req: Request, res: Response): void {
  const signatureHeader = req.header("x-hub-signature-256") ?? undefined;

  if (!allowUnsigned) {
    if (!appSecret || !verifyXHubSignature(req.rawBody, signatureHeader, appSecret)) {
      logger.warn("Webhook signature validation failed");
      res.sendStatus(401);
      return;
    }
  } else if (appSecret && signatureHeader && !verifyXHubSignature(req.rawBody, signatureHeader, appSecret)) {
    logger.warn("Webhook signature validation failed in debug mode");
    res.sendStatus(401);
    return;
  }

  const payload = req.body as WebhookPayload;

  if (!req.rawBody) {
    logger.error("Webhook raw body is missing and event cannot be persisted safely");
    res.sendStatus(503);
    return;
  }

  void storeWebhookEvent({
    payload,
    rawBody: req.rawBody,
    signatureHeader
  })
    .then((storedEvent) => {
      res.sendStatus(200);

      if (!storedEvent.inserted) {
        logger.debug("Webhook duplicate detected via payload hash", { eventId: storedEvent.eventId });
      }

      void processWebhookEvent(storedEvent.eventId);
    })
    .catch((error) => {
      logger.error("Failed to persist webhook event", {
        details: extractDbErrorDetails(error)
      });
      res.sendStatus(503);
    });
}
