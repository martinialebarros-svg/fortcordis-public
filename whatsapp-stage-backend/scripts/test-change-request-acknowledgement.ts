import assert from "assert";
import axios from "axios";
import { createHash, createHmac } from "crypto";
import { Request, Response } from "express";
import { pool, query, withTransaction } from "../src/services/dbService";
import { handleApprovedTemplateButtonReply } from "../src/services/approvedTemplateButtonService";
import {
  CHANGE_REQUEST_ACK_SOURCE,
  CHANGE_REQUEST_ACK_TEXT,
  runPendingChangeRequestAcknowledgements,
  shutdownChangeRequestAcknowledgementWorker
} from "../src/services/changeRequestAcknowledgementService";
import { listConversations } from "../src/controllers/conversationsController";
import { WebhookMessage } from "../src/types/whatsapp";

interface Fixture {
  templateId: string;
  conversationId: string;
  phone: string;
  payload: string;
  clickId: string;
}

function buttonMessage(fixture: Fixture, options: { from?: string; timestamp?: string } = {}): WebhookMessage {
  return {
    id: fixture.clickId, from: options.from ?? fixture.phone,
    timestamp: options.timestamp ?? String(Math.floor(Date.now() / 1000)),
    type: "button", button: { text: "Solicitar alteração", payload: fixture.payload }
  } as WebhookMessage;
}

async function needsHumanReply(phone: string): Promise<boolean> {
  let responseBody: { data: Array<{ needs_reply: boolean; wa_phone_number: string }> } | undefined;
  const response = { status() { return this; }, json(value: unknown) {
    responseBody = value as typeof responseBody;
    return this;
  } } as unknown as Response;
  await listConversations({ query: { search: phone, limit: "100" } } as unknown as Request, response);
  const row = responseBody?.data.find((item) => item.wa_phone_number === phone);
  assert.ok(row, `Conversation ${phone} must appear in inbox`);
  return row.needs_reply;
}

async function run(): Promise<void> {
  const databaseUrl = new URL(process.env.DATABASE_URL || "");
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(databaseUrl.hostname)
    && /test/i.test(databaseUrl.pathname), "Use a local test database only");
  process.env.PHONE_NUMBER_ID = "synthetic-change-ack-number";
  process.env.WHATSAPP_ACCESS_TOKEN = "synthetic-change-ack-token";
  process.env.WHATSAPP_INTERNAL_API_TOKEN = "synthetic-change-ack-internal";
  process.env.WHATSAPP_APP_SECRET = "synthetic-change-ack-webhook-secret";
  process.env.WEBHOOK_ALLOW_UNSIGNED = "false";

  const runId = String(Date.now());
  const fixtures: Fixture[] = [];
  const webhookHashes: string[] = [];
  const graphRequests: Array<{ url: string; body: string }> = [];
  const callbackRequests: Array<{ action: string; agendamento_id: number }> = [];
  let backendOutcome: "accepted" | "review" | "throw" = "accepted";
  let graphFails = false;
  let graphStarted: (() => void) | null = null;
  let graphGate: Promise<void> | null = null;
  const originalPost = axios.post;
  (axios.post as unknown as (url: string, data: unknown) => Promise<unknown>) = async (url, data) => {
    if (url.includes("/integracoes/whatsapp/agenda/respostas")) {
      const payload = data as { action: string; agendamento_id: number };
      callbackRequests.push(payload);
      if (backendOutcome === "throw") throw new Error("synthetic callback failure");
      return { data: {
        action: payload.action, agendamento_id: payload.agendamento_id,
        result: backendOutcome === "accepted" ? "alteracao_solicitada" : "revisao_manual",
        status: "Agendado"
      } };
    }
    if (url.includes("/integracoes/whatsapp/notificacoes/mensagem-recebida")) {
      return { data: { bot_job_enqueued: false } };
    }
    if (url.includes("graph.facebook.com")) {
      graphRequests.push({ url, body: (data as { text: { body: string } }).text.body });
      if (graphGate) {
        graphStarted?.();
        await graphGate;
      }
      if (graphFails) throw new Error("synthetic uncertain Graph failure");
      return { data: { messages: [{ id: `wamid.synthetic.ack.${graphRequests.length}.${runId}` }] } };
    }
    throw new Error(`Unexpected external request: ${url}`);
  };

  async function fixture(label: string, preinsertInbound = true): Promise<Fixture> {
    const phone = `5585990${runId.slice(-6)}${fixtures.length.toString().padStart(2, "0")}`;
    const conversation = await query<{ id: string }>(
      `INSERT INTO conversations (wa_phone_number, wa_psid, last_inbound_at)
       VALUES ($1, $1, now()) RETURNING id`, [phone]);
    const payload = `synthetic_change_ack_${runId}_${label}`;
    const template = await query<{ id: string }>(`
      INSERT INTO approved_template_messages (
        template_key, template_name, language_code, subject_type, subject_id, subject_ids,
        destination, idempotency_key, request_hash, body_parameters, button_bindings,
        rendered_body, processing_status, wa_message_id, created_at, updated_at, sent_at
      ) VALUES ('appointmentReminderService', 'lembrete_de_agendamento_servico_v2', 'pt_BR',
        'agendamento', 4242, '[4242]'::jsonb, $1, $2, 'synthetic', '[]'::jsonb, $3::jsonb,
        'synthetic reminder', 'sent', $4, now(), now(), now()) RETURNING id`,
      [phone, `synthetic-change-ack-template-${runId}-${label}`,
        JSON.stringify([{ action: "solicitar_alteracao", index: 1, payload }]),
        `wamid.synthetic.reminder.${runId}.${label}`]);
    const created = {
      conversationId: conversation.rows[0].id,
      templateId: template.rows[0].id,
      phone, payload, clickId: `wamid.synthetic.click.${runId}.${label}`
    };
    fixtures.push(created);
    if (preinsertInbound) {
      await query(`INSERT INTO messages (conversation_id, wa_message_id, from_me, body, type, status, created_at)
                   VALUES ($1, $2, FALSE, 'Solicitar alteração', 'button', 'received', now())`,
        [created.conversationId, created.clickId]);
    }
    return created;
  }

  async function click(item: Fixture, options: { from?: string; timestamp?: string } = {}): Promise<void> {
    await withTransaction(async (client) => {
      await handleApprovedTemplateButtonReply(client, buttonMessage(item, options));
    });
  }

  async function ackMessages(item: Fixture): Promise<Array<{
    status: string; body: string; metadata: Record<string, unknown>; wa_message_id: string | null;
  }>> {
    const rows = await query<{ status: string; body: string; metadata: Record<string, unknown>; wa_message_id: string | null }>(
      `SELECT status, body, metadata, wa_message_id FROM messages
       WHERE conversation_id = $1 AND from_me = TRUE ORDER BY id`, [item.conversationId]);
    return rows.rows;
  }

  try {
    const accepted = await fixture("accepted");
    await click(accepted);
    assert.strictEqual(graphRequests.length, 0, "No provider send before webhook commit/dispatcher");
    await runPendingChangeRequestAcknowledgements();
    const sent = await ackMessages(accepted);
    assert.strictEqual(sent.length, 1);
    assert.strictEqual(sent[0].status, "sent");
    assert.strictEqual(sent[0].body, CHANGE_REQUEST_ACK_TEXT);
    assert.strictEqual(sent[0].metadata.source, CHANGE_REQUEST_ACK_SOURCE);
    assert.strictEqual(sent[0].metadata.origem, "bot");
    assert.strictEqual(sent[0].metadata.inbound_wa_message_id, accepted.clickId);
    assert.ok(sent[0].wa_message_id);
    assert.strictEqual(graphRequests.length, 1);
    assert.strictEqual(graphRequests[0].body, CHANGE_REQUEST_ACK_TEXT);
    assert.strictEqual(await needsHumanReply(accepted.phone), true,
      "An automatic acknowledgement must not close the human-review queue");
    await query(`INSERT INTO messages (conversation_id, from_me, body, type, metadata, status, created_at)
                 VALUES ($1, TRUE, 'A equipe conferiu o pedido.', 'text', '{"source":"agent_api"}'::jsonb,
                         'sent', now() + interval '1 second')`, [accepted.conversationId]);
    assert.strictEqual(await needsHumanReply(accepted.phone), false,
      "A later human response resolves the request normally");
    await click(accepted);
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual((await ackMessages(accepted)).filter((row) => row.metadata.source === CHANGE_REQUEST_ACK_SOURCE).length, 1);
    assert.strictEqual(graphRequests.length, 1, "Provider retries cannot duplicate the acknowledgement");
    assert.strictEqual(callbackRequests.length, 1);

    const mismatch = await fixture("sender-mismatch");
    await click(mismatch, { from: "5511999990000" });
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual((await ackMessages(mismatch)).length, 0);
    assert.strictEqual(graphRequests.length, 1);

    backendOutcome = "review";
    const review = await fixture("manual-review-result");
    await click(review);
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual((await ackMessages(review)).length, 0,
      "A callback outcome other than alteration requested cannot be acknowledged as accepted");

    backendOutcome = "throw";
    const failure = await fixture("callback-failure");
    await click(failure);
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual((await ackMessages(failure)).length, 0);

    backendOutcome = "accepted";
    const expired = await fixture("expired-window");
    await click(expired, { timestamp: String(Math.floor(Date.now() / 1000) - 25 * 3600) });
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual((await ackMessages(expired)).length, 0);

    graphFails = true;
    const uncertain = await fixture("uncertain-graph");
    await click(uncertain);
    await runPendingChangeRequestAcknowledgements();
    const failed = await ackMessages(uncertain);
    assert.strictEqual(failed.length, 1);
    assert.strictEqual(failed[0].status, "failed");
    const providerCallsAfterFailure = graphRequests.length;
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual(graphRequests.length, providerCallsAfterFailure,
      "Ambiguous provider failure cannot trigger an automatic second send");
    assert.strictEqual(await needsHumanReply(uncertain.phone), true);

    graphFails = false;
    const alreadyAnswered = await fixture("human-already-replied");
    await click(alreadyAnswered);
    await query(`INSERT INTO messages (conversation_id, from_me, body, type, metadata, status, created_at)
                 VALUES ($1, TRUE, 'A equipe respondeu.', 'text', '{"source":"agent_api"}'::jsonb,
                         'sent', now())`, [alreadyAnswered.conversationId]);
    const callsBeforeHuman = graphRequests.length;
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual((await ackMessages(alreadyAnswered)).filter(
      (row) => row.metadata.source === CHANGE_REQUEST_ACK_SOURCE).length, 0,
      "A delayed acknowledgement cannot follow a successful human reply");
    assert.strictEqual(graphRequests.length, callsBeforeHuman);
    const skipped = await query<{ response_payload: Record<string, unknown> }>(
      "SELECT response_payload FROM approved_template_button_events WHERE provider_message_id = $1",
      [alreadyAnswered.clickId]);
    assert.strictEqual(skipped.rows[0].response_payload.acknowledgement_skipped, "human_already_replied");

    const retriedHuman = await fixture("retried-human-reply", false);
    const oldHuman = await query<{ id: string }>(
      `INSERT INTO messages (conversation_id, from_me, body, type, metadata, status, created_at)
       VALUES ($1, TRUE, 'Resposta humana', 'text', '{"source":"agent_api"}'::jsonb,
               'failed', now() - interval '2 minutes') RETURNING id`, [retriedHuman.conversationId]);
    await query(`INSERT INTO messages (conversation_id, wa_message_id, from_me, body, type, status, created_at)
                 VALUES ($1, $2, FALSE, 'Solicitar alteração', 'button', 'received', now())`,
      [retriedHuman.conversationId, retriedHuman.clickId]);
    await click(retriedHuman);
    await query(`UPDATE messages SET status = 'sent', created_at = now() + interval '1 second'
                 WHERE id = $1`, [oldHuman.rows[0].id]);
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual((await ackMessages(retriedHuman)).filter(
      (row) => row.metadata.source === CHANGE_REQUEST_ACK_SOURCE).length, 0,
      "A successful human retry with an older ID still prevents a late acknowledgement");

    const stale = await fixture("stale-reservation");
    await click(stale);
    await query(`INSERT INTO messages (conversation_id, from_me, body, type, metadata, status, created_at)
                 VALUES ($1, TRUE, $2, 'text', $3::jsonb, 'pending', now() - interval '6 minutes')`,
      [stale.conversationId, CHANGE_REQUEST_ACK_TEXT, JSON.stringify({
        source: CHANGE_REQUEST_ACK_SOURCE, origem: "bot",
        idempotency_key: `appointment-change-ack:${stale.clickId}`
      })]);
    const callsBeforeStale = graphRequests.length;
    await runPendingChangeRequestAcknowledgements();
    const staleMessage = (await ackMessages(stale))[0];
    assert.strictEqual(staleMessage.status, "failed");
    assert.strictEqual(staleMessage.metadata.ack_delivery_outcome, "uncertain_after_restart");
    assert.strictEqual(graphRequests.length, callsBeforeStale,
      "An uncertain reservation must never be sent automatically again");
    assert.strictEqual(await needsHumanReply(stale.phone), true);

    await query(`INSERT INTO approved_template_button_events
      (provider_message_id, template_message_id, action, from_phone,
       processing_status, response_payload, created_at, processed_at)
      SELECT 'wamid.synthetic.expired.' || $1 || '.' || n::text, $2, 'solicitar_alteracao', $3,
             'processed', $4::jsonb, now() - interval '1 second', now()
      FROM generate_series(1, 51) AS n`,
      [runId, accepted.templateId, accepted.phone, JSON.stringify({
        action: "solicitar_alteracao", result: "alteracao_solicitada", agendamento_id: 4242,
        acknowledgement_requested: true,
        acknowledgement_inbound_at: new Date(Date.now() - 25 * 3_600_000).toISOString()
      })]);
    const freshAfterExpired = await fixture("fresh-after-expired");
    await click(freshAfterExpired);
    await runPendingChangeRequestAcknowledgements();
    assert.strictEqual((await ackMessages(freshAfterExpired))[0]?.status, "sent",
      "Expired events cannot starve a newer valid acknowledgement");

    const signed = await fixture("signed-webhook", false);
    const { receiveWebhook } = await import("../src/controllers/webhookController");
    const webhookPayload = {
      object: "whatsapp_business_account",
      entry: [{ changes: [{ field: "messages", value: {
        metadata: { phone_number_id: "synthetic-change-ack-number" },
        messages: [buttonMessage(signed)]
      } }] }]
    };
    const rawBody = Buffer.from(JSON.stringify(webhookPayload));
    const hash = createHash("sha256").update(rawBody).digest("hex");
    webhookHashes.push(hash);
    const signature = `sha256=${createHmac("sha256", process.env.WHATSAPP_APP_SECRET)
      .update(rawBody).digest("hex")}`;
    const receiveSignedWebhook = async () => new Promise<void>((resolve, reject) => {
      const response = { sendStatus(status: number) {
        if (status === 200) resolve(); else reject(new Error(`Webhook returned ${status}`));
        return this;
      } } as unknown as Response;
      receiveWebhook({ body: webhookPayload, rawBody, header: () => signature } as unknown as Request, response);
    });
    const graphCallsBeforeSigned = graphRequests.length;
    await receiveSignedWebhook();
    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      const event = await query<{ processing_status: string }>(
        "SELECT processing_status FROM webhook_events WHERE payload_hash = $1", [hash]);
      if (event.rows[0]?.processing_status === "failed") assert.fail("Signed webhook failed");
      if (event.rows[0]?.processing_status === "processed"
          && (await ackMessages(signed))[0]?.status === "sent") break;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    assert.strictEqual((await ackMessages(signed))[0]?.status, "sent",
      "A signed webhook must dispatch acknowledgement after commit");
    assert.strictEqual(graphRequests.length, graphCallsBeforeSigned + 1);
    assert.strictEqual(await needsHumanReply(signed.phone), true);
    await receiveSignedWebhook();
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.strictEqual(graphRequests.length, graphCallsBeforeSigned + 1,
      "Replayed signed webhook cannot send a second acknowledgement");

    const shutdownCase = await fixture("graceful-shutdown");
    await click(shutdownCase);
    let releaseGraph: (() => void) | undefined;
    graphGate = new Promise<void>((resolve) => { releaseGraph = resolve; });
    const started = new Promise<void>((resolve) => { graphStarted = resolve; });
    const dispatch = runPendingChangeRequestAcknowledgements();
    await Promise.race([
      started,
      new Promise<void>((_, reject) => setTimeout(() => reject(new Error("Graph send did not start")), 2000))
    ]);
    const shutdown = shutdownChangeRequestAcknowledgementWorker();
    assert.strictEqual((await ackMessages(shutdownCase))[0]?.status, "pending");
    releaseGraph?.();
    await shutdown;
    await dispatch;
    graphGate = null;
    assert.strictEqual((await ackMessages(shutdownCase))[0]?.status, "sent",
      "Shutdown must wait for an in-flight provider send and its persisted result");
    console.log("Change-request acknowledgement tests passed.");
  } finally {
    axios.post = originalPost;
    for (const item of fixtures) {
      await query("DELETE FROM messages WHERE conversation_id = $1", [item.conversationId]);
      await query("DELETE FROM approved_template_messages WHERE id = $1", [item.templateId]);
      await query("DELETE FROM conversations WHERE id = $1", [item.conversationId]);
    }
    for (const hash of webhookHashes) await query("DELETE FROM webhook_events WHERE payload_hash = $1", [hash]);
    await pool.end();
  }
}

void run().catch((error) => {
  console.error("Change-request acknowledgement tests failed:", error);
  process.exitCode = 1;
});
