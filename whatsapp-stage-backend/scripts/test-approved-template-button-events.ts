import "dotenv/config";
import assert from "assert";
import axios from "axios";
import { pool, query, withTransaction } from "../src/services/dbService";
import { handleApprovedTemplateButtonReply } from "../src/services/approvedTemplateButtonService";
import { WebhookMessage } from "../src/types/whatsapp";

async function insertApprovedTemplateMessage(params: {
  destination: string;
  buttonBindings: Array<{ action: string; index: number; payload: string }>;
  idempotencyKey: string;
  waMessageId: string;
}): Promise<string> {
  const result = await query<{ id: string }>(
    `
      INSERT INTO approved_template_messages (
        template_key, template_name, language_code, subject_type, subject_id, subject_ids,
        destination, idempotency_key, request_hash, body_parameters, button_bindings,
        rendered_body, processing_status, wa_message_id, created_at, updated_at, sent_at
      ) VALUES (
        'appointmentMissingData', 'dados_pendentes_agendamento', 'pt_BR', 'agendamento', 4242, '[4242]'::jsonb,
        $1, $2, 'hash', '[]'::jsonb, $3::jsonb,
        'corpo renderizado', 'sent', $4, now(), now(), now()
      )
      RETURNING id
    `,
    [params.destination, params.idempotencyKey, JSON.stringify(params.buttonBindings), params.waMessageId]
  );
  return result.rows[0].id;
}

function buildButtonMessage(params: {
  id: string;
  from: string;
  payload: string;
}): WebhookMessage {
  return {
    id: params.id,
    from: params.from,
    type: "button",
    button: { text: "Enviar dados", payload: params.payload }
  } as unknown as WebhookMessage;
}

async function run(): Promise<void> {
  const runId = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const destination = `55850009${runId}`.slice(0, 15);
  const enviarDadosPayload = `fc_test_enviar_dados_${runId}`;
  const falarEquipePayload = `fc_test_falar_equipe_${runId}`;

  const capturedRequests: Array<{ url: string; payload: unknown }> = [];
  const originalPost = axios.post;
  (axios.post as unknown as (url: string, payload: unknown, config?: unknown) => Promise<unknown>) = async (
    url,
    payload
  ) => {
    capturedRequests.push({ url, payload });
    if (url.includes("/link-formalizacao")) {
      return { data: { link: "https://app.fortcordis.example/agenda/formalizar/test-token", expires_at: null } };
    }
    if (url.includes("/integracoes/whatsapp/agenda/respostas")) {
      return { data: { result: "falar_equipe_solicitado", idempotent: false } };
    }
    if (url.includes("graph.facebook.com")) {
      return { data: { messaging_product: "whatsapp", messages: [{ id: `wamid.reply.${capturedRequests.length}` }] } };
    }
    throw new Error(`Unexpected axios.post call in test: ${url}`);
  };

  let conversationId: string | null = null;
  let templateMessageId1: string | null = null;
  let templateMessageId2: string | null = null;

  try {
    const conversation = await query<{ id: string }>(
      `
        INSERT INTO conversations (wa_phone_number, wa_psid, status, last_activity_at, created_at, updated_at)
        VALUES ($1, $1, 'open', now(), now(), now())
        RETURNING id
      `,
      [destination]
    );
    conversationId = conversation.rows[0].id;

    templateMessageId1 = await insertApprovedTemplateMessage({
      destination,
      idempotencyKey: `button-test-enviar-dados-${runId}`,
      waMessageId: `wamid.outbound.button-test-1-${runId}`,
      buttonBindings: [
        { action: "enviar_dados", index: 0, payload: enviarDadosPayload },
        { action: "falar_equipe", index: 1, payload: `unused_${runId}` }
      ]
    });

    await withTransaction(async (client) => {
      await handleApprovedTemplateButtonReply(
        client,
        buildButtonMessage({ id: `wamid.click.enviar-dados.${runId}`, from: destination, payload: enviarDadosPayload })
      );
    });

    const enviarDadosEvent = await query<{ processing_status: string; response_payload: unknown }>(
      `SELECT processing_status, response_payload FROM approved_template_button_events WHERE provider_message_id = $1`,
      [`wamid.click.enviar-dados.${runId}`]
    );
    assert.strictEqual(enviarDadosEvent.rows[0]?.processing_status, "processed");

    const linkCall = capturedRequests.find((req) => req.url.includes("/link-formalizacao"));
    assert.ok(linkCall, "expected a call to the link-formalizacao endpoint");

    const outboundText = await query<{ body: string; status: string }>(
      `SELECT body, status FROM messages WHERE conversation_id = $1 AND from_me = true ORDER BY created_at DESC LIMIT 1`,
      [conversationId]
    );
    assert.ok(
      outboundText.rows[0]?.body.includes("https://app.fortcordis.example/agenda/formalizar/test-token"),
      `expected outbound free-text message to include the formalizacao link, got: ${outboundText.rows[0]?.body}`
    );
    assert.strictEqual(outboundText.rows[0]?.status, "sent");

    // Reentrega do mesmo evento (retry do webhook da Meta) nao deve gerar um segundo link/mensagem.
    await withTransaction(async (client) => {
      await handleApprovedTemplateButtonReply(
        client,
        buildButtonMessage({ id: `wamid.click.enviar-dados.${runId}`, from: destination, payload: enviarDadosPayload })
      );
    });
    const linkCallsAfterRetry = capturedRequests.filter((req) => req.url.includes("/link-formalizacao"));
    assert.strictEqual(linkCallsAfterRetry.length, 1, "retry of the same provider_message_id must not re-trigger the link call");

    templateMessageId2 = await insertApprovedTemplateMessage({
      destination,
      idempotencyKey: `button-test-falar-equipe-${runId}`,
      waMessageId: `wamid.outbound.button-test-2-${runId}`,
      buttonBindings: [{ action: "falar_equipe", index: 0, payload: falarEquipePayload }]
    });

    await withTransaction(async (client) => {
      await handleApprovedTemplateButtonReply(
        client,
        buildButtonMessage({ id: `wamid.click.falar-equipe.${runId}`, from: destination, payload: falarEquipePayload })
      );
    });

    const falarEquipeEvent = await query<{ processing_status: string }>(
      `SELECT processing_status FROM approved_template_button_events WHERE provider_message_id = $1`,
      [`wamid.click.falar-equipe.${runId}`]
    );
    assert.strictEqual(falarEquipeEvent.rows[0]?.processing_status, "processed");
    const respostasCall = capturedRequests.find((req) => req.url.includes("/integracoes/whatsapp/agenda/respostas"));
    assert.ok(respostasCall, "expected a call to the shared button-response endpoint for falar_equipe");
    assert.strictEqual((respostasCall!.payload as { action: string }).action, "falar_equipe");

    // Sender diferente do destino cadastrado deve ser rejeitado sem disparar nenhuma acao.
    const mismatchPayload = `fc_test_mismatch_${runId}`;
    const templateMessageId3 = await insertApprovedTemplateMessage({
      destination,
      idempotencyKey: `button-test-mismatch-${runId}`,
      waMessageId: `wamid.outbound.button-test-3-${runId}`,
      buttonBindings: [{ action: "enviar_dados", index: 0, payload: mismatchPayload }]
    });
    const callsBeforeMismatch = capturedRequests.length;
    await withTransaction(async (client) => {
      await handleApprovedTemplateButtonReply(
        client,
        buildButtonMessage({ id: `wamid.click.mismatch.${runId}`, from: "5511900000000", payload: mismatchPayload })
      );
    });
    assert.strictEqual(capturedRequests.length, callsBeforeMismatch, "mismatched sender must not trigger any outbound call");
    const mismatchEvent = await query<{ processing_status: string }>(
      `SELECT processing_status FROM approved_template_button_events WHERE provider_message_id = $1`,
      [`wamid.click.mismatch.${runId}`]
    );
    assert.strictEqual(mismatchEvent.rows[0]?.processing_status, "rejected");
    await query(`DELETE FROM approved_template_messages WHERE id = $1`, [templateMessageId3]);

    console.log("Approved template button reply tests passed.");
  } finally {
    axios.post = originalPost;
    if (conversationId) {
      await query(`DELETE FROM messages WHERE conversation_id = $1`, [conversationId]);
      await query(`DELETE FROM conversations WHERE id = $1`, [conversationId]);
    }
    for (const id of [templateMessageId1, templateMessageId2]) {
      if (id) {
        await query(`DELETE FROM approved_template_messages WHERE id = $1`, [id]);
      }
    }
  }
}

void run()
  .catch((error) => {
    console.error("Approved template button reply test failed:", error);
    process.exit(1);
  })
  .finally(() => {
    void pool.end();
  });
