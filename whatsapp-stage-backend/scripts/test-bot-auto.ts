import assert from "assert";
import axios from "axios";
import { Request, Response } from "express";
import { pool, query } from "../src/services/dbService";
import { listConversationMessages, listConversations, reservePendingTextMessage, resolveTextMessageMetadata, sendConversationMessage } from "../src/controllers/conversationsController";

async function readContext(
  handler: (req: Request, res: Response) => Promise<void>,
  conversationId: string,
  queryParams: Record<string, unknown> = {},
  authSource: string | undefined = "internal_token"
): Promise<{ status: number; payload: any }> {
  let status = 200;
  let payload: unknown;
  await handler({
    params: { id: conversationId }, query: queryParams,
    ...(authSource ? { authUser: { authSource } } : {})
  } as unknown as Request, {
    status(value: number) { status = value; return this; },
    json(value: unknown) { payload = value; return this; }
  } as unknown as Response);
  return { status, payload: JSON.parse(JSON.stringify(payload)) };
}

async function run() {
  const url = new URL(process.env.DATABASE_URL || "");
  assert.ok(url.hostname === "127.0.0.1" && /test/.test(url.pathname));
  process.env.WHATSAPP_BOT_AUTO_SEND_ENABLED = "true";
  const conversations: string[] = [];
  let agentId: string | undefined;
  const metadata = (id: string) => ({ source: "bot_auto", origem: "bot", resposta_id: id,
    idempotency_key: `whatsapp-bot-resposta-${id}`, inbound_wa_message_id: `wamid.${id}` });
  const create = async (id: string) => {
    const r = await query<{id: string}>("INSERT INTO conversations (wa_phone_number, last_inbound_at) VALUES ($1, now()) RETURNING id", [`5585000${id}`]);
    const cid = r.rows[0].id;
    conversations.push(cid);
    await query("INSERT INTO messages (conversation_id, from_me, body, type, wa_message_id, status) VALUES ($1, false, 'horario?', 'text', $2, 'received')", [cid, `wamid.${id}`]);
    return cid;
  };
  const request = (cid: string, id: string) => ({ params: {id: cid}, body: {body: "Resposta publica", type: "text", metadata: metadata(id)}, authUser: {authSource: "internal_token"} } as unknown as Request);
  const reaction = async (cid: string, fromMe = false) => {
    const inserted = await query<{ id: string }>(
      "INSERT INTO messages (conversation_id, from_me, body, type, status) VALUES ($1, $2, 'Reagiu com 👍', 'reaction', $3) RETURNING id",
      [cid, fromMe, fromMe ? "sent" : "received"]
    );
    return inserted.rows[0].id;
  };
  let graphCalls = 0;
  const originalPost = axios.post;
  axios.post = (async () => { graphCalls++; throw Object.assign(new Error("simulated timeout"), {code: "ETIMEDOUT"}); }) as typeof axios.post;
  try {
    const req = request("1", "101");
    assert.deepStrictEqual(resolveTextMessageMetadata(req), metadata("101"));
    assert.strictEqual(resolveTextMessageMetadata({...req, authUser: {authSource: "core_api"}} as unknown as Request), null);
    assert.strictEqual(resolveTextMessageMetadata({...req, body: {metadata: {...metadata("101"), inbound_wa_message_id: ""}}} as Request), null);

    for (const handler of [listConversations, listConversationMessages]) {
      for (const bot_context of ["1", "yes", "", ["true"], true]) {
        assert.strictEqual((await readContext(handler, "1", { bot_context })).status, 422);
      }
      for (const authSource of ["core_api", ""]) {
        assert.strictEqual((await readContext(handler, "1", { bot_context: "true" }, authSource)).status, 403);
      }
    }

    // A reaction during debounce cannot supersede the question, disappear from
    // the inbox, or move the inbox revision frontier backwards.
    const reacted = await create("201");
    const reactionId = await reaction(reacted);
    const inbox = await readContext(listConversations, reacted, { phone: "5585000201" });
    const botInbox = await readContext(listConversations, reacted, { phone: "5585000201", bot_context: "true" });
    assert.strictEqual(inbox.payload.data[0].last_message_type, "reaction");
    assert.strictEqual(botInbox.payload.data[0].last_message_wa_message_id, "wamid.201");
    assert.strictEqual(inbox.payload.data[0].last_message_id, reactionId);
    assert.strictEqual(botInbox.payload.data[0].last_message_id, reactionId);
    for (const bot_context of [undefined, "false"]) {
      const full = await readContext(listConversationMessages, reacted, { limit: "1", page: "2", bot_context });
      assert.strictEqual(full.payload.pagination.total, 2);
      assert.strictEqual(full.payload.data[0].type, "reaction");
      assert.strictEqual(full.payload.last_message_id, reactionId);
    }
    for (const order of ["latest", "oldest"]) {
      const context = await readContext(listConversationMessages, reacted, { bot_context: "true", limit: "1", order });
      assert.strictEqual(context.payload.pagination.total, 1);
      assert.strictEqual(context.payload.data[0].wa_message_id, "wamid.201");
      assert.strictEqual(context.payload.last_message_id, reactionId);
      const nextPage = await readContext(listConversationMessages, reacted, { bot_context: "true", limit: "1", page: "2", order });
      assert.deepStrictEqual(nextPage.payload.data, []);
    }
    const reactedReservation = await reservePendingTextMessage(reacted, "Resposta", "text", metadata("201"));
    assert.strictEqual(reactedReservation.status, "pending");
    assert.strictEqual(reactedReservation.idempotent, false);
    await reaction(reacted);
    const repeatedReservation = await reservePendingTextMessage(reacted, "Resposta", "text", metadata("201"));
    assert.strictEqual(repeatedReservation.id, reactedReservation.id);
    assert.strictEqual(repeatedReservation.idempotent, true);
    const botAfterReservation = await readContext(listConversations, reacted, { phone: "5585000201", bot_context: "true" });
    assert.strictEqual(botAfterReservation.payload.data[0].last_message_from_me, true);

    const reactionOnly = await create("202");
    await query("DELETE FROM messages WHERE conversation_id=$1", [reactionOnly]);
    const onlyReactionId = await reaction(reactionOnly);
    const empty = await readContext(listConversationMessages, reactionOnly, { bot_context: "true" });
    assert.strictEqual(empty.payload.pagination.total, 0);
    assert.deepStrictEqual(empty.payload.data, []);
    assert.strictEqual(empty.payload.last_message_id, onlyReactionId);
    const emptyInbox = await readContext(listConversations, reactionOnly, { phone: "5585000202", bot_context: "true" });
    assert.strictEqual(emptyInbox.payload.data[0].last_message_at, null);
    assert.strictEqual((await reservePendingTextMessage(reactionOnly, "Resposta", "text", metadata("202"))).status, "bot_conversation_changed");

    // A recent reaction can update the conversation timestamp, but cannot
    // authorize an automatic answer to an expired effective inbound message.
    const expiredQuestion = await create("203");
    await query("UPDATE messages SET created_at=now() - interval '25 hours' WHERE conversation_id=$1", [expiredQuestion]);
    await reaction(expiredQuestion);
    assert.strictEqual((await reservePendingTextMessage(expiredQuestion, "Resposta", "text", metadata("203"))).status, "bot_conversation_changed");

    // Only inbound reaction events are skipped. Later questions, media and all
    // human activity continue to invalidate a response to an older question.
    for (const [index, message] of [
      { fromMe: false, type: "text", body: "outra pergunta" },
      { fromMe: false, type: "audio", body: "[audio]" },
      { fromMe: false, type: "image", body: "[image]" },
      { fromMe: true, type: "reaction", body: "Reagiu com 👍" },
      { fromMe: true, type: "text", body: "resposta humana" }
    ].entries()) {
      const id = String(210 + index);
      const changed = await create(id);
      await query(
        "INSERT INTO messages (conversation_id, from_me, body, type, wa_message_id, status) VALUES ($1,$2,$3,$4,$5,$6)",
        [changed, message.fromMe, message.body, message.type, `wamid.changed.${id}`, message.fromMe ? "sent" : "received"]
      );
      await reaction(changed);
      const context = await readContext(listConversationMessages, changed, { bot_context: "true", order: "latest", limit: "1" });
      assert.strictEqual(context.payload.pagination.total, 2);
      assert.strictEqual(context.payload.data[0].wa_message_id, `wamid.changed.${id}`);
      assert.strictEqual((await reservePendingTextMessage(changed, "Resposta", "text", metadata(id))).status, "bot_conversation_changed");
    }

    const cid = await create("101");
    const reservations = await Promise.all([
      reservePendingTextMessage(cid, "Resposta", "text", metadata("101")),
      reservePendingTextMessage(cid, "Resposta", "text", metadata("101")),
    ]);
    assert.strictEqual(reservations.filter(r => !r.idempotent).length, 1);
    assert.strictEqual(reservations[0].id, reservations[1].id);
    await query("UPDATE messages SET status='failed' WHERE id=$1", [reservations[0].id]);
    const retry = await reservePendingTextMessage(cid, "Resposta", "text", metadata("101"));
    assert.strictEqual(retry.idempotent, true);
    assert.strictEqual(retry.status, "failed");

    for (const [i, change] of [
      "UPDATE conversations SET last_inbound_at = now() - interval '25 hours' WHERE id=$1",
      "INSERT INTO messages (conversation_id, from_me, body, type, wa_message_id, status) VALUES ($1, false, 'outra pergunta', 'text', 'wamid.new', 'received')",
      "INSERT INTO messages (conversation_id, from_me, body, type, status) VALUES ($1, true, 'resposta humana', 'text', 'sent')",
    ].entries()) {
      const id = String(110+i);
      const changed = await create(id);
      await query(change, [changed]);
      assert.strictEqual((await reservePendingTextMessage(changed, "Resposta", "text", metadata(id))).status, "bot_conversation_changed");
    }
    const agent = await query<{id: string}>("INSERT INTO agents (name,email) VALUES ('Bot Test', 'bot-operacao@example.invalid') RETURNING id");
    agentId = agent.rows[0].id;
    const claimed = await create("119");
    await query("UPDATE conversations SET last_agent_id=$2 WHERE id=$1", [claimed, agentId]);
    await reaction(claimed);
    assert.strictEqual((await reservePendingTextMessage(claimed, "Resposta", "text", metadata("119"))).status, "bot_conversation_changed");

    const disabled = await create("120");
    process.env.WHATSAPP_BOT_AUTO_SEND_ENABLED = "false";
    assert.strictEqual((await reservePendingTextMessage(disabled, "Resposta", "text", metadata("120"))).status, "bot_conversation_changed");
    process.env.WHATSAPP_BOT_AUTO_SEND_ENABLED = "true";

    const timeout = await create("130");
    let status = 0;
    const res = {status(value: number) {status=value;return this;}, json() {return this;}} as unknown as Response;
    await sendConversationMessage(request(timeout, "130"), res);
    assert.strictEqual(status, 502);
    assert.strictEqual(graphCalls, 1, "automatic Graph calls never retry an ambiguous failure");
    await sendConversationMessage(request(timeout, "130"), res);
    assert.strictEqual(status, 409);
    assert.strictEqual(graphCalls, 1, "repeated HTTP requests cannot send again");
    console.log("Automatic bot contracts passed: internal bot context, inbound reactions, complete inbox revisions, concurrent reservation, stale reply, human activity, window, kill switch, ambiguous delivery.");
  } finally {
    axios.post = originalPost;
    await query("DELETE FROM messages WHERE conversation_id = ANY($1::bigint[])", [conversations]);
    await query("DELETE FROM conversations WHERE id = ANY($1::bigint[])", [conversations]);
    if (agentId) await query("DELETE FROM agents WHERE id=$1", [agentId]);
    await pool.end();
  }
}
run().catch(e => { console.error(e); process.exitCode=1; });
