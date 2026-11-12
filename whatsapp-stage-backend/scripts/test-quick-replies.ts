import assert from "assert";
import axios from "axios";
import fs from "fs/promises";
import path from "path";
import { Request, Response } from "express";
import { pool, query } from "../src/services/dbService";
import { createQuickReply, listQuickReplies, updateQuickReply } from "../src/controllers/quickRepliesController";

interface Reply {
  id: string; title: string; body: string; category: string; shortcut: string; active: boolean;
  created_at: string; updated_at: string;
}
interface Result { status: number; payload: { data: Reply; code?: string; error?: string } }

async function invoke(handler: (req: Request, res: Response) => Promise<void>, body: unknown = {}, id = "1"): Promise<Result> {
  let status = 200;
  let payload: unknown;
  const res = {
    status(value: number) { status = value; return this; },
    json(value: unknown) { payload = JSON.parse(JSON.stringify(value)); return this; }
  } as unknown as Response;
  await handler({ body, params: { id } } as unknown as Request, res);
  return { status, payload } as Result;
}

async function run() {
  const db = new URL(process.env.DATABASE_URL || "");
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(db.hostname) && /test/i.test(db.pathname),
    "Use an explicit local test database; this test changes synthetic quick-reply fixtures.");
  const migration = await fs.readFile(path.resolve(__dirname, "../migrations/quick-replies.sql"), "utf8");
  await query(migration);
  const suffix = Date.now().toString(36);
  const shortcut = `test_${suffix}`;
  const base = { title: "Resposta sintética", body: "Texto de teste.\nSegunda linha.", category: "Agenda", shortcut };
  const createdIds: string[] = [];
  const seedResult = await query<Reply>("SELECT * FROM quick_replies WHERE seed_key = 'welcome'");
  const seed = seedResult.rows[0];

  try {
    for (const invalid of [
      null, [], { ...base, title: " " }, { ...base, title: "x".repeat(101) },
      { ...base, body: " " }, { ...base, body: "x".repeat(4097) },
      { ...base, category: "x".repeat(61) }, { ...base, shortcut: "/atalho" },
      { ...base, shortcut: "a" }, { ...base, shortcut: "x".repeat(33) },
      { ...base, shortcut: "duas palavras" }, { ...base, active: "false" },
      { ...base, id: "42" }
    ]) assert.strictEqual((await invoke(createQuickReply, invalid)).status, 422);

    const created = await invoke(createQuickReply, { ...base, shortcut: shortcut.toUpperCase() });
    assert.strictEqual(created.status, 201);
    const item = created.payload.data;
    createdIds.push(item.id);
    assert.strictEqual(typeof item.id, "string");
    assert.strictEqual(item.shortcut, shortcut);
    assert.strictEqual(item.active, true);
    assert.strictEqual(item.body, base.body);
    assert.ok(item.created_at && item.updated_at);

    const list = await invoke(listQuickReplies);
    assert.ok((list.payload.data as unknown as Reply[]).some((reply) => reply.id === item.id));
    assert.strictEqual((await invoke(createQuickReply, base)).status, 409);
    assert.strictEqual((await invoke(updateQuickReply, { title: "Sem versão" }, item.id)).status, 422);
    assert.strictEqual((await invoke(updateQuickReply, { title: "Versão inválida", expected_updated_at: "ontem" }, item.id)).status, 422);
    for (const id of ["0", "-1", "1.5", "abc", "9223372036854775808"]) {
      assert.strictEqual((await invoke(updateQuickReply, { title: "Inválido", expected_updated_at: item.updated_at }, id)).status, 422);
    }

    const updated = await invoke(updateQuickReply, { body: "Texto editado pela equipe", expected_updated_at: item.updated_at }, item.id);
    assert.strictEqual(updated.status, 200);
    assert.ok(Date.parse(updated.payload.data.updated_at) > Date.parse(item.updated_at));
    const stale = await invoke(updateQuickReply, { body: "Edição antiga", expected_updated_at: item.updated_at }, item.id);
    assert.strictEqual(stale.status, 409);
    assert.strictEqual(stale.payload.code, "QUICK_REPLY_STALE");
    assert.strictEqual(stale.payload.data.body, "Texto editado pela equipe");

    const concurrent = await Promise.all(["Primeira edição", "Segunda edição"].map((title) =>
      invoke(updateQuickReply, { title, expected_updated_at: updated.payload.data.updated_at }, item.id)));
    assert.deepStrictEqual(concurrent.map((result) => result.status).sort(), [200, 409]);
    const latest = concurrent.find((result) => result.status === 200)!.payload.data;
    const disabled = await invoke(updateQuickReply, { active: false, expected_updated_at: latest.updated_at }, item.id);
    assert.strictEqual(disabled.status, 200);
    assert.strictEqual(disabled.payload.data.active, false);
    assert.strictEqual((await invoke(createQuickReply, base)).status, 409, "inactive shortcuts remain reserved");
    const inactiveList = await invoke(listQuickReplies);
    assert.ok((inactiveList.payload.data as unknown as Reply[]).some((reply) => reply.id === item.id && !reply.active));
    const reactivated = await invoke(updateQuickReply, { active: true, expected_updated_at: disabled.payload.data.updated_at }, item.id);
    assert.strictEqual(reactivated.payload.data.active, true);
    assert.strictEqual((await invoke(updateQuickReply, { active: false, expected_updated_at: item.updated_at }, "9223372036854775807")).status, 404);

    const editedSeed = await invoke(updateQuickReply, {
      title: "Saudação editada pela equipe", shortcut: `seed_${suffix}`, active: false,
      expected_updated_at: new Date(seed.updated_at).toISOString()
    }, seed.id);
    assert.strictEqual(editedSeed.status, 200);
    await query(migration);
    const seeds = await query<Reply & { seed_key: string }>("SELECT * FROM quick_replies WHERE seed_key IS NOT NULL");
    assert.strictEqual(seeds.rows.length, 3, "reapplying SQL does not recreate renamed seeds");
    const preserved = seeds.rows.find((reply) => reply.seed_key === "welcome")!;
    assert.strictEqual(preserved.title, "Saudação editada pela equipe");
    assert.strictEqual(preserved.shortcut, `seed_${suffix}`);
    assert.strictEqual(preserved.active, false);

    process.env.WHATSAPP_API_AUTH_ENABLED = "true";
    process.env.WHATSAPP_ALLOWED_PAPEIS = "admin,recepcao";
    process.env.WHATSAPP_WRITE_ALLOWED_PAPEIS = "admin";
    let coreRole = "recepcao";
    const originalGet = axios.get;
    axios.get = async () => ({ data: {
      id: 99, nome: "Usuário sintético", email: "test@example.invalid", ativo: 1, papeis: [{ nome: coreRole }]
    } }) as never;
    const app = (await import("../src/app")).default;
    const server = app.listen(0, "127.0.0.1");
    try {
      await new Promise<void>((resolve) => server.once("listening", resolve));
      const address = server.address();
      assert.ok(address && typeof address !== "string");
      for (const [method, route] of [["GET", "/quick-replies"], ["POST", "/quick-replies"], ["PATCH", `/quick-replies/${item.id}`]]) {
        const response: { status: number } = await fetch(`http://127.0.0.1:${address.port}${route}`, { method });
        assert.strictEqual(response.status, 401, `${method} ${route} requires API auth`);
      }
      const read = await fetch(`http://127.0.0.1:${address.port}/quick-replies`, { headers: { Authorization: "Bearer test-only" } });
      assert.strictEqual(read.status, 200, "allowed read role can view library");
      for (const [method, route] of [["POST", "/quick-replies"], ["PATCH", `/quick-replies/${item.id}`]]) {
        const denied: { status: number } = await fetch(`http://127.0.0.1:${address.port}${route}`, {
          method, headers: { Authorization: "Bearer test-only", "Content-Type": "application/json" }, body: JSON.stringify(base)
        });
        assert.strictEqual(denied.status, 403, "read role cannot write library");
      }
      coreRole = "admin";
      const allowed = await fetch(`http://127.0.0.1:${address.port}/quick-replies`, {
        method: "POST", headers: { Authorization: "Bearer test-only", "Content-Type": "application/json" },
        body: JSON.stringify({ ...base, shortcut: `auth_${suffix}` })
      });
      assert.strictEqual(allowed.status, 201, "write role can create library phrase");
      createdIds.push(((await allowed.json()) as { data: Reply }).data.id);
    } finally {
      axios.get = originalGet;
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }

    console.log("Quick-reply contracts passed: validation, CRUD, inactive uniqueness, optimistic concurrency, seed preservation and authenticated routes.");
  } finally {
    for (const id of createdIds) await query("DELETE FROM quick_replies WHERE id = $1", [id]);
    if (seed) await query("UPDATE quick_replies SET title=$1, shortcut=$2, active=$3, updated_at=$4 WHERE id=$5",
      [seed.title, seed.shortcut, seed.active, seed.updated_at, seed.id]);
  }
}

void run().catch((error) => { console.error("Quick-reply contracts failed:", error); process.exitCode = 1; })
  .finally(() => pool.end());
