import "dotenv/config";
import assert from "assert";
import { Request, Response } from "express";
import { pool, query } from "../src/services/dbService";
import { listConversations } from "../src/controllers/conversationsController";

function fakeResponse(): { response: Response; payload(): any } {
  let captured: unknown = null;
  const response = {
    status() {
      return this;
    },
    json(payload: unknown) {
      captured = payload;
      return this;
    }
  } as unknown as Response;
  return { response, payload: () => captured };
}

async function insertConversation(params: {
  waPhoneNumber: string;
  subject: string;
  lastInboundAt: string | null;
  lastSeenAt: string | null;
  lastActivityAt: string;
}): Promise<string> {
  const result = await query<{ id: string }>(
    `
      INSERT INTO conversations (wa_phone_number, subject, last_inbound_at, last_seen_at, last_activity_at)
      VALUES ($1, $2, $3, $4, $5)
      RETURNING id
    `,
    [params.waPhoneNumber, params.subject, params.lastInboundAt, params.lastSeenAt, params.lastActivityAt]
  );
  return result.rows[0].id;
}

async function run(): Promise<void> {
  const runId = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const marker = `Ordering Test ${runId}`;
  const now = Date.now();
  const hoursAgo = (h: number) => new Date(now - h * 60 * 60 * 1000).toISOString();

  const conversationIds: string[] = [];

  try {
    // Nao lida, esperando ha pouco tempo.
    conversationIds.push(await insertConversation({
      waPhoneNumber: `55850001${runId}`.slice(0, 20),
      subject: `${marker} A-nao-lida-recente`,
      lastInboundAt: hoursAgo(2),
      lastSeenAt: null,
      lastActivityAt: hoursAgo(2),
    }));

    // Nao lida, esperando ha mais tempo - deve vir antes da anterior.
    conversationIds.push(await insertConversation({
      waPhoneNumber: `55850002${runId}`.slice(0, 20),
      subject: `${marker} B-nao-lida-antiga`,
      lastInboundAt: hoursAgo(5),
      lastSeenAt: null,
      lastActivityAt: hoursAgo(5),
    }));

    // Lida ha tempos, sem atividade recente.
    conversationIds.push(await insertConversation({
      waPhoneNumber: `55850003${runId}`.slice(0, 20),
      subject: `${marker} C-lida-antiga`,
      lastInboundAt: hoursAgo(30 * 24),
      lastSeenAt: hoursAgo(24),
      lastActivityAt: hoursAgo(30 * 24),
    }));

    // So enviamos (reserva automatica), nunca recebeu nada - atividade agora mesmo.
    // Bug: antes da correcao, essa conversa caia sempre por ultimo (NULLS LAST
    // globalmente), mesmo sendo a mais recente de todas as "nao urgentes".
    conversationIds.push(await insertConversation({
      waPhoneNumber: `55850004${runId}`.slice(0, 20),
      subject: `${marker} D-so-enviada-agora`,
      lastInboundAt: null,
      lastSeenAt: null,
      lastActivityAt: hoursAgo(0),
    }));

    const call = fakeResponse();
    await listConversations(
      { query: { search: marker, limit: "20" } } as unknown as Request,
      call.response
    );

    const order = call.payload().data.map((row: any) => row.subject as string);

    assert.deepStrictEqual(order, [
      `${marker} B-nao-lida-antiga`,
      `${marker} A-nao-lida-recente`,
      `${marker} D-so-enviada-agora`,
      `${marker} C-lida-antiga`,
    ], `ordem inesperada: ${JSON.stringify(order)}`);

    console.log("Conversation ordering contract tests passed.");
  } finally {
    for (const id of conversationIds) {
      await query(`DELETE FROM messages WHERE conversation_id = $1`, [id]);
      await query(`DELETE FROM conversations WHERE id = $1`, [id]);
    }
  }
}

void run()
  .catch((error) => {
    console.error("Conversation ordering test failed:", error);
    process.exit(1);
  })
  .finally(() => {
    void pool.end();
  });
