import "dotenv/config";
import assert from "assert";
import { Request, Response } from "express";
import { pool, query } from "../src/services/dbService";
import { executeSmokeCleanup, previewSmokeCleanup } from "../src/controllers/smokeCleanupController";

function fakeResponse(): { response: Response; payload(): unknown } {
  let captured: unknown = null;
  const response = {
    json(payload: unknown) {
      captured = payload;
      return this;
    },
    status() {
      return this;
    }
  } as unknown as Response;
  return { response, payload: () => captured };
}

async function run(): Promise<void> {
  const runId = `${Date.now()}${Math.floor(Math.random() * 1000)}`;

  const controlConversation = await query<{ id: string }>(
    `INSERT INTO conversations (wa_phone_number, subject) VALUES ($1, $2) RETURNING id`,
    [`55850000${runId}`.slice(0, 20), `Contato real ${runId}`]
  );
  const controlAgent = await query<{ id: string }>(
    `INSERT INTO agents (name, email) VALUES ($1, $2) RETURNING id`,
    [`Atendente Real ${runId}`, `atendente.real.${runId}@fortcordis.com`]
  );

  const smokeConversation = await query<{ id: string }>(
    `INSERT INTO conversations (wa_phone_number, subject) VALUES ($1, $2) RETURNING id`,
    [`5511${runId}`.slice(0, 20), `Smoke User ${runId}`]
  );
  const smokeAgent = await query<{ id: string }>(
    `INSERT INTO agents (name, email) VALUES ($1, $2) RETURNING id`,
    ["Agent Smoke", `agent.smoke.${runId}@example.com`]
  );
  const smokeWaMessageId = `wamid.smoke.${runId}.inbound`;
  await query(
    `INSERT INTO messages (conversation_id, wa_message_id, from_me, body) VALUES ($1, $2, false, $3)`,
    [smokeConversation.rows[0].id, smokeWaMessageId, "smoke test message"]
  );
  await query(
    `INSERT INTO message_status_events (wa_message_id, conversation_id, status, payload) VALUES ($1, $2, $3, $4::jsonb)`,
    [smokeWaMessageId, smokeConversation.rows[0].id, "sent", JSON.stringify({ source: "smoke-cleanup-test" })]
  );
  await query(
    `INSERT INTO webhook_events (payload, raw_body, payload_hash) VALUES ($1::jsonb, $2, $3)`,
    [
      JSON.stringify({ entry: [{ id: "WABA_SMOKE" }] }),
      `{"wamid":"${smokeWaMessageId}"}`,
      `smoke-cleanup-${runId}`
    ]
  );
  await query(
    `INSERT INTO audit_logs (conversation_id, agent_id, action, payload) VALUES ($1, $2, $3, $4::jsonb)`,
    [smokeConversation.rows[0].id, smokeAgent.rows[0].id, "smoke_cleanup_test", JSON.stringify({})]
  );

  const previewCall = fakeResponse();
  await previewSmokeCleanup({} as Request, previewCall.response);
  const preview = previewCall.payload() as {
    would_delete: { conversations: number; agents: number };
    sample_conversation_ids: string[];
  };
  assert.ok(preview.would_delete.conversations >= 1, "preview deve contar ao menos a conversa de smoke criada");
  assert.ok(
    preview.sample_conversation_ids.includes(smokeConversation.rows[0].id),
    "preview deve listar a conversa de smoke criada neste teste"
  );

  const forbiddenCall = fakeResponse();
  let forbiddenStatus = 0;
  const forbiddenResponse = {
    ...forbiddenCall.response,
    status(code: number) {
      forbiddenStatus = code;
      return this as unknown as Response;
    }
  } as unknown as Response;
  await executeSmokeCleanup({ authUser: { papeis: ["recepcao"] } } as unknown as Request, forbiddenResponse);
  assert.strictEqual(forbiddenStatus, 403, "execute deve recusar quem nao tem papel admin");

  const executeCall = fakeResponse();
  await executeSmokeCleanup({ authUser: { papeis: ["admin"] } } as unknown as Request, executeCall.response);

  const remainingSmokeConversation = await query(`SELECT id FROM conversations WHERE id = $1`, [
    smokeConversation.rows[0].id
  ]);
  const remainingSmokeAgent = await query(`SELECT id FROM agents WHERE id = $1`, [smokeAgent.rows[0].id]);
  const remainingMessages = await query(`SELECT id FROM messages WHERE wa_message_id = $1`, [smokeWaMessageId]);
  const remainingStatusEvents = await query(`SELECT id FROM message_status_events WHERE wa_message_id = $1`, [
    smokeWaMessageId
  ]);
  const remainingWebhookEvents = await query(`SELECT id FROM webhook_events WHERE payload_hash = $1`, [
    `smoke-cleanup-${runId}`
  ]);
  assert.strictEqual(remainingSmokeConversation.rowCount, 0, "conversa de smoke deveria ter sido apagada");
  assert.strictEqual(remainingSmokeAgent.rowCount, 0, "agente de smoke deveria ter sido apagado");
  assert.strictEqual(remainingMessages.rowCount, 0, "mensagem de smoke deveria ter sido apagada em cascata");
  assert.strictEqual(remainingStatusEvents.rowCount, 0, "message_status_events de smoke deveria ter sido apagado");
  assert.strictEqual(remainingWebhookEvents.rowCount, 0, "webhook_events de smoke deveria ter sido apagado");

  const remainingControlConversation = await query(`SELECT id FROM conversations WHERE id = $1`, [
    controlConversation.rows[0].id
  ]);
  const remainingControlAgent = await query(`SELECT id FROM agents WHERE id = $1`, [controlAgent.rows[0].id]);
  assert.strictEqual(remainingControlConversation.rowCount, 1, "conversa real (nao-smoke) nao deveria ser tocada");
  assert.strictEqual(remainingControlAgent.rowCount, 1, "agente real (nao-smoke) nao deveria ser tocado");

  await query(`DELETE FROM conversations WHERE id = $1`, [controlConversation.rows[0].id]);
  await query(`DELETE FROM agents WHERE id = $1`, [controlAgent.rows[0].id]);

  console.log("Smoke cleanup preview/execute contracts passed.");
}

void run()
  .catch((error) => {
    console.error("Smoke cleanup test failed:", error);
    process.exit(1);
  })
  .finally(() => {
    void pool.end();
  });
