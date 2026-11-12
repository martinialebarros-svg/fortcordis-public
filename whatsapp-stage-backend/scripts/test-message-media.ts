import "dotenv/config";
import assert from "assert";
import { Request, Response } from "express";
import { pool, query } from "../src/services/dbService";
import { getMessageMedia } from "../src/controllers/conversationsController";

function fakeResponse(): { response: Response; status(): number; payload(): unknown; headers(): Record<string, string> } {
  let statusCode = 200;
  let captured: unknown = null;
  const headers: Record<string, string> = {};
  const response = {
    status(code: number) {
      statusCode = code;
      return this;
    },
    json(payload: unknown) {
      captured = payload;
      return this;
    },
    setHeader(name: string, value: string) {
      headers[name] = value;
      return this;
    },
    send(payload: unknown) {
      captured = payload;
      return this;
    }
  } as unknown as Response;
  return { response, status: () => statusCode, payload: () => captured, headers: () => headers };
}

async function run(): Promise<void> {
  const runId = `${Date.now()}${Math.floor(Math.random() * 1000)}`;

  const conversation = await query<{ id: string }>(
    `INSERT INTO conversations (wa_phone_number, subject) VALUES ($1, $2) RETURNING id`,
    [`558590${runId}`.slice(0, 20), `Teste Midia ${runId}`]
  );
  const conversationId = conversation.rows[0].id;

  const textMessage = await query<{ id: string }>(
    `INSERT INTO messages (conversation_id, wa_message_id, from_me, body, type, metadata)
     VALUES ($1, $2, false, 'Oi', 'text', $3::jsonb) RETURNING id`,
    [conversationId, `wamid.test.${runId}.text`, JSON.stringify({ message: { type: "text", text: { body: "Oi" } } })]
  );
  const documentMessage = await query<{ id: string }>(
    `INSERT INTO messages (conversation_id, wa_message_id, from_me, body, type, metadata)
     VALUES ($1, $2, false, 'teste.pdf', 'document', $3::jsonb) RETURNING id`,
    [
      conversationId,
      `wamid.test.${runId}.document`,
      JSON.stringify({ message: { type: "document", document: { id: `fake-media-${runId}`, filename: "teste.pdf" } } })
    ]
  );
  const imageWithoutIdMessage = await query<{ id: string }>(
    `INSERT INTO messages (conversation_id, wa_message_id, from_me, body, type, metadata)
     VALUES ($1, $2, false, '[image]', 'image', $3::jsonb) RETURNING id`,
    [conversationId, `wamid.test.${runId}.image`, JSON.stringify({ message: { type: "image", image: {} } })]
  );

  try {
    const notFoundCall = fakeResponse();
    await getMessageMedia({ params: { id: conversationId, messageId: "999999999" } } as unknown as Request, notFoundCall.response);
    assert.strictEqual(notFoundCall.status(), 404, "mensagem inexistente deveria retornar 404");

    const textCall = fakeResponse();
    await getMessageMedia(
      { params: { id: conversationId, messageId: textMessage.rows[0].id } } as unknown as Request,
      textCall.response
    );
    assert.strictEqual(textCall.status(), 422, "mensagem de texto nao deveria ter midia para baixar");

    const missingIdCall = fakeResponse();
    await getMessageMedia(
      { params: { id: conversationId, messageId: imageWithoutIdMessage.rows[0].id } } as unknown as Request,
      missingIdCall.response
    );
    assert.strictEqual(missingIdCall.status(), 404, "imagem sem media id no metadata deveria retornar 404");

    const documentCall = fakeResponse();
    await getMessageMedia(
      { params: { id: conversationId, messageId: documentMessage.rows[0].id } } as unknown as Request,
      documentCall.response
    );
    // Sem credenciais reais da Graph API validas neste ambiente, o download falha
    // (401/erro de token) e o endpoint deve responder 502 de forma controlada,
    // nunca deixar a exception escapar sem resposta.
    assert.strictEqual(documentCall.status(), 502, "falha de download da Graph API deveria responder 502 controlado");

    console.log("Message media contract tests passed.");
  } finally {
    await query(`DELETE FROM messages WHERE conversation_id = $1`, [conversationId]);
    await query(`DELETE FROM conversations WHERE id = $1`, [conversationId]);
  }
}

void run()
  .catch((error) => {
    console.error("Message media test failed:", error);
    process.exit(1);
  })
  .finally(() => {
    void pool.end();
  });
