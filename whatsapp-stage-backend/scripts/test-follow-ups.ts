import assert from "assert";
import axios from "axios";
import { createHash, createHmac } from "crypto";
import { readFile } from "fs/promises";
import path from "path";
import { Request, Response } from "express";
import { pool, query } from "../src/services/dbService";
import { getFollowUp, saveFollowUp } from "../src/controllers/followUpsController";
import { listConversations, markConversationSeen, updateConversationStatus } from "../src/controllers/conversationsController";

type Handler = (req: Request, res: Response) => Promise<void>;
async function call(handler: Handler, id: string, body: unknown = {}, filters: Record<string, unknown> = {}) {
  let status = 200; let payload: any;
  const res = { status(code: number) { status = code; return this; }, json(data: unknown) { payload = JSON.parse(JSON.stringify(data)); return this; } } as unknown as Response;
  await handler({ params: { id }, query: filters, body, authUser: { id: 42, authSource: "core_api" } } as unknown as Request, res);
  return { status, ...payload };
}
async function run() {
  const url = new URL(process.env.DATABASE_URL || "");
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) && /test/.test(url.pathname), "Explicit local test database required");
  process.env.WHATSAPP_APP_SECRET = "synthetic-followup-secret";
  process.env.PHONE_NUMBER_ID = "synthetic-followup-number";
  process.env.WHATSAPP_INTERNAL_API_TOKEN = "";
  process.env.WEBHOOK_ALLOW_UNSIGNED = "false";
  const { receiveWebhook } = await import("../src/controllers/webhookController");
  const agents: string[] = []; const conversations: string[] = []; const hashes: string[] = [];
  const marker = `followup-${Date.now()}`;
  const future = () => new Date(Date.now() + 3600000).toISOString();
  try {
    for (const name of ["Equipe A", "Equipe B"]) agents.push((await query<{ id: string }>("INSERT INTO agents (name) VALUES ($1) RETURNING id", [name])).rows[0].id);
    for (let i = 0; i < 5; i++) conversations.push((await query<{ id: string }>("INSERT INTO conversations (wa_phone_number, subject) VALUES ($1, $2) RETURNING id", [`${marker}-${i}`, marker])).rows[0].id);
    const id = conversations[0];
    assert.strictEqual((await call(getFollowUp, id)).data, null);
    const base = { action: "schedule", expected_revision: 0, due_at: future(), note: "Confirmar horário combinado", agent_id: agents[0] };
    for (const invalid of [null, {}, { ...base, expected_revision: "0" }, { ...base, expected_revision: -1 }, { ...base, due_at: "2026-09-09T15:00" }, { ...base, due_at: `${new Date().getUTCFullYear()+1}-02-31T15:00:00Z` },
      { ...base, due_at: new Date(Date.now() - 1).toISOString() }, { ...base, due_at: new Date(Date.now() + 400 * 86400000).toISOString() },
      { ...base, note: " " }, { ...base, note: "x".repeat(1001) }, { ...base, agent_id: "9223372036854775808" }, { ...base, agent_id: agents }]) {
      assert.strictEqual((await call(saveFollowUp, id, invalid)).status, 422);
    }
    assert.strictEqual((await call(getFollowUp, "not-an-id")).status, 422);
    assert.strictEqual((await call(saveFollowUp, "9223372036854775807", base)).status, 404);
    assert.strictEqual((await call(saveFollowUp, id, { ...base, agent_id: "9223372036854775807" })).status, 422);
    await query("UPDATE agents SET active = FALSE WHERE id = $1", [agents[1]]);
    assert.strictEqual((await call(saveFollowUp, id, { ...base, agent_id: agents[1] })).status, 422);
    await query("UPDATE agents SET active = TRUE WHERE id = $1", [agents[1]]);
    const created = await call(saveFollowUp, id, base);
    assert.strictEqual(created.status, 200); assert.strictEqual(created.data.revision, 1);
    assert.strictEqual(created.data.agent_id, agents[0]);
    const concurrent = await Promise.all(["Nota A", "Nota B"].map(note => call(saveFollowUp, id, { ...base, expected_revision: 1, note })));
    assert.deepStrictEqual(concurrent.map(x => x.status).sort(), [200, 409]);
    const saved = await call(getFollowUp, id);
    assert.strictEqual(saved.data.revision, 2);
    await query(await readFile(path.resolve(__dirname, "../migrations/init.sql"), "utf8"));
    assert.deepStrictEqual((await call(getFollowUp, id)).data, saved.data, "migration preserves scheduled returns");
    await call(markConversationSeen, id);
    await call(updateConversationStatus, id, { status: "closed", expected_last_message_id: null });
    assert.strictEqual((await call(getFollowUp, id)).data.status, "pending", "read and conversation resolution do not silently cancel an agreement");

    const phone = `5591${id.padStart(9, "0")}`;
    await query("UPDATE conversations SET wa_phone_number=$2, wa_psid=$2 WHERE id=$1", [id, phone]);
    const inbound = async (variant: number, messageId: string) => {
      const body = { object: "whatsapp_business_account", entry: [{ id: String(variant), changes: [{ field: "messages", value: {
        metadata: { phone_number_id: "synthetic-followup-number" }, messages: [{ id: messageId, from: phone, timestamp: String(Math.floor(Date.now()/1000)), type: "text", text: { body: "Retorno sintético" } }]
      } }] }] };
      const rawBody = Buffer.from(JSON.stringify(body));
      const hash = createHash("sha256").update(rawBody).digest("hex"); hashes.push(hash);
      const signature = `sha256=${createHmac("sha256", "synthetic-followup-secret").update(rawBody).digest("hex")}`;
      await new Promise<void>((resolve, reject) => {
        const res = { status() { return this; }, json() { resolve(); }, sendStatus(code: number) { if (code === 200) resolve(); else reject(new Error(String(code))); } } as unknown as Response;
        receiveWebhook({ body, rawBody, header: () => signature } as unknown as Request, res);
      });
      const deadline = Date.now() + 5000;
      while (Date.now() < deadline) {
        const event = (await query("SELECT processing_status FROM webhook_events WHERE payload_hash=$1", [hash])).rows[0];
        assert.notStrictEqual(event?.processing_status, "failed");
        if (event?.processing_status === "processed") return;
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      assert.fail("inbound processing timed out");
    };
    await inbound(1, `${marker}-inbound`);
    const responded = (await call(getFollowUp, id)).data;
    assert.strictEqual(responded.revision, 3); assert.ok(responded.inbound_received_at);
    assert.strictEqual(responded.note, saved.data.note);
    await inbound(2, `${marker}-inbound`);
    assert.strictEqual((await call(getFollowUp, id)).data.revision, 3, "duplicate message does not change reminder");
    assert.strictEqual((await call(saveFollowUp, id, { action: "complete", expected_revision: 2 })).status, 409, "new inbound blocks stale completion");

    for (const other of conversations.slice(1)) assert.strictEqual((await call(saveFollowUp, other, { ...base, agent_id: agents[1] })).status, 200);
    await query("UPDATE conversation_follow_ups SET due_at=now()-interval '1 hour' WHERE conversation_id=$1", [conversations[1]]);
    await query("UPDATE conversation_follow_ups SET due_at=(date_trunc('day', now() AT TIME ZONE 'America/Fortaleza')+interval '1 day') AT TIME ZONE 'America/Fortaleza' WHERE conversation_id=$1", [conversations[2]]);
    await call(saveFollowUp, conversations[3], { action: "cancel", expected_revision: 1 });
    const list = (filter: string, extra = {}) => call(listConversations, "", {}, { search: marker, follow_up: filter, limit: "100", ...extra });
    const ready = await list("ready", { summary_agent_id: agents[0] });
    assert.ok(ready.data.some((c: any) => c.id === id));
    assert.ok(ready.data.some((c: any) => c.id === conversations[1]));
    assert.strictEqual(ready.summary.my_follow_up_ready, 1);
    assert.strictEqual((await list("responded")).data.length, 1);
    assert.ok((await list("upcoming")).data.some((c: any) => c.id === conversations[2]), "Fortaleza midnight belongs to upcoming");
    assert.ok(!(await list("today")).data.some((c: any) => [conversations[1], conversations[2]].includes(c.id)), "today excludes overdue and next midnight");
    assert.strictEqual((await list("all", { follow_up_agent_id: agents[0] })).data.length, 1);
    assert.ok(!(await list("all")).data.some((c: any) => c.id === conversations[3]), "cancelled hidden");
    for (const invalid of ["bad", ["due", "all"], ""]) assert.strictEqual((await list(invalid as string)).status, 422);
    assert.strictEqual((await list("all", { follow_up_agent_id: "0" })).status, 422);
    assert.strictEqual((await list("all", { summary_agent_id: "bad" })).status, 422);
    const completed = await call(saveFollowUp, id, { action: "complete", expected_revision: 3 });
    assert.strictEqual(completed.data.status, "completed");
    await inbound(3, `${marker}-later`);
    assert.strictEqual((await call(getFollowUp, id)).data.revision, 4, "completed reminder is not reactivated by inbound");
    assert.strictEqual((await call(saveFollowUp, id, base)).status, 409, "terminal row preserves version against stale recreate");
    const rescheduled = await call(saveFollowUp, id, { ...base, expected_revision: 4, agent_id: agents[1] });
    assert.strictEqual(rescheduled.data.inbound_received_at, null); assert.strictEqual(rescheduled.data.revision, 5);
    const audit = await query("SELECT payload FROM audit_logs WHERE conversation_id=$1 AND action='conversation_follow_up_changed'", [id]);
    assert.ok(audit.rows.every(row => row.payload.actor_user_id === 42 && !('note' in row.payload)), "audit actor without duplicating private note");

    process.env.WHATSAPP_API_AUTH_ENABLED = "true";
    process.env.WHATSAPP_ALLOWED_PAPEIS = "reader,admin";
    process.env.WHATSAPP_WRITE_ALLOWED_PAPEIS = "admin";
    const originalGet = axios.get; let role = "reader";
    axios.get = (async () => ({ data: { id: 42, email: "synthetic@example.com", nome: "Synthetic", ativo: 1, papeis: [{ nome: role }] } })) as never;
    const app = (await import("../src/app")).default;
    const server = app.listen(0, "127.0.0.1");
    try {
      await new Promise<void>(resolve => server.once("listening", resolve));
      const address = server.address(); assert.ok(address && typeof address !== "string");
      const route = `http://127.0.0.1:${address.port}/conversations/${id}/follow-up`;
      for (const method of ["GET", "PATCH"]) assert.strictEqual((await fetch(route, { method })).status, 401);
      const auth = { Authorization: "Bearer synthetic-only", "Content-Type": "application/json" };
      assert.strictEqual((await fetch(route, { headers: auth })).status, 200);
      assert.strictEqual((await fetch(route, { method: "PATCH", headers: auth, body: JSON.stringify({ action: "cancel", expected_revision: 5 }) })).status, 403);
      role = "admin";
      assert.strictEqual((await fetch(route, { method: "PATCH", headers: auth, body: JSON.stringify({ action: "cancel", expected_revision: 5 }) })).status, 200);
    } finally { axios.get = originalGet; await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); }
    console.log("Follow-up contracts passed: validation, migration, concurrency, inbound/dedup, due queues, timezone, completion/reschedule, audit and HTTP auth.");
  } finally {
    await query("DELETE FROM webhook_events WHERE payload_hash = ANY($1::text[])", [hashes]);
    await query("DELETE FROM audit_logs WHERE conversation_id = ANY($1::bigint[])", [conversations]);
    await query("DELETE FROM conversations WHERE id = ANY($1::bigint[])", [conversations]);
    await query("DELETE FROM agents WHERE id = ANY($1::bigint[])", [agents]);
  }
}
void run().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => pool.end());
