import assert from "assert";
import axios from "axios";
import { createHash, createHmac } from "crypto";
import { readFile } from "fs/promises";
import path from "path";
import { Request, Response } from "express";
import { pool, query } from "../src/services/dbService";
import {
  claimConversation,
  listConversationMessages,
  listConversations,
  markConversationSeen,
  updateConversationStatus
} from "../src/controllers/conversationsController";

interface Conversation {
  id: string;
  status: string;
  unread: boolean;
  needs_reply: boolean;
  waiting_since: string | null;
  last_message_id: string | null;
  resolved_through_message_id: string | null;
}

interface Payload {
  data: Conversation[];
  pagination: { total: number };
  summary: Record<string, number>;
  last_message_id: string | null;
  changed?: boolean;
  code?: string;
}

async function call(
  handler: (req: Request, res: Response) => Promise<void>,
  options: { id?: string; query?: Record<string, unknown>; body?: Record<string, unknown> } = {}
): Promise<{ status: number; payload: Payload }> {
  let status = 200;
  let payload: unknown;
  const response = {
    status(value: number) { status = value; return this; },
    json(value: unknown) { payload = value; return this; }
  } as unknown as Response;
  await handler({ params: { id: options.id }, query: options.query ?? {}, body: options.body ?? {} } as unknown as Request, response);
  // Exercise the wire representation, including Date -> ISO and BIGINT strings.
  return { status, payload: JSON.parse(JSON.stringify(payload)) as Payload };
}

async function until(check: () => Promise<boolean>, message: string): Promise<void> {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.fail(message);
}

async function run(): Promise<void> {
  const databaseUrl = new URL(process.env.DATABASE_URL || "");
  assert.ok(
    ["127.0.0.1", "localhost", "[::1]"].includes(databaseUrl.hostname) && /test/i.test(databaseUrl.pathname),
    "Use an explicit local test database; these contracts create synthetic fixtures and reapply the migration."
  );

  // Only signed synthetic inbound traffic is exercised; notifications and
  // customer-facing delivery have no configured credentials or recipients.
  process.env.WHATSAPP_APP_SECRET = "synthetic-reply-queue-secret";
  process.env.WEBHOOK_ALLOW_UNSIGNED = "false";
  process.env.WHATSAPP_INTERNAL_API_TOKEN = "";
  process.env.PHONE_NUMBER_ID = "synthetic-reply-queue-number";
  const { receiveWebhook } = await import("../src/controllers/webhookController");

  const marker = `Reply queue ${Date.now()}`;
  const conversations: string[] = [];
  const agents: string[] = [];
  const webhookHashes: string[] = [];
  const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
  const times = { six: hoursAgo(6), five: hoursAgo(5), four: hoursAgo(4), three: hoursAgo(3), two: hoursAgo(2), one: hoursAgo(1) };
  let fixtureIndex = 0;

  async function insertConversation(label: string, status = "open"): Promise<string> {
    const inserted = await query<{ id: string }>(
      `INSERT INTO conversations (wa_phone_number, subject, status, last_inbound_at)
       VALUES ($1, $2, $3, $4) RETURNING id`,
      [`queue-${Date.now()}-${fixtureIndex++}`, `${marker} ${label}`, status, times.one]
    );
    const id = inserted.rows[0].id;
    conversations.push(id);
    return id;
  }

  async function insertMessage(id: string, fromMe: boolean, at: string, status = fromMe ? "sent" : "received"): Promise<string> {
    const inserted = await query<{ id: string }>(
      `INSERT INTO messages (conversation_id, from_me, body, created_at, status)
       VALUES ($1, $2, $3, $4, $5) RETURNING id`,
      [id, fromMe, `${marker} synthetic message`, at, status]
    );
    return inserted.rows[0].id;
  }

  async function getConversation(id: string): Promise<Conversation> {
    const listed = await call(listConversations, { query: { search: marker, limit: "100" } });
    const conversation = listed.payload.data.find((row) => row.id === id);
    assert.ok(conversation);
    return conversation;
  }

  async function sendInbound(id: string, waMessageId: string, deliveryVariant = 0,
    message: Record<string, unknown> = {}): Promise<() => Promise<void>> {
    const phone = `5591${id.padStart(9, "0")}`;
    await query("UPDATE conversations SET wa_phone_number = $2, wa_psid = $2 WHERE id = $1", [id, phone]);
    const payload = {
      object: "whatsapp_business_account",
      entry: [{ id: String(deliveryVariant), changes: [{ field: "messages", value: {
        metadata: { phone_number_id: "synthetic-reply-queue-number" },
        messages: [{ id: waMessageId, from: phone, timestamp: "1700000000", type: "text", text: { body: `${marker} inbound` }, ...message }]
      } }] }]
    };
    const rawBody = Buffer.from(JSON.stringify(payload));
    const hash = createHash("sha256").update(rawBody).digest("hex");
    if (!webhookHashes.includes(hash)) webhookHashes.push(hash);
    const signature = `sha256=${createHmac("sha256", "synthetic-reply-queue-secret").update(rawBody).digest("hex")}`;
    await new Promise<void>((resolve, reject) => {
      let httpStatus = 200;
      const response = {
        status(value: number) { httpStatus = value; return this; },
        json() { if (httpStatus === 200) resolve(); else reject(new Error(`Unexpected webhook status ${httpStatus}`)); return this; },
        sendStatus(value: number) { if (value === 200) resolve(); else reject(new Error(`Unexpected webhook status ${value}`)); return this; }
      } as unknown as Response;
      receiveWebhook({ body: payload, rawBody, header: () => signature } as unknown as Request, response);
    });
    return async () => {
      await until(async () => {
        const event = await query<{ processing_status: string }>("SELECT processing_status FROM webhook_events WHERE payload_hash = $1", [hash]);
        assert.notStrictEqual(event.rows[0]?.processing_status, "failed", "synthetic webhook must process successfully");
        return event.rows[0]?.processing_status === "processed";
      }, "Timed out waiting for the signed synthetic webhook");
    };
  }

  try {
    for (const needs_reply of ["yes", "1", "", ["true", "false"]]) {
      assert.strictEqual((await call(listConversations, { query: { needs_reply } })).status, 422);
    }
    for (const token of [0, 123, "0", "-1", "1.2", "9223372036854775808", ["1"]]) {
      assert.strictEqual((await call(updateConversationStatus, { id: "1", body: { status: "closed", expected_last_message_id: token } })).status, 422);
    }
    for (const only_if_unassigned of ["true", "false", 1, null]) {
      assert.strictEqual((await call(claimConversation, { id: "1", body: { agent_id: "1", only_if_unassigned } })).status, 422);
    }

    const baseline = (await call(listConversations, { query: { limit: "1" } })).payload.summary;
    const readWaiting = await insertConversation("read but waiting");
    await insertMessage(readWaiting, false, times.six);
    const latestReadWaiting = await insertMessage(readWaiting, false, times.two);
    await call(markConversationSeen, { id: readWaiting });
    const readRow = await getConversation(readWaiting);
    assert.strictEqual(readRow.unread, false);
    assert.strictEqual(readRow.needs_reply, true, "reading does not answer a customer");
    assert.strictEqual(readRow.waiting_since, times.six, "waiting begins with the first unanswered inbound");
    assert.strictEqual(readRow.last_message_id, latestReadWaiting, "the queue token is a BIGINT string");

    const failedWaiting = await insertConversation("pending and failed", "pending");
    await insertMessage(failedWaiting, false, times.three);
    await insertMessage(failedWaiting, true, times.two, "pending");
    const retryId = await insertMessage(failedWaiting, true, times.one, "failed");
    assert.strictEqual((await getConversation(failedWaiting)).waiting_since, times.three, "pending and failed sends do not remove the queue item");

    const newQuestion = await insertConversation("new question");
    await insertMessage(newQuestion, false, times.five);
    await insertMessage(newQuestion, true, times.four);
    const questionId = await insertMessage(newQuestion, false, times.one);
    assert.strictEqual((await getConversation(newQuestion)).waiting_since, times.one);

    const answered = await insertConversation("answered but unread");
    await insertMessage(answered, false, times.four);
    await insertMessage(answered, true, times.three, "delivered");
    await insertMessage(answered, true, times.two, "read");
    assert.strictEqual((await getConversation(answered)).needs_reply, false);
    assert.strictEqual((await getConversation(answered)).waiting_since, null);
    assert.strictEqual((await getConversation(answered)).unread, true, "reply and reading are independent dimensions");

    const queue = await call(listConversations, { query: { search: marker, needs_reply: "true", limit: "2" } });
    assert.deepStrictEqual(queue.payload.data.map((row) => row.id), [readWaiting, failedWaiting], "the longest actual wait wins regardless of read state");
    assert.strictEqual(queue.payload.pagination.total, 3);
    assert.strictEqual(queue.payload.summary.needs_reply, baseline.needs_reply + 3, "the global count ignores filters and pagination");
    assert.strictEqual((await call(listConversations, { query: { search: `${marker} absent`, needs_reply: "false" } })).payload.summary.needs_reply, baseline.needs_reply + 3);
    assert.deepStrictEqual((await call(listConversations, { query: { search: marker, needs_reply: "false" } })).payload.data.map((row) => row.id), [answered]);
    assert.deepStrictEqual((await call(listConversations, { query: { search: marker, needs_reply: "true", unread: "false" } })).payload.data.map((row) => row.id), [readWaiting]);
    assert.deepStrictEqual((await call(listConversations, { query: { search: marker, needs_reply: "true", status: "pending", assigned: "unassigned" } })).payload.data.map((row) => row.id), [failedWaiting]);

    // Same timestamp boundaries use the same ID tiebreaker as message history.
    const tieReply = await insertMessage(newQuestion, true, times.one);
    assert.strictEqual((await getConversation(newQuestion)).needs_reply, false);
    const tieQuestion = await insertMessage(newQuestion, false, times.one);
    assert.ok(BigInt(tieQuestion) > BigInt(tieReply) && BigInt(tieReply) > BigInt(questionId));
    assert.strictEqual((await getConversation(newQuestion)).needs_reply, true);

    // A reviewed retry can retain its old ID while moving forward in history.
    await insertMessage(failedWaiting, false, hoursAgo(0.5));
    await query("UPDATE messages SET status = 'sent', created_at = now() WHERE id = $1", [retryId]);
    assert.strictEqual((await getConversation(failedWaiting)).needs_reply, false, "successful retry is ordered by its refreshed timestamp");

    for (const order of ["oldest", "latest"]) {
      const messages = await call(listConversationMessages, { id: readWaiting, query: { order, limit: "1" } });
      assert.strictEqual(messages.payload.last_message_id, latestReadWaiting, "the optimistic token covers all messages independently of pagination");
    }
    const resolved = await call(updateConversationStatus, { id: readWaiting, body: { status: "closed", expected_last_message_id: latestReadWaiting } });
    assert.strictEqual(resolved.status, 200);
    assert.strictEqual(resolved.payload.changed, true);
    assert.strictEqual((await getConversation(readWaiting)).needs_reply, false);
    assert.strictEqual((await getConversation(readWaiting)).resolved_through_message_id, latestReadWaiting);
    assert.strictEqual((await call(updateConversationStatus, { id: readWaiting, body: { status: "closed", expected_last_message_id: latestReadWaiting } })).payload.changed, false, "repeated resolution is idempotent");
    await call(updateConversationStatus, { id: readWaiting, body: { status: "open" } });
    assert.strictEqual((await getConversation(readWaiting)).needs_reply, false, "manual reopening does not resurrect already resolved inbound");

    const empty = await insertConversation("empty");
    assert.strictEqual((await call(listConversationMessages, { id: empty })).payload.last_message_id, null);
    assert.strictEqual((await call(updateConversationStatus, { id: empty, body: { status: "closed", expected_last_message_id: null } })).status, 200);
    assert.strictEqual((await getConversation(empty)).resolved_through_message_id, "0");
    assert.strictEqual((await call(updateConversationStatus, { id: newQuestion, body: { status: "closed" } })).status, 200, "legacy clients may still omit the optimistic token");

    for (const suffix of ["a", "b"]) {
      const inserted = await query<{ id: string }>("INSERT INTO agents (name) VALUES ($1) RETURNING id", [`${marker} ${suffix}`]);
      agents.push(inserted.rows[0].id);
    }
    const concurrentClaims = await Promise.all(agents.map((agentId) => call(claimConversation, {
      id: empty, body: { agent_id: agentId, only_if_unassigned: true }
    })));
    assert.deepStrictEqual(concurrentClaims.map((claim) => claim.status).sort(), [200, 409], "only one concurrent quick claim may acquire an unassigned conversation");
    const winningAgent = agents[concurrentClaims.findIndex((claim) => claim.status === 200)];
    const losingAgent = agents.find((agentId) => agentId !== winningAgent)!;
    assert.strictEqual(concurrentClaims.find((claim) => claim.status === 409)?.payload.code, "CONVERSATION_ALREADY_ASSIGNED");
    const participantCount = async () => (await query<{ count: string }>("SELECT COUNT(*)::text AS count FROM conversation_participants WHERE conversation_id = $1", [empty])).rows[0].count;
    assert.strictEqual(await participantCount(), "1");
    assert.strictEqual((await call(claimConversation, { id: empty, body: { agent_id: winningAgent, only_if_unassigned: true } })).status, 200);
    assert.strictEqual(await participantCount(), "1", "repeated quick claim by the same agent preserves the participant and audit history");
    assert.strictEqual((await call(claimConversation, { id: empty, body: { agent_id: losingAgent } })).status, 200, "explicit legacy transfer remains available");
    assert.strictEqual(await participantCount(), "2");

    await call(updateConversationStatus, { id: readWaiting, body: { status: "closed" } });
    await (await sendInbound(readWaiting, `${marker}-reopen`))();
    let reopened = await getConversation(readWaiting);
    assert.strictEqual(reopened.status, "open", "new signed inbound reopens a resolved conversation");
    assert.strictEqual(reopened.needs_reply, true, "even an old provider timestamp is a new locally observed request");
    assert.ok(BigInt(reopened.last_message_id!) > BigInt(latestReadWaiting));
    await call(updateConversationStatus, { id: readWaiting, body: { status: "closed", expected_last_message_id: reopened.last_message_id } });
    await (await sendInbound(readWaiting, `${marker}-reopen`, 1))();
    const duplicate = await getConversation(readWaiting);
    assert.strictEqual(duplicate.status, "closed", "duplicate message with a different event envelope does not reopen");
    assert.strictEqual(duplicate.needs_reply, false);
    assert.strictEqual(duplicate.last_message_id, reopened.last_message_id);
    await (await sendInbound(readWaiting, `${marker}-reopen`, 1))();
    assert.strictEqual((await getConversation(readWaiting)).status, "closed", "duplicate webhook payload is also idempotent");
    await call(updateConversationStatus, { id: readWaiting, body: { status: "pending" } });
    await (await sendInbound(readWaiting, `${marker}-pending-reopen`))();
    reopened = await getConversation(readWaiting);
    assert.strictEqual(reopened.status, "open", "new inbound also reopens pending conversations");
    const stale = await call(updateConversationStatus, { id: readWaiting, body: { status: "closed", expected_last_message_id: duplicate.last_message_id } });
    assert.strictEqual(stale.status, 409);
    assert.strictEqual(stale.payload.code, "CONVERSATION_CHANGED");
    assert.strictEqual((await getConversation(readWaiting)).status, "open");

    // An inbound transaction that was already holding the row lock must commit
    // before safe resolution compares the latest persisted message token.
    const lockingClient = await pool.connect();
    try {
      await lockingClient.query("BEGIN");
      await lockingClient.query("SELECT id FROM conversations WHERE id = $1 FOR UPDATE", [readWaiting]);
      const closing = call(updateConversationStatus, { id: readWaiting, body: { status: "closed", expected_last_message_id: reopened.last_message_id } });
      await until(async () => {
        const blocked = await query<{ count: string }>(`SELECT COUNT(*)::text AS count FROM pg_stat_activity
          WHERE datname = current_database() AND wait_event_type = 'Lock'
            AND query = 'SELECT * FROM conversations WHERE id = $1 FOR UPDATE'`);
        return Number(blocked.rows[0].count) > 0;
      }, "the safe close must wait for the inbound transaction's conversation lock");
      await lockingClient.query("INSERT INTO messages (conversation_id, from_me, body) VALUES ($1, FALSE, $2)", [readWaiting, `${marker} concurrent inbound`]);
      await lockingClient.query("COMMIT");
      const conflict = await closing;
      assert.strictEqual(conflict.status, 409, "inbound committed while close waited must cause conflict");
      assert.strictEqual(conflict.payload.code, "CONVERSATION_CHANGED");
      assert.strictEqual((await getConversation(readWaiting)).needs_reply, true);
    } finally {
      await lockingClient.query("ROLLBACK");
      lockingClient.release();
    }

    const legacy = await insertConversation("legacy closed", "closed");
    const legacyMessage = await insertMessage(legacy, false, times.one);
    const migration = await readFile(path.resolve(__dirname, "../migrations/init.sql"), "utf8");
    await query(migration);
    assert.strictEqual((await getConversation(legacy)).resolved_through_message_id, legacyMessage, "migration preserves the already closed legacy backlog");
    assert.strictEqual((await getConversation(legacy)).needs_reply, false);
    await query(migration);
    assert.strictEqual((await getConversation(legacy)).resolved_through_message_id, legacyMessage, "legacy backfill is idempotent");
    await (await sendInbound(legacy, `${marker}-legacy-reopen`))();
    assert.strictEqual((await getConversation(legacy)).needs_reply, true);

    // Exercise the entire signed webhook path with a fake authenticated domain
    // callback. No request reaches Meta or another external service.
    const templateIds: string[] = [];
    const reservationIds: string[] = [];
    const originalPost = axios.post;
    const originalInternalToken = process.env.WHATSAPP_INTERNAL_API_TOKEN;
    const callbackCalls: Array<Record<string, unknown>> = [];
    const domainResults = new Map<number, Record<string, unknown> | Error>();
    let domainTarget = 91000;
    process.env.WHATSAPP_INTERNAL_API_TOKEN = "synthetic-reply-queue-domain-token";
    (axios.post as unknown as (url: string, payload: Record<string, unknown>) => Promise<unknown>) = async (url, body) => {
      if (url.endsWith("/notificacoes/mensagem-recebida")) return { data: {} };
      assert.ok(url.endsWith("/agenda/respostas"), "no Graph or other delivery call is permitted");
      callbackCalls.push(body);
      const value = domainResults.get(Number(body.agendamento_id));
      if (value instanceof Error) throw value;
      assert.ok(value, "domain result must be configured by the synthetic fixture");
      return { data: value };
    };
    async function buttonFixture(options: {
      source?: "reservation" | "appointmentReminder" | "appointmentReminderService" | "appointmentChange";
      action?: string; result?: string; status?: string | null;
      failure?: boolean; senderMismatch?: boolean; unknownPayload?: boolean;
      responseTargetMismatch?: boolean; responseActionMismatch?: boolean;
      earlierQuestion?: boolean;
    } = {}): Promise<{ id: string; messageId: string; payload: string; waMessageId: string }> {
      const id = await insertConversation("domain button");
      if (options.earlierQuestion) await insertMessage(id, false, times.three);
      const source = options.source ?? "appointmentReminder";
      const action = options.action ?? (source === "reservation" ? "confirmar" : "confirmar_presenca");
      const target = ++domainTarget;
      const payload = `${marker}-domain-payload-${target}`;
      const phone = `5591${id.padStart(9, "0")}`;
      const destination = options.senderMismatch ? "5511900000000" : phone;
      if (source === "reservation") {
        const binding = await query<{ id: string }>(`INSERT INTO agenda_reservation_messages
          (reservation_id, destination, idempotency_key, request_hash, template_name, language_code,
           confirm_payload, change_payload, wa_message_id, processing_status)
          VALUES ($1, $2, $3, 'synthetic', 'reserva_de_agendamento', 'pt_BR', $4, $5, $6, 'sent') RETURNING id`,
        [target, destination, payload, action === "confirmar" ? payload : `${payload}-unused`,
          action === "confirmar" ? `${payload}-unused` : payload, `${payload}-outbound`]);
        reservationIds.push(binding.rows[0].id);
      } else {
        const binding = await query<{ id: string }>(`INSERT INTO approved_template_messages
          (template_key, template_name, language_code, subject_type, subject_id, subject_ids, destination,
           idempotency_key, request_hash, body_parameters, button_bindings, rendered_body, processing_status, wa_message_id)
          VALUES ($1, 'synthetic', 'pt_BR', 'agendamento', $2, $3::jsonb, $4, $5, 'synthetic', '[]'::jsonb,
            $6::jsonb, 'synthetic body', 'sent', $7) RETURNING id`,
        [source, target, JSON.stringify([target]), destination, payload,
          JSON.stringify([{ action, index: 0, payload }]), `${payload}-outbound`]);
        templateIds.push(binding.rows[0].id);
      }
      domainResults.set(target, options.failure ? new Error("synthetic domain callback unavailable") : {
        agendamento_id: options.responseTargetMismatch ? target + 1 : target,
        action: options.responseActionMismatch ? "solicitar_alteracao" : action,
        result: options.result ?? (source === "reservation" ? "confirmado" : "presenca_confirmada"),
        status: options.status === undefined ? (source === "reservation" ? "Confirmado" : "Agendado") : options.status,
      });
      const waMessageId = `${marker}-domain-click-${target}`;
      await (await sendInbound(id, waMessageId, 0, {
        type: "button", button: { text: "Confirmar presença", payload: options.unknownPayload ? `${payload}-unknown` : payload },
        // Untrusted provider fields must never be promoted into our annotation.
        agenda_receipt: { source: "appointmentReminder", action: "confirmar_presenca", result: "presenca_confirmada", status: "Agendado" }
      }))();
      const persisted = await query<{ id: string }>("SELECT id FROM messages WHERE wa_message_id = $1", [waMessageId]);
      return { id, messageId: persisted.rows[0].id, payload, waMessageId };
    }
    try {
      for (const source of ["appointmentReminder", "appointmentReminderService"] as const) for (const status of ["Agendado", "Confirmado"]) {
        const fixture = await buttonFixture({ source, status });
        const row = await getConversation(fixture.id);
        assert.strictEqual(row.needs_reply, false, "a trusted successful presence receipt resolves its own button");
        assert.strictEqual(row.unread, true, "domain processing is independent of reading");
        assert.strictEqual(row.last_message_id, fixture.messageId, "the button remains in the optimistic frontier");
        const history = await query<{ metadata: Record<string, unknown>; type: string }>("SELECT type, metadata FROM messages WHERE id = $1", [fixture.messageId]);
        assert.strictEqual(history.rows[0].type, "button");
        assert.deepStrictEqual(history.rows[0].metadata.agenda_receipt,
          { source: "appointmentReminder", action: "confirmar_presenca", result: "presenca_confirmada", status });
        const call = callbackCalls[callbackCalls.length - 1];
        assert.strictEqual(call.action, "confirmar_presenca", "presence never maps to reservation confirmation");
        const callsBeforeReplay = callbackCalls.length;
        await (await sendInbound(fixture.id, fixture.waMessageId, 1, {
          type: "button", button: { text: "Confirmar presença", payload: fixture.payload }
        }))();
        assert.strictEqual(callbackCalls.length, callsBeforeReplay, "provider retries cannot invoke the domain twice");
        assert.strictEqual((await getConversation(fixture.id)).needs_reply, false);
        assert.strictEqual((await getConversation(fixture.id)).last_message_id, fixture.messageId);
        await insertMessage(fixture.id, false, new Date().toISOString());
        assert.strictEqual((await getConversation(fixture.id)).needs_reply, true, "a later question is still waiting");
      }
      for (const result of ["confirmado", "ja_confirmado"]) {
        const fixture = await buttonFixture({ source: "reservation", result });
        assert.strictEqual((await getConversation(fixture.id)).needs_reply, false, "confirmed reservation receipts are also handled");
        const history = await query<{ metadata: Record<string, unknown> }>("SELECT metadata FROM messages WHERE id = $1", [fixture.messageId]);
        assert.deepStrictEqual(history.rows[0].metadata.agenda_receipt,
          { source: "reservation", action: "confirmar", result, status: "Confirmado" });
      }
      const oldQuestion = await buttonFixture({ earlierQuestion: true });
      assert.strictEqual((await getConversation(oldQuestion.id)).needs_reply, true, "a receipt cannot answer an earlier question");
      assert.strictEqual((await getConversation(oldQuestion.id)).waiting_since, times.three);

      for (const options of [
        { status: "Reservado" }, { status: "Cancelado" }, { status: "Expirado" }, { status: null },
        { result: "revisao_manual" }, { responseTargetMismatch: true }, { responseActionMismatch: true },
        { failure: true }, { senderMismatch: true }, { unknownPayload: true },
        { action: "solicitar_alteracao", result: "alteracao_solicitada" }, { action: "falar_equipe", result: "falar_equipe_solicitado" },
        { source: "appointmentReminderService" as const, action: "solicitar_alteracao", result: "alteracao_solicitada" },
        { source: "appointmentReminderService" as const, senderMismatch: true },
        { source: "appointmentReminderService" as const, unknownPayload: true },
        { source: "appointmentReminderService" as const, failure: true },
        { source: "appointmentChange" as const, action: "confirmar_horario" },
        { source: "appointmentChange" as const, action: "confirmar_presenca" },
        { source: "reservation" as const, action: "solicitar_alteracao", result: "alteracao_solicitada" },
        { source: "reservation" as const, result: "confirmacao_apos_prazo", status: "Expirado" },
        { source: "reservation" as const, result: "confirmacao_dados_pendentes", status: "Reservado" }
      ]) {
        const callsBefore = callbackCalls.length;
        const fixture = await buttonFixture(options);
        assert.strictEqual((await getConversation(fixture.id)).needs_reply, true, `review remains required: ${JSON.stringify(options)}`);
        const history = await query<{ metadata: Record<string, unknown> }>("SELECT metadata FROM messages WHERE id = $1", [fixture.messageId]);
        assert.ok(!history.rows[0].metadata.agenda_receipt, "failed, ignored, rejected and unrecognized replies have no trusted annotation");
        const eventTable = options.source === "reservation" ? "agenda_reservation_button_events" : "approved_template_button_events";
        const event = await query<{ processing_status: string }>(`SELECT processing_status FROM ${eventTable} WHERE provider_message_id = $1`, [fixture.waMessageId]);
        if ("unknownPayload" in options) {
          assert.strictEqual(event.rowCount, 0, "unknown payloads do not masquerade as processed domain events");
          assert.strictEqual(callbackCalls.length, callsBefore);
        } else if ("senderMismatch" in options) {
          assert.strictEqual(event.rows[0].processing_status, "rejected");
          assert.strictEqual(callbackCalls.length, callsBefore, "a rejected sender never reaches the domain callback");
        } else if ("failure" in options) {
          assert.strictEqual(event.rows[0].processing_status, "failed", "callback failure remains auditable");
        } else if (options.source === "appointmentChange") {
          assert.strictEqual(event.rows[0].processing_status, "ignored", "unsupported domain actions remain explicitly unhandled");
          assert.strictEqual(callbackCalls.length, callsBefore);
        } else {
          assert.strictEqual(event.rows[0].processing_status, "processed", "review outcomes retain their domain record");
        }
        if ("action" in options && options.action === "solicitar_alteracao" && options.source !== "reservation") {
          assert.strictEqual(callbackCalls[callbackCalls.length - 1].action, "solicitar_alteracao");
          const callsBeforeReplay = callbackCalls.length;
          await (await sendInbound(fixture.id, fixture.waMessageId, 1, {
            type: "button", button: { text: "Solicitar alteração", payload: fixture.payload }
          }))();
          assert.strictEqual(callbackCalls.length, callsBeforeReplay, "an alteration retry cannot notify the domain twice");
          assert.strictEqual((await getConversation(fixture.id)).needs_reply, true, "processing an alteration does not resolve human review");
        }
      }
      // Nullable, incomplete or cross-domain annotations must stay fail closed.
      for (const receipt of [
        {}, { source: "appointmentReminder", action: "confirmar_presenca" },
        { source: "appointmentReminder", action: "confirmar", result: "confirmado", status: "Confirmado" },
        { source: "reservation", action: "confirmar_presenca", result: "presenca_confirmada", status: "Agendado" },
        { source: "reservation", action: "confirmar", result: "confirmado", status: "Agendado" }
      ]) {
        const id = await insertConversation("incomplete receipt");
        await query(`INSERT INTO messages (conversation_id, from_me, body, type, metadata)
          VALUES ($1, FALSE, 'synthetic button', 'button', $2::jsonb)`, [id, JSON.stringify({ agenda_receipt: receipt })]);
        assert.strictEqual((await getConversation(id)).needs_reply, true);
      }
    } finally {
      axios.post = originalPost;
      if (originalInternalToken === undefined) delete process.env.WHATSAPP_INTERNAL_API_TOKEN;
      else process.env.WHATSAPP_INTERNAL_API_TOKEN = originalInternalToken;
      for (const id of templateIds) await query("DELETE FROM approved_template_messages WHERE id = $1", [id]);
      for (const id of reservationIds) await query("DELETE FROM agenda_reservation_messages WHERE id = $1", [id]);
    }

    console.log("Reply queue contracts passed: ordering, concurrency, signed webhook replay, trusted Agenda receipts, domain failures/review, and preservation of earlier/later questions.");
  } finally {
    for (const hash of webhookHashes) await query("DELETE FROM webhook_events WHERE payload_hash = $1", [hash]);
    for (const id of conversations) {
      await query("DELETE FROM audit_logs WHERE conversation_id = $1", [id]);
      await query("DELETE FROM conversation_participants WHERE conversation_id = $1", [id]);
      await query("DELETE FROM conversations WHERE id = $1", [id]);
    }
    for (const id of agents) await query("DELETE FROM agents WHERE id = $1", [id]);
  }
}

void run()
  .catch((error) => {
    console.error("Reply queue contract failed:", error);
    process.exitCode = 1;
  })
  .finally(() => pool.end());
