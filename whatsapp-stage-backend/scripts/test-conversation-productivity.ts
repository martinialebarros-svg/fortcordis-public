import assert from "assert";
import { Request, Response } from "express";
import { pool, query } from "../src/services/dbService";
import {
  listConversationMessages,
  listConversations
} from "../src/controllers/conversationsController";

interface ListPayload {
  data: Array<{ id: string; subject: string; unread: boolean; body?: string }>;
  pagination: { page: number; limit: number; total: number };
  summary: Record<string, number>;
}

async function callController(
  handler: (req: Request, res: Response) => Promise<void>,
  queryParams: Record<string, unknown>,
  params: Record<string, string> = {}
): Promise<{ status: number; payload: ListPayload }> {
  let status = 200;
  let payload: unknown;
  const response = {
    status(value: number) { status = value; return this; },
    json(value: unknown) { payload = value; return this; }
  } as unknown as Response;
  await handler({ query: queryParams, params } as unknown as Request, response);
  return { status, payload: payload as ListPayload };
}

async function run(): Promise<void> {
  const databaseUrl = new URL(process.env.DATABASE_URL || "");
  assert.ok(
    ["127.0.0.1", "localhost", "[::1]"].includes(databaseUrl.hostname)
      && /test/i.test(databaseUrl.pathname),
    "Use an explicit local test database; these contracts create and remove synthetic fixtures."
  );

  for (const agent_id of ["0", "-1", "1.5", "1 OR 1=1", "9223372036854775808", ["1", "2"]]) {
    assert.strictEqual((await callController(listConversations, { agent_id })).status, 422);
  }
  for (const unread of ["yes", "1", "", ["true", "false"]]) {
    assert.strictEqual((await callController(listConversations, { unread })).status, 422);
  }
  assert.strictEqual((await callController(listConversations, { search: ["a", "b"] })).status, 422);
  assert.strictEqual((await callController(listConversationMessages, { order: "unexpected" }, { id: "1" })).status, 422);

  const baseline = (await callController(listConversations, { limit: "1" })).payload.summary;
  const marker = `Productivity ${Date.now()}`;
  const phoneLocal = `8${String(Date.now()).slice(-7)}`;
  const conversationIds: string[] = [];
  const agentIds: string[] = [];
  const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

  try {
    for (const suffix of ["a", "b"]) {
      const agent = await query<{ id: string }>(
        "INSERT INTO agents (name, email) VALUES ($1, $2) RETURNING id",
        [`${marker} ${suffix}`, `${marker.replace(/ /g, "-")}-${suffix}@example.invalid`]
      );
      agentIds.push(agent.rows[0].id);
    }
    const fixtures = [
      { status: "open", agent: agentIds[0], inbound: hoursAgo(5), seen: null },
      { status: "pending", agent: agentIds[0], inbound: hoursAgo(6), seen: hoursAgo(4) },
      { status: "open", agent: agentIds[1], inbound: hoursAgo(3), seen: null },
      { status: "closed", agent: null, inbound: null, seen: null },
      { status: "pending", agent: null, inbound: hoursAgo(1), seen: null }
    ];
    for (const [index, fixture] of fixtures.entries()) {
      const inserted = await query<{ id: string }>(
        `INSERT INTO conversations
          (wa_phone_number, subject, status, last_agent_id, last_inbound_at, last_seen_at)
         VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`,
        [
          index === 0 ? `5585${phoneLocal}` : `5586${phoneLocal}${index}`,
          `${marker} ${index}`, fixture.status, fixture.agent, fixture.inbound, fixture.seen
        ]
      );
      conversationIds.push(inserted.rows[0].id);
    }

    const firstPage = (await callController(listConversations, { search: marker, limit: "2" })).payload;
    assert.strictEqual(firstPage.data.length, 2);
    assert.strictEqual(firstPage.pagination.total, 5, "pagination counts the entire matching list");
    for (const [key, added] of Object.entries({ total: 5, unread: 3, unassigned: 2, open: 2, pending: 2, closed: 1 })) {
      assert.strictEqual(firstPage.summary[key], baseline[key] + added, `${key} counts every page and status`);
    }
    assert.ok(!("mine" in firstPage.summary), "mine is omitted without an agent_id");

    const mine = (await callController(listConversations, {
      search: marker, agent_id: agentIds[0], unread: "true", status: "open", assigned: "assigned"
    })).payload;
    assert.deepStrictEqual(mine.data.map((row) => row.id), [conversationIds[0]]);
    assert.strictEqual(mine.pagination.total, 1);
    assert.strictEqual(mine.summary.mine, 2, "mine ignores status and unread filters");
    assert.strictEqual(mine.summary.total, baseline.total + 5, "global totals ignore filters");

    const unread = (await callController(listConversations, { search: marker, unread: "true" })).payload;
    assert.deepStrictEqual(unread.data.map((row) => row.id), [conversationIds[0], conversationIds[2], conversationIds[4]]);
    const read = (await callController(listConversations, { search: marker, unread: "false" })).payload;
    assert.strictEqual(read.pagination.total, 2, "outbound-only conversations count as read");
    assert.ok(read.data.every((row) => !row.unread));
    assert.strictEqual((await callController(listConversations, {
      search: marker, assigned: "unassigned", agent_id: agentIds[0]
    })).payload.pagination.total, 0, "conflicting filters stay an intersection");
    assert.strictEqual((await callController(listConversations, {
      search: `${marker} absent`
    })).payload.summary.total, baseline.total + 5, "empty searches retain global counters");

    for (const search of [
      `+55 (85) 9${phoneLocal.slice(0, 4)}-${phoneLocal.slice(4)}`,
      `(85) 9${phoneLocal.slice(0, 4)}-${phoneLocal.slice(4)}`,
      `55 85 ${phoneLocal.slice(0, 4)} ${phoneLocal.slice(4)}`,
      phoneLocal
    ]) {
      const found = (await callController(listConversations, { search })).payload;
      assert.ok(found.data.some((row) => row.id === conversationIds[0]), "formatted phones match the stored identity");
    }
    const phoneAlias = (await callController(listConversations, { phone: `+55 (85) ${phoneLocal}` })).payload;
    assert.ok(phoneAlias.data.some((row) => row.id === conversationIds[0]), "legacy phone query stays supported");

    await query(
      `INSERT INTO messages (conversation_id, from_me, body, created_at)
       SELECT $1, TRUE, $2 || sequence::text, '2026-01-01T00:00:00Z'::timestamptz
       FROM generate_series(1, 65) AS sequence`,
      [conversationIds[0], `${marker} message `]
    );
    const lastMessageSearch = (await callController(listConversations, { search: `${marker} message 65` })).payload;
    assert.deepStrictEqual(lastMessageSearch.data.map((row) => row.id), [conversationIds[0]], "latest message body remains searchable");

    const latest = (await callController(listConversationMessages, {
      order: "latest", limit: "50", page: "1"
    }, { id: conversationIds[0] })).payload;
    assert.strictEqual(latest.pagination.total, 65);
    assert.strictEqual(latest.data.length, 50);
    assert.strictEqual(latest.data[0].body, `${marker} message 16`);
    assert.strictEqual(latest.data[49].body, `${marker} message 65`, "newest message is visible immediately");
    const history = (await callController(listConversationMessages, {
      order: "latest", limit: "50", page: "2"
    }, { id: conversationIds[0] })).payload;
    assert.strictEqual(history.data.length, 15);
    assert.strictEqual(history.data[0].body, `${marker} message 1`);
    assert.strictEqual(history.data[14].body, `${marker} message 15`);
    assert.strictEqual(new Set([...latest.data, ...history.data].map((row) => row.id)).size, 65,
      "message pages have no overlap, including identical timestamps");
    const legacy = (await callController(listConversationMessages, { limit: "50" }, { id: conversationIds[0] })).payload;
    assert.strictEqual(legacy.data[0].body, `${marker} message 1`);
    assert.strictEqual(legacy.data[49].body, `${marker} message 50`, "legacy ordering remains unchanged");

    console.log("Conversation productivity contracts passed: filters, global counters, formatted phones and latest history.");
  } finally {
    for (const id of conversationIds) await query("DELETE FROM conversations WHERE id = $1", [id]);
    for (const id of agentIds) await query("DELETE FROM agents WHERE id = $1", [id]);
  }
}

void run()
  .catch((error) => {
    console.error("Conversation productivity contract failed:", error);
    process.exitCode = 1;
  })
  .finally(() => pool.end());
