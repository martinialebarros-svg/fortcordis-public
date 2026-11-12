import { Request, Response } from "express";
import { query, withTransaction } from "../services/dbService";
import {
  downloadWhatsAppMedia,
  sendWhatsAppDocumentMessageWithRetry,
  sendWhatsAppMessageWithRetry,
  uploadWhatsAppDocumentWithRetry
} from "../services/whatsappService";
import {
  CustomerServiceWindow,
  describeCustomerServiceWindow
} from "../services/customerServiceWindow";
import { logger } from "../utils/logger";
import { canonicalWhatsAppIdentity, digitsOnly, whatsappGraphRecipient } from "../utils/phoneNumber";

import { FOLLOW_UP_JOIN, FOLLOW_UP_JSON, FOLLOW_UP_ACTIVE, FOLLOW_UP_DUE, FOLLOW_UP_READY, FOLLOW_UP_TODAY, validId } from "./followUpsController";

const whatsappAccessToken = process.env.WHATSAPP_ACCESS_TOKEN;
const phoneNumberId = process.env.PHONE_NUMBER_ID;

const ATTACHMENT_EXTENSION_MIME_TYPES: Record<string, string> = {
  ".pdf": "application/pdf",
  ".doc": "application/msword",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xls": "application/vnd.ms-excel",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".ppt": "application/vnd.ms-powerpoint",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".csv": "text/csv",
  ".txt": "text/plain"
};

const GENERIC_ATTACHMENT_MIME_TYPES = new Set(["", "application/octet-stream", "application/binary"]);

function resolveAttachmentMimeType(filename: string, reportedMimeType: string): string | null {
  const extension = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  const expectedMimeType = ATTACHMENT_EXTENSION_MIME_TYPES[extension];
  if (!expectedMimeType) return null;
  if (reportedMimeType === expectedMimeType || GENERIC_ATTACHMENT_MIME_TYPES.has(reportedMimeType)) {
    return expectedMimeType;
  }
  return null;
}

const WHATSAPP_DOCUMENT_CAPTION_MAX_LENGTH = 1024;

interface ConversationRow {
  id: string;
  wa_phone_number: string;
  last_inbound_at: Date | string | null;
  [key: string]: unknown;
}

interface PendingMessageReservation {
  id: string;
  wa_message_id: string | null;
  status: string;
  idempotent: boolean;
}

const CONVERSATION_STATUSES = ["open", "pending", "closed"] as const;
type ConversationStatus = (typeof CONVERSATION_STATUSES)[number];

export function isConversationStatus(value: unknown): value is ConversationStatus {
  return typeof value === "string" && CONVERSATION_STATUSES.includes(value as ConversationStatus);
}

function parsePositiveInt(input: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(input ?? "", 10);
  if (Number.isNaN(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

const UNREAD_CONVERSATION_SQL = `(
  c.last_inbound_at IS NOT NULL
  AND (c.last_seen_at IS NULL OR c.last_inbound_at > c.last_seen_at)
)`;

// A domain receipt resolves only its own button. It cannot answer an earlier
// question, remove the history/frontier, or resolve a request for human review.
const SUCCESSFUL_AGENDA_RECEIPT_SQL = `COALESCE((m.type = 'button' AND (
  (m.metadata->'agenda_receipt'->>'source' = 'appointmentReminder'
    AND m.metadata->'agenda_receipt'->>'action' = 'confirmar_presenca'
    AND m.metadata->'agenda_receipt'->>'result' = 'presenca_confirmada'
    AND m.metadata->'agenda_receipt'->>'status' IN ('Agendado', 'Confirmado'))
  OR (m.metadata->'agenda_receipt'->>'source' = 'reservation'
    AND m.metadata->'agenda_receipt'->>'action' = 'confirmar'
    AND m.metadata->'agenda_receipt'->>'result' IN ('confirmado', 'ja_confirmado')
    AND m.metadata->'agenda_receipt'->>'status' = 'Confirmado')
)), FALSE)`;

// Delivery failures, reading the inbox and an automatic change-request
// acknowledgement do not resolve a request awaiting human review. Retry may
// reuse an outbound ID and refresh created_at, so use the history's tuple order
// for replies, and the persisted ID frontier only for explicit resolution.
const REPLY_QUEUE_JOINS_SQL = `
  LEFT JOIN LATERAL (
    SELECT m.id, m.created_at
    FROM messages m
    WHERE m.conversation_id = c.id AND m.from_me = TRUE
      AND m.status IN ('sent', 'delivered', 'read')
      AND m.metadata->>'source' IS DISTINCT FROM 'approved_template_button.solicitar_alteracao_ack'
    ORDER BY m.created_at DESC, m.id DESC
    LIMIT 1
  ) successful_reply ON true
  LEFT JOIN LATERAL (
    SELECT m.id, m.created_at AS waiting_since
    FROM messages m
    WHERE m.conversation_id = c.id AND m.from_me = FALSE
      AND NOT ${SUCCESSFUL_AGENDA_RECEIPT_SQL}
      AND m.id > COALESCE(c.resolved_through_message_id, 0)
      AND (successful_reply.id IS NULL
        OR (m.created_at, m.id) > (successful_reply.created_at, successful_reply.id))
    ORDER BY m.created_at ASC, m.id ASC
    LIMIT 1
  ) reply_queue ON true
`;
const NEEDS_REPLY_SQL = "(reply_queue.id IS NOT NULL)";

// Reactions remain visible in the inbox and its revision frontier. Only the
// bot's conversational context ignores inbound reactions; human activity still
// invalidates an automatic reply. IS DISTINCT FROM keeps legacy NULL types.
const BOT_CONTEXT_MESSAGE_SQL = "(m.from_me IS DISTINCT FROM FALSE OR m.type IS DISTINCT FROM 'reaction')";

function resolveBotContext(req: Request, res: Response): boolean | null {
  const value = req.query.bot_context;
  if (value !== undefined && value !== "true" && value !== "false") {
    res.status(422).json({ error: "bot_context must be true or false" });
    return null;
  }
  if (value === "true" && req.authUser?.authSource !== "internal_token") {
    res.status(403).json({ error: "bot_context requires internal authentication" });
    return null;
  }
  return value === "true";
}

function isPositiveBigInt(value: unknown): value is string {
  return typeof value === "string"
    && /^[1-9]\d*$/.test(value)
    && value.length <= 19
    && BigInt(value) <= 9223372036854775807n;
}

/** Search variants affect lookup only; never rewrite the stored identity or send destination. */
function phoneSearchVariants(search: string): string[] {
  if (!/^[+\d\s().-]+$/.test(search)) return [];
  const digits = digitsOnly(search);
  if (digits.length < 3) return [];

  const variants = new Set([digits, canonicalWhatsAppIdentity(digits)]);
  // Accept a Brazilian DDD + local number pasted without the country code.
  if (/^\d{10,11}$/.test(digits)) {
    variants.add(canonicalWhatsAppIdentity(`55${digits}`));
  }
  return [...variants];
}

async function touchConversation(conversationId: string): Promise<void> {
  await query(
    `
      UPDATE conversations
      SET updated_at = now(),
          last_activity_at = now()
      WHERE id = $1
    `,
    [conversationId]
  );
}

export async function listConversations(req: Request, res: Response): Promise<void> {
  const botContext = resolveBotContext(req, res);
  if (botContext === null) return;
  const page = parsePositiveInt(req.query.page as string | undefined, 1);
  const limit = Math.min(parsePositiveInt(req.query.limit as string | undefined, 20), 100);
  const offset = (page - 1) * limit;

  const status = req.query.status as string | undefined;
  const assigned = req.query.assigned as string | undefined;
  const phone = req.query.phone as string | undefined;
  const search = (req.query.search as string | undefined) || phone;
  const agentId = req.query.agent_id;
  const unread = req.query.unread;
  const needsReply = req.query.needs_reply;
  const followUp = req.query.follow_up;
  const followUpAgentId = req.query.follow_up_agent_id;
  const summaryAgentId = req.query.summary_agent_id;
  if ((followUp !== undefined && !["all", "due", "today", "upcoming", "responded", "ready"].includes(followUp as string))
      || (followUpAgentId !== undefined && !validId(followUpAgentId))
      || (summaryAgentId !== undefined && !validId(summaryAgentId))) {
    res.status(422).json({ error: "Filtro de retorno inválido." }); return;
  }

  if (agentId !== undefined && !isPositiveBigInt(agentId)) {
    res.status(422).json({ error: "agent_id must be a positive integer" });
    return;
  }
  if (unread !== undefined && unread !== "true" && unread !== "false") {
    res.status(422).json({ error: "unread must be true or false" });
    return;
  }
  if (needsReply !== undefined && needsReply !== "true" && needsReply !== "false") {
    res.status(422).json({ error: "needs_reply must be true or false" });
    return;
  }
  if (search !== undefined && typeof search !== "string") {
    res.status(422).json({ error: "search must be a string" });
    return;
  }

  const whereClauses: string[] = [];
  const params: unknown[] = [];

  if (followUp !== undefined) {
    const filters: Record<string, string> = {
      all: FOLLOW_UP_ACTIVE, due: FOLLOW_UP_DUE, today: FOLLOW_UP_TODAY,
      ready: FOLLOW_UP_READY,
      upcoming: `(${FOLLOW_UP_ACTIVE} AND follow_up.due_at >= (date_trunc('day', now() AT TIME ZONE 'America/Fortaleza') + interval '1 day') AT TIME ZONE 'America/Fortaleza')`,
      responded: `(${FOLLOW_UP_ACTIVE} AND follow_up.inbound_received_at IS NOT NULL)`,
    };
    whereClauses.push(filters[followUp as string]);
  }
  if (followUpAgentId !== undefined) {
    params.push(followUpAgentId);
    whereClauses.push(`(${FOLLOW_UP_ACTIVE} AND follow_up.agent_id = $${params.length})`);
  }

  if (status) {
    params.push(status);
    whereClauses.push(`c.status = $${params.length}`);
  }

  if (assigned === "assigned") {
    whereClauses.push("c.last_agent_id IS NOT NULL");
  }

  if (assigned === "unassigned") {
    whereClauses.push("c.last_agent_id IS NULL");
  }

  if (agentId !== undefined) {
    params.push(agentId);
    whereClauses.push(`c.last_agent_id = $${params.length}`);
  }

  if (unread !== undefined) {
    whereClauses.push(`${UNREAD_CONVERSATION_SQL} = ${unread === "true" ? "TRUE" : "FALSE"}`);
  }
  if (needsReply !== undefined) {
    whereClauses.push(`${NEEDS_REPLY_SQL} = ${needsReply === "true" ? "TRUE" : "FALSE"}`);
  }

  if (search?.trim()) {
    params.push(`%${search.trim()}%`);
    const searchConditions = [`
      c.wa_phone_number ILIKE $${params.length}
      OR COALESCE(c.subject, '') ILIKE $${params.length}
      OR COALESCE(last_message.body, '') ILIKE $${params.length}
    `];
    for (const variant of phoneSearchVariants(search.trim())) {
      params.push(`%${variant}%`);
      searchConditions.push(`c.wa_phone_number ILIKE $${params.length}`);
    }
    whereClauses.push(`(${searchConditions.join(" OR ")})`);
  }

  const whereSql = whereClauses.length > 0 ? `WHERE ${whereClauses.join(" AND ")}` : "";
  const joinsSql = `
    ${REPLY_QUEUE_JOINS_SQL}
    ${FOLLOW_UP_JOIN}
    LEFT JOIN agents assigned_agent ON assigned_agent.id = c.last_agent_id
    LEFT JOIN LATERAL (
      SELECT MAX(m.id)::text AS last_message_id
      FROM messages m WHERE m.conversation_id = c.id
    ) message_revision ON true
    LEFT JOIN LATERAL (
      SELECT m.body, m.created_at, m.from_me, m.type, m.wa_message_id, m.metadata
      FROM messages m
      WHERE m.conversation_id = c.id
        ${botContext ? `AND ${BOT_CONTEXT_MESSAGE_SQL}` : ""}
      ORDER BY m.created_at DESC, m.id DESC
      LIMIT 1
    ) last_message ON true
  `;

  const dataParams = [...params, limit, offset];
  const [totalResult, dataResult, summaryResult] = await Promise.all([
    query<{ total: string }>(
      `SELECT COUNT(*)::text AS total FROM conversations c ${search?.trim() ? joinsSql : `${FOLLOW_UP_JOIN} ${needsReply !== undefined ? REPLY_QUEUE_JOINS_SQL : ""}`} ${whereSql}`,
      params
    ),
    query<ConversationRow>(
    `
      SELECT
        c.*,
        ${FOLLOW_UP_JSON} AS follow_up,
        ${UNREAD_CONVERSATION_SQL} AS unread,
        ${NEEDS_REPLY_SQL} AS needs_reply,
        reply_queue.waiting_since,
        message_revision.last_message_id,
        assigned_agent.name AS assigned_agent_name,
        assigned_agent.email AS assigned_agent_email,
        last_message.body AS last_message_body,
        last_message.created_at AS last_message_at,
        last_message.from_me AS last_message_from_me,
        last_message.type AS last_message_type,
        last_message.wa_message_id AS last_message_wa_message_id,
        last_message.metadata->>'origem' AS last_message_origem
      FROM conversations c
      ${joinsSql}
      ${whereSql}
      ORDER BY
        ${followUp !== undefined ? "COALESCE(follow_up.inbound_received_at, follow_up.due_at) ASC, c.id ASC," : ""}
        ${needsReply === "true" ? "reply_queue.waiting_since ASC NULLS LAST, reply_queue.id ASC," : ""}
        unread DESC,
        CASE WHEN ${UNREAD_CONVERSATION_SQL} THEN c.last_inbound_at END ASC NULLS LAST,
        c.last_activity_at DESC,
        c.id DESC
      LIMIT $${dataParams.length - 1}
      OFFSET $${dataParams.length}
    `,
    dataParams
    ),
    query<Record<string, string>>(
      `SELECT
        COUNT(*)::text AS total,
        COUNT(*) FILTER (WHERE ${FOLLOW_UP_DUE})::text AS follow_up_due,
        COUNT(*) FILTER (WHERE ${FOLLOW_UP_READY})::text AS follow_up_ready,
        COUNT(*) FILTER (WHERE ${FOLLOW_UP_READY} AND follow_up.agent_id = $1)::text AS my_follow_up_ready,
        COUNT(*) FILTER (WHERE ${UNREAD_CONVERSATION_SQL})::text AS unread,
        COUNT(*) FILTER (WHERE ${NEEDS_REPLY_SQL})::text AS needs_reply,
        COUNT(*) FILTER (WHERE c.last_agent_id IS NULL)::text AS unassigned,
        COUNT(*) FILTER (WHERE c.status = 'open')::text AS open,
        COUNT(*) FILTER (WHERE c.status = 'pending')::text AS pending,
        COUNT(*) FILTER (WHERE c.status = 'closed')::text AS closed
        ${agentId === undefined ? "" : ", COUNT(*) FILTER (WHERE c.last_agent_id = $2)::text AS mine"}
       FROM conversations c ${REPLY_QUEUE_JOINS_SQL} ${FOLLOW_UP_JOIN}`,
      agentId === undefined ? [summaryAgentId ?? null] : [summaryAgentId ?? null, agentId]
    )
  ]);

  res.json({
    data: dataResult.rows.map((conversation) => ({
      ...conversation,
      customer_service_window: describeCustomerServiceWindow(conversation.last_inbound_at)
    })),
    pagination: {
      page,
      limit,
      total: Number.parseInt(totalResult.rows[0]?.total ?? "0", 10)
    },
    // Queue totals intentionally ignore list filters and pagination.
    summary: Object.fromEntries(
      Object.entries(summaryResult.rows[0]).map(([key, value]) => [key, Number.parseInt(value, 10)])
    )
  });
}

export async function updateConversationStatus(req: Request, res: Response): Promise<void> {
  const conversationId = req.params.id;
  const nextStatus = req.body?.status;
  const expectedLastMessageId = req.body?.expected_last_message_id;

  if (!isConversationStatus(nextStatus)) {
    res.status(422).json({
      error: `status must be one of: ${CONVERSATION_STATUSES.join(", ")}`
    });
    return;
  }
  if (expectedLastMessageId !== undefined && expectedLastMessageId !== null && !isPositiveBigInt(expectedLastMessageId)) {
    res.status(422).json({ error: "expected_last_message_id must be a positive integer string or null" });
    return;
  }

  const result = await withTransaction(async (client) => {
    const current = await client.query<ConversationRow>(
      `SELECT * FROM conversations WHERE id = $1 FOR UPDATE`,
      [conversationId]
    );

    const conversation = current.rows[0];
    if (!conversation) {
      return { notFound: true as const };
    }

    // The inbound upsert holds this same conversation lock before inserting.
    // A later inbound therefore either causes this comparison to fail, or is
    // inserted after commit and reopens the conversation without being covered.
    const revision = await client.query<{ last_message_id: string | null }>(
      `SELECT MAX(id)::text AS last_message_id FROM messages WHERE conversation_id = $1`,
      [conversationId]
    );
    const lastMessageId = revision.rows[0].last_message_id;
    if (nextStatus === "closed" && expectedLastMessageId !== undefined && expectedLastMessageId !== lastMessageId) {
      return { conflict: true as const, lastMessageId };
    }

    const resolvedThroughMessageId = nextStatus === "closed"
      ? lastMessageId ?? "0"
      : conversation.resolved_through_message_id;
    const changed = conversation.status !== nextStatus
      || conversation.resolved_through_message_id !== resolvedThroughMessageId;

    if (changed) {
      await client.query(
        `UPDATE conversations
         SET status = $2, resolved_through_message_id = $3, updated_at = now()
         WHERE id = $1`,
        [conversationId, nextStatus, resolvedThroughMessageId]
      );
      await client.query(
        `INSERT INTO audit_logs (conversation_id, action, payload, created_at)
         VALUES ($1, 'conversation_status_changed', $2::jsonb, now())`,
        [conversationId, JSON.stringify({
          source: "api.conversation_status",
          previous_status: conversation.status,
          status: nextStatus,
          resolved_through_message_id: resolvedThroughMessageId
        })]
      );
    }
    const updated = await client.query<ConversationRow>(
      `SELECT c.*, ${NEEDS_REPLY_SQL} AS needs_reply, reply_queue.waiting_since
       FROM conversations c ${REPLY_QUEUE_JOINS_SQL} WHERE c.id = $1`,
      [conversationId]
    );

    return { conversation: { ...updated.rows[0], last_message_id: lastMessageId }, changed };
  });

  if ("notFound" in result) {
    res.status(404).json({ error: "Conversation not found" });
    return;
  }
  if ("conflict" in result) {
    res.status(409).json({
      error: "A conversa recebeu novas mensagens. Revise o histórico antes de resolver.",
      code: "CONVERSATION_CHANGED",
      last_message_id: result.lastMessageId
    });
    return;
  }

  res.status(200).json({ data: result.conversation, changed: result.changed });
}

export async function markConversationSeen(req: Request, res: Response): Promise<void> {
  const conversationId = req.params.id;

  const result = await query<{ id: string; last_seen_at: string }>(
    `UPDATE conversations
     SET last_seen_at = now()
     WHERE id = $1
     RETURNING id, last_seen_at`,
    [conversationId]
  );

  if (result.rowCount === 0) {
    res.status(404).json({ error: "Conversation not found" });
    return;
  }

  res.status(200).json({ data: result.rows[0] });
}

export async function listConversationMessages(req: Request, res: Response): Promise<void> {
  const botContext = resolveBotContext(req, res);
  if (botContext === null) return;
  const conversationId = req.params.id;
  const page = parsePositiveInt(req.query.page as string | undefined, 1);
  const limit = Math.min(parsePositiveInt(req.query.limit as string | undefined, 50), 200);
  const offset = (page - 1) * limit;
  const order = req.query.order;
  if (order !== undefined && order !== "latest" && order !== "oldest") {
    res.status(422).json({ error: "order must be latest or oldest" });
    return;
  }
  const latestFirst = order === "latest";
  const sortDirection = latestFirst ? "DESC" : "ASC";

  const conversation = await query<{ id: string; last_inbound_at: Date | string | null }>(
    `SELECT id, last_inbound_at FROM conversations WHERE id = $1`,
    [conversationId]
  );
  if (conversation.rowCount === 0) {
    res.status(404).json({ error: "Conversation not found" });
    return;
  }

  const totalResult = await query<{ total: string; last_message_id: string | null }>(
    `SELECT COUNT(*) ${botContext ? `FILTER (WHERE ${BOT_CONTEXT_MESSAGE_SQL})` : ""}::text AS total,
      MAX(m.id)::text AS last_message_id FROM messages m WHERE m.conversation_id = $1`,
    [conversationId]
  );

  const dataResult = await query(
    `
      SELECT m.*
      FROM messages m
      WHERE m.conversation_id = $1
        ${botContext ? `AND ${BOT_CONTEXT_MESSAGE_SQL}` : ""}
      ORDER BY m.created_at ${sortDirection}, m.id ${sortDirection}
      LIMIT $2
      OFFSET $3
    `,
    [conversationId, limit, offset]
  );

  res.json({
    data: latestFirst ? dataResult.rows.reverse() : dataResult.rows,
    last_message_id: totalResult.rows[0]?.last_message_id ?? null,
    last_inbound_at: conversation.rows[0]?.last_inbound_at ?? null,
    customer_service_window: describeCustomerServiceWindow(
      conversation.rows[0]?.last_inbound_at ?? null
    ),
    pagination: {
      page,
      limit,
      total: Number.parseInt(totalResult.rows[0]?.total ?? "0", 10)
    }
  });
}

const DOWNLOADABLE_MEDIA_TYPES = new Set(["image", "audio", "video", "document", "sticker"]);

export async function getMessageMedia(req: Request, res: Response): Promise<void> {
  const conversationId = req.params.id;
  const messageId = req.params.messageId;

  const result = await query<{ type: string; metadata: Record<string, unknown> | null; from_me: boolean }>(
    `SELECT type, metadata, from_me FROM messages WHERE id = $1 AND conversation_id = $2`,
    [messageId, conversationId]
  );

  const row = result.rows[0];
  if (!row) {
    res.status(404).json({ error: "Message not found" });
    return;
  }

  if (!DOWNLOADABLE_MEDIA_TYPES.has(row.type)) {
    res.status(422).json({ error: "Message does not have downloadable media" });
    return;
  }

  const rawMessage = (row.metadata?.message ?? {}) as Record<string, unknown>;
  const mediaObject = (rawMessage[row.type] ?? {}) as { id?: unknown; filename?: unknown };
  const approvedTemplateMediaId = row.metadata?.wa_media_id;
  const mediaId = typeof mediaObject.id === "string"
    ? mediaObject.id
    : typeof approvedTemplateMediaId === "string" ? approvedTemplateMediaId : null;
  const filename = typeof mediaObject.filename === "string" && mediaObject.filename
    ? mediaObject.filename
    : typeof row.metadata?.document_filename === "string" ? row.metadata.document_filename : null;

  if (!mediaId) {
    res.status(404).json({ error: "Media reference not found for this message" });
    return;
  }

  if (!whatsappAccessToken) {
    res.status(500).json({ error: "Missing WhatsApp API environment configuration" });
    return;
  }

  try {
    const media = await downloadWhatsAppMedia({ mediaId, accessToken: whatsappAccessToken });
    res.setHeader("Content-Type", media.mimeType);
    res.setHeader("Cache-Control", "private, max-age=3600");
    if (row.type === "document" && filename) {
      const asciiFallback = filename.replace(/[^\x20-\x7E]/g, "_").replace(/"/g, "");
      const encodedFilename = encodeURIComponent(filename);
      res.setHeader(
        "Content-Disposition",
        `inline; filename="${asciiFallback}"; filename*=UTF-8''${encodedFilename}`
      );
    }
    res.send(media.buffer);
  } catch (error) {
    logger.error("Failed to download WhatsApp media", {
      conversationId,
      messageId,
      mediaId,
      message: error instanceof Error ? error.message : String(error)
    });
    res.status(502).json({ error: "Failed to download media from WhatsApp. It may have expired." });
  }
}

async function insertPendingMessage(
  conversationId: string,
  body: string,
  type: string,
  metadata: Record<string, unknown>
): Promise<string> {
  const inserted = await query<{ id: string }>(
    `
      INSERT INTO messages (
        conversation_id,
        from_me,
        body,
        type,
        metadata,
        status,
        created_at
      )
      VALUES ($1, true, $2, $3, $4::jsonb, 'pending', now())
      RETURNING id
    `,
    [conversationId, body, type, JSON.stringify(metadata)]
  );
  return inserted.rows[0].id;
}

export async function reservePendingTextMessage(
  conversationId: string,
  body: string,
  type: string,
  metadata: Record<string, unknown>
): Promise<PendingMessageReservation> {
  const idempotencyKey = typeof metadata.idempotency_key === "string"
    ? metadata.idempotency_key.trim()
    : "";
  if (!idempotencyKey) {
    return {
      id: await insertPendingMessage(conversationId, body, type, metadata),
      wa_message_id: null,
      status: "pending",
      idempotent: false
    };
  }

  return withTransaction(async (client) => {
    await client.query("SELECT pg_advisory_xact_lock(hashtext($1))", [idempotencyKey]);
    const existing = await client.query<{ id: string; wa_message_id: string | null; status: string }>(
      `
        SELECT id, wa_message_id, status
        FROM messages
        WHERE metadata->>'idempotency_key' = $1
        LIMIT 1
      `,
      [idempotencyKey]
    );
    const row = existing.rows[0];
    if (row && (row.status !== "failed" || metadata.source === "bot_auto")) {
      return { ...row, idempotent: true };
    }
    if (metadata.source === "bot_auto") {
      const current = await client.query<{
        last_agent_id: string | null; last_inbound_at: Date | string | null;
        wa_message_id: string | null; from_me: boolean | null;
        message_created_at: Date | string | null;
      }>(`
        SELECT c.last_agent_id, c.last_inbound_at, m.wa_message_id, m.from_me,
          m.created_at AS message_created_at
        FROM conversations c
        LEFT JOIN LATERAL (
          SELECT m.wa_message_id, m.from_me, m.created_at FROM messages m WHERE m.conversation_id = c.id
            AND ${BOT_CONTEXT_MESSAGE_SQL}
          ORDER BY m.created_at DESC, m.id DESC LIMIT 1
        ) m ON true
        WHERE c.id = $1 FOR UPDATE OF c
      `, [conversationId]);
      const latest = current.rows[0];
      if (process.env.WHATSAPP_BOT_AUTO_SEND_ENABLED !== "true" || !latest
          || latest.last_agent_id || latest.from_me !== false
          || latest.wa_message_id !== metadata.inbound_wa_message_id
          || !describeCustomerServiceWindow(latest.last_inbound_at).is_open
          || !describeCustomerServiceWindow(latest.message_created_at).is_open) {
        return { id: "", wa_message_id: null, status: "bot_conversation_changed", idempotent: true };
      }
    }
    if (row) {
      const retried = await client.query<{ id: string; wa_message_id: string | null; status: string }>(
        `
          UPDATE messages
          SET conversation_id = $1,
              body = $2,
              type = $3,
              metadata = $4::jsonb,
              wa_message_id = NULL,
              status = 'pending',
              created_at = now()
          WHERE id = $5
          RETURNING id, wa_message_id, status
        `,
        [conversationId, body, type, JSON.stringify(metadata), row.id]
      );
      return { ...retried.rows[0], idempotent: false };
    }
    const inserted = await client.query<{ id: string; wa_message_id: string | null; status: string }>(
      `
        INSERT INTO messages (
          conversation_id, from_me, body, type, metadata, status, created_at
        )
        VALUES ($1, true, $2, $3, $4::jsonb, 'pending', now())
        RETURNING id, wa_message_id, status
      `,
      [conversationId, body, type, JSON.stringify(metadata)]
    );
    return { ...inserted.rows[0], idempotent: false };
  });
}

export function resolveTextMessageMetadata(req: Request): Record<string, unknown> | null {
  const requested = req.body?.metadata;
  if (requested === undefined || requested === null) {
    return { source: "agent_api" };
  }
  const authenticatedRequest = req as Request & {
    authUser?: { authSource?: "core_api" | "internal_token" };
  };
  if (authenticatedRequest.authUser?.authSource !== "internal_token") {
    return null;
  }
  if (typeof requested !== "object" || Array.isArray(requested)) {
    return null;
  }
  const source = requested.source;
  const origem = requested.origem;
  const respostaId = requested.resposta_id;
  const idempotencyKey = requested.idempotency_key;
  if (
    !["bot_suggest_reviewed", "bot_auto"].includes(source) ||
    origem !== "bot" ||
    typeof respostaId !== "string" || !/^\d{1,20}$/.test(respostaId) ||
    typeof idempotencyKey !== "string" ||
    idempotencyKey !== `whatsapp-bot-resposta-${respostaId}`
  ) {
    return null;
  }
  if (source === "bot_auto") {
    if (typeof requested.inbound_wa_message_id !== "string"
        || !requested.inbound_wa_message_id.trim() || requested.inbound_wa_message_id.length > 160) return null;
    return { source, origem, resposta_id: respostaId, idempotency_key: idempotencyKey,
      inbound_wa_message_id: requested.inbound_wa_message_id };
  }
  return { source, origem, resposta_id: respostaId, idempotency_key: idempotencyKey };
}

async function markMessageSent(
  messageId: string,
  waMessageId: string | null,
  metadataPatch: Record<string, unknown>
): Promise<void> {
  await query(
    `
      UPDATE messages
      SET wa_message_id = $1,
          status = 'sent',
          metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb
      WHERE id = $3
    `,
    [waMessageId, JSON.stringify(metadataPatch), messageId]
  );
}

async function markMessageFailed(messageId: string, error: any): Promise<void> {
  await query(
    `
      UPDATE messages
      SET status = 'failed',
          metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb
      WHERE id = $2
    `,
    [
      JSON.stringify({
        graph_error: {
          message: error?.message,
          status: error?.response?.status,
          data: error?.response?.data
        }
      }),
      messageId
    ]
  );
}

export function decodeMultipartFilename(rawFilename: string): string {
  // Busboy/Multer decode multipart header parameters as latin1 by default,
  // even though browsers send the filename as raw UTF-8 bytes — without
  // this round-trip, accented names (ex.: "laudo-coração.pdf") arrive
  // mangled ("laudo-coraÃ§Ã£o.pdf").
  return Buffer.from(rawFilename, "latin1").toString("utf8");
}

const ATTACHMENT_FILENAME_MAX_LENGTH = 200;

export function sanitizeAttachmentFilename(rawFilename: string): string {
  const trimmed = rawFilename.trim();
  if (!trimmed) return "anexo";
  if (trimmed.length <= ATTACHMENT_FILENAME_MAX_LENGTH) return trimmed;

  const dotIndex = trimmed.lastIndexOf(".");
  const hasExtension = dotIndex > 0 && dotIndex < trimmed.length - 1;
  const extension = hasExtension ? trimmed.slice(dotIndex) : "";
  const stem = hasExtension ? trimmed.slice(0, dotIndex) : trimmed;

  const stemCodePoints = Array.from(stem);
  const maxStemLength = Math.max(1, ATTACHMENT_FILENAME_MAX_LENGTH - extension.length);
  const truncatedStem = stemCodePoints.slice(0, maxStemLength).join("");

  return `${truncatedStem}${extension}` || "anexo";
}

async function sendAttachmentMessage(
  res: Response,
  conversationId: string,
  waPhoneNumber: string,
  file: Express.Multer.File,
  mimeType: string,
  caption: string,
  accessToken: string,
  phoneNumberId: string
): Promise<void> {
  const filename = sanitizeAttachmentFilename(decodeMultipartFilename(file.originalname));
  const localMessageId = await insertPendingMessage(conversationId, filename, "document", {
    source: "agent_api",
    ...(caption ? { caption } : {})
  });

  let media: Awaited<ReturnType<typeof uploadWhatsAppDocumentWithRetry>>;
  let graphResponse: Awaited<ReturnType<typeof sendWhatsAppDocumentMessageWithRetry>>;
  try {
    media = await uploadWhatsAppDocumentWithRetry({
      phoneNumberId,
      accessToken,
      filename,
      content: file.buffer,
      mimeType
    });

    graphResponse = await sendWhatsAppDocumentMessageWithRetry({
      phoneNumberId,
      accessToken,
      to: whatsappGraphRecipient(waPhoneNumber),
      mediaId: media.id,
      filename,
      caption: caption || undefined
    });
  } catch (error: any) {
    logger.error("Graph API attachment send failed", {
      conversationId,
      localMessageId,
      message: error?.message
    });

    await markMessageFailed(localMessageId, error);
    await touchConversation(conversationId);

    res.status(502).json({
      error: "Failed to send attachment to WhatsApp Graph API",
      local_message_id: localMessageId
    });
    return;
  }

  const waMessageId = graphResponse.messages?.[0]?.id ?? null;

  try {
    await markMessageSent(localMessageId, waMessageId, {
      graph_response: graphResponse,
      message: {
        type: "document",
        document: { id: media.id, filename, ...(caption ? { caption } : {}) }
      }
    });
    await touchConversation(conversationId);
  } catch (error: any) {
    logger.error("Failed to persist sent attachment message state", {
      conversationId,
      localMessageId,
      waMessageId,
      message: error?.message
    });
  }

  res.status(201).json({ id: localMessageId, wa_message_id: waMessageId, status: "sent" });
}

export async function sendConversationMessage(req: Request, res: Response): Promise<void> {
  const conversationId = req.params.id;
  if (typeof conversationId !== "string" || conversationId.trim().length === 0) {
    res.status(400).json({ error: "conversation id is required" });
    return;
  }
  const file = req.file;
  const caption = typeof req.body?.body === "string" ? req.body.body.trim() : "";
  const type = req.body?.type ?? "text";

  if (!file && caption.length === 0) {
    res.status(400).json({ error: "body is required" });
    return;
  }

  const resolvedAttachmentMimeType = file
    ? resolveAttachmentMimeType(decodeMultipartFilename(file.originalname), file.mimetype)
    : null;
  if (file && !resolvedAttachmentMimeType) {
    res.status(422).json({ error: "Unsupported attachment file type" });
    return;
  }

  if (file && caption.length > WHATSAPP_DOCUMENT_CAPTION_MAX_LENGTH) {
    res.status(422).json({
      error: `Attachment caption exceeds ${WHATSAPP_DOCUMENT_CAPTION_MAX_LENGTH} characters`,
      code: "CAPTION_TOO_LONG"
    });
    return;
  }

  if (file && file.buffer.length === 0) {
    res.status(422).json({ error: "Attachment file is empty" });
    return;
  }

  if (!whatsappAccessToken || !phoneNumberId) {
    res.status(500).json({ error: "Missing WhatsApp API environment configuration" });
    return;
  }

  const conversationResult = await query<{
    id: string;
    wa_phone_number: string;
    last_inbound_at: Date | string | null;
  }>(
    `SELECT id, wa_phone_number, last_inbound_at FROM conversations WHERE id = $1`,
    [conversationId]
  );

  const conversation = conversationResult.rows[0];
  if (!conversation) {
    res.status(404).json({ error: "Conversation not found" });
    return;
  }

  const customerServiceWindow: CustomerServiceWindow = describeCustomerServiceWindow(
    conversation.last_inbound_at
  );
  if (!customerServiceWindow.is_open) {
    res.status(409).json({
      error: "Customer service window is closed. Use an approved template.",
      code: "CUSTOMER_SERVICE_WINDOW_CLOSED",
      customer_service_window: customerServiceWindow
    });
    return;
  }

  if (file) {
    await sendAttachmentMessage(
      res,
      conversationId,
      conversation.wa_phone_number,
      file,
      resolvedAttachmentMimeType as string,
      caption,
      whatsappAccessToken,
      phoneNumberId
    );
    return;
  }

  const messageMetadata = resolveTextMessageMetadata(req);
  if (!messageMetadata) {
    res.status(422).json({ error: "Invalid bot message metadata" });
    return;
  }
  const reservation = await reservePendingTextMessage(
    conversationId,
    caption,
    type,
    messageMetadata
  );
  const localMessageId = reservation.id;
  if (reservation.status === "bot_conversation_changed") {
    res.status(409).json({ code: "BOT_CONVERSATION_CHANGED", error: "Automatic reply is no longer eligible" });
    return;
  }
  if (reservation.idempotent) {
    if (["sent", "delivered", "read"].includes(reservation.status)) {
      res.status(200).json({
        id: localMessageId,
        wa_message_id: reservation.wa_message_id,
        status: "sent",
        idempotent: true
      });
      return;
    }
    res.status(409).json({
      error: "Message send is already in progress",
      code: "MESSAGE_SEND_IN_PROGRESS",
      local_message_id: localMessageId
    });
    return;
  }

  let graphResponse: any;
  try {
    graphResponse = await sendWhatsAppMessageWithRetry({
      phoneNumberId,
      accessToken: whatsappAccessToken,
      to: whatsappGraphRecipient(conversation.wa_phone_number),
      body: caption,
      type,
      maxAttempts: messageMetadata.source === "bot_auto" ? 1 : undefined
    });
  } catch (error: any) {
    logger.error("Graph API send failed", {
      conversationId,
      localMessageId,
      message: error?.message
    });

    try {
      await markMessageFailed(localMessageId, error);
      await touchConversation(conversationId);
    } catch (persistenceError: any) {
      logger.error("Failed to persist WhatsApp send failure", {
        conversationId,
        localMessageId,
        message: persistenceError?.message
      });
    }

    res.status(502).json({
      error: "Failed to send message to WhatsApp Graph API",
      local_message_id: localMessageId
    });
    return;
  }

  const waMessageId = graphResponse.messages?.[0]?.id ?? null;
  try {
    await markMessageSent(localMessageId, waMessageId, { graph_response: graphResponse });
  } catch (error: any) {
    // A Graph API já aceitou a mensagem. Manter a reserva em `pending` é
    // intencionalmente fail-closed: uma repetição idempotente não pode chamar
    // a Graph novamente e duplicar a mensagem externa.
    logger.error("WhatsApp send accepted but local confirmation failed", {
      conversationId,
      localMessageId,
      message: error?.message
    });
    res.status(202).json({
      id: localMessageId,
      wa_message_id: waMessageId,
      status: "accepted_unconfirmed",
      idempotent: false
    });
    return;
  }

  try {
    await touchConversation(conversationId);
  } catch (error: any) {
    logger.error("WhatsApp message sent but conversation touch failed", {
      conversationId,
      localMessageId,
      message: error?.message
    });
  }

  res.status(201).json({
    id: localMessageId,
    wa_message_id: waMessageId,
    status: "sent",
    idempotent: false
  });
}

export async function claimConversation(req: Request, res: Response): Promise<void> {
  const conversationId = req.params.id;
  const agentId = req.body?.agent_id;
  const onlyIfUnassigned = req.body?.only_if_unassigned;

  if (!agentId) {
    res.status(400).json({ error: "agent_id is required" });
    return;
  }
  if (onlyIfUnassigned !== undefined && typeof onlyIfUnassigned !== "boolean") {
    res.status(422).json({ error: "only_if_unassigned must be a boolean" });
    return;
  }

  const result = await withTransaction(async (client) => {
    const conversation = await client.query<{ id: string; last_agent_id: string | null }>(
      `SELECT id, last_agent_id FROM conversations WHERE id = $1 FOR UPDATE`,
      [conversationId]
    );

    if (conversation.rowCount === 0) {
      return { notFound: "conversation" as const };
    }

    const agent = await client.query<{ id: string }>(
      `SELECT id FROM agents WHERE id = $1 AND active = true`,
      [agentId]
    );

    if (agent.rowCount === 0) {
      return { notFound: "agent" as const };
    }

    if (onlyIfUnassigned === true && conversation.rows[0].last_agent_id !== null) {
      if (conversation.rows[0].last_agent_id !== String(agentId)) {
        return { conflict: true as const, agentId: conversation.rows[0].last_agent_id };
      }
      const existing = await client.query<{ id: string }>(
        `SELECT id FROM conversation_participants
         WHERE conversation_id = $1 AND agent_id = $2 AND left_at IS NULL
         ORDER BY id DESC LIMIT 1`,
        [conversationId, agentId]
      );
      return { participantId: existing.rows[0]?.id ?? null, idempotent: true };
    }

    await client.query(
      `
        SELECT id
        FROM conversation_participants
        WHERE conversation_id = $1
          AND left_at IS NULL
        FOR UPDATE
      `,
      [conversationId]
    );

    await client.query(
      `
        UPDATE conversation_participants
        SET left_at = now()
        WHERE conversation_id = $1
          AND left_at IS NULL
      `,
      [conversationId]
    );

    const participant = await client.query<{ id: string }>(
      `
        INSERT INTO conversation_participants (
          conversation_id,
          agent_id,
          joined_at
        )
        VALUES ($1, $2, now())
        RETURNING id
      `,
      [conversationId, agentId]
    );

    await client.query(
      `
        UPDATE conversations
        SET last_agent_id = $2,
            updated_at = now(),
            last_activity_at = now()
        WHERE id = $1
      `,
      [conversationId, agentId]
    );

    await client.query(
      `
        INSERT INTO audit_logs (conversation_id, agent_id, action, payload, created_at)
        VALUES ($1, $2, 'claim', $3::jsonb, now())
      `,
      [
        conversationId,
        agentId,
        JSON.stringify({
          source: "api.claim",
          note: "conversation row locked with FOR UPDATE before claim"
        })
      ]
    );

    return { participantId: participant.rows[0].id };
  });

  if ((result as any).notFound === "conversation") {
    res.status(404).json({ error: "Conversation not found" });
    return;
  }

  if ((result as any).notFound === "agent") {
    res.status(404).json({ error: "Agent not found or inactive" });
    return;
  }
  if ("conflict" in result) {
    res.status(409).json({
      error: "Outro integrante da equipe já assumiu esta conversa.",
      code: "CONVERSATION_ALREADY_ASSIGNED",
      last_agent_id: result.agentId
    });
    return;
  }

  res.status(200).json({
    message: "Conversation claimed",
    participant_id: (result as any).participantId,
    idempotent: "idempotent" in result && result.idempotent === true
  });
}

export async function unclaimConversation(req: Request, res: Response): Promise<void> {
  const conversationId = req.params.id;
  const agentId = req.body?.agent_id;

  if (!agentId) {
    res.status(400).json({ error: "agent_id is required" });
    return;
  }

  const result = await withTransaction(async (client) => {
    const conversation = await client.query<{ id: string; last_agent_id: string | null }>(
      `SELECT id, last_agent_id FROM conversations WHERE id = $1 FOR UPDATE`,
      [conversationId]
    );

    if (conversation.rowCount === 0) {
      return { notFound: "conversation" as const };
    }

    await client.query(
      `
        SELECT id
        FROM conversation_participants
        WHERE conversation_id = $1
          AND left_at IS NULL
        FOR UPDATE
      `,
      [conversationId]
    );

    const participants = await client.query<{ id: string }>(
      `
        UPDATE conversation_participants
        SET left_at = now()
        WHERE conversation_id = $1
          AND agent_id = $2
          AND left_at IS NULL
        RETURNING id
      `,
      [conversationId, agentId]
    );

    if (participants.rowCount === 0) {
      return { notFound: "assignment" as const };
    }

    await client.query(
      `
        UPDATE conversations
        SET last_agent_id = CASE WHEN last_agent_id = $2 THEN NULL ELSE last_agent_id END,
            updated_at = now(),
            last_activity_at = now()
        WHERE id = $1
      `,
      [conversationId, agentId]
    );

    await client.query(
      `
        INSERT INTO audit_logs (conversation_id, agent_id, action, payload, created_at)
        VALUES ($1, $2, 'unclaim', $3::jsonb, now())
      `,
      [
        conversationId,
        agentId,
        JSON.stringify({
          source: "api.unclaim",
          note: "conversation row locked with FOR UPDATE before unclaim"
        })
      ]
    );

    return { affected: participants.rowCount };
  });

  if ((result as any).notFound === "conversation") {
    res.status(404).json({ error: "Conversation not found" });
    return;
  }

  if ((result as any).notFound === "assignment") {
    res.status(404).json({ error: "No active claim found for this agent in this conversation" });
    return;
  }

  res.status(200).json({ message: "Conversation unclaimed" });
}
