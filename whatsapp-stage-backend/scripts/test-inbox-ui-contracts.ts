import assert from "assert";
import { Request, Response } from "express";
import {
  isConversationStatus,
  resolveTextMessageMetadata
} from "../src/controllers/conversationsController";
import { listApprovedTemplateCatalog } from "../src/controllers/templateCatalogController";
import { sendApprovedUtilityTemplate } from "../src/controllers/templateAutomationController";
import { APPROVED_UTILITY_TEMPLATES } from "../src/templates/approvedTemplates";
import { pool } from "../src/services/dbService";

async function run(): Promise<void> {
  assert.strictEqual(isConversationStatus("open"), true);
  assert.strictEqual(isConversationStatus("pending"), true);
  assert.strictEqual(isConversationStatus("closed"), true);
  assert.strictEqual(isConversationStatus("resolved"), false);
  assert.strictEqual(isConversationStatus(null), false);

  assert.deepStrictEqual(
    resolveTextMessageMetadata({ body: {} } as Request),
    { source: "agent_api" },
    "ordinary agent messages keep the legacy metadata"
  );
  const botRequest = {
    body: {
      metadata: {
        origem: "bot",
        source: "bot_suggest_reviewed",
        resposta_id: "21",
        idempotency_key: "whatsapp-bot-resposta-21"
      }
    },
    authUser: { authSource: "internal_token" }
  } as unknown as Request;
  assert.deepStrictEqual(resolveTextMessageMetadata(botRequest), botRequest.body.metadata);
  assert.strictEqual(
    resolveTextMessageMetadata({ ...botRequest, authUser: { authSource: "core_api" } } as unknown as Request),
    null,
    "browser-authenticated callers cannot forge the bot badge"
  );
  assert.strictEqual(
    resolveTextMessageMetadata({
      ...botRequest,
      body: { metadata: { ...botRequest.body.metadata, idempotency_key: "arbitrary" } }
    } as unknown as Request),
    null,
    "bot idempotency keys are scoped to response ids"
  );
  assert.strictEqual(
    resolveTextMessageMetadata({
      ...botRequest,
      body: {
        metadata: {
          ...botRequest.body.metadata,
          idempotency_key: "whatsapp-bot-resposta-22"
        }
      }
    } as unknown as Request),
    null,
    "the idempotency key must belong to the declared bot response"
  );

  let responsePayload: unknown = null;
  const response = {
    json(payload: unknown) {
      responsePayload = payload;
      return this;
    }
  } as unknown as Response;

  await listApprovedTemplateCatalog({} as Request, response);

  const catalog = responsePayload as {
    data: Array<{
      key: string;
      variable_labels: string[];
      body_parameter_count: number;
      requires_document: boolean;
      can_copy_as_free_text: boolean;
      meta_approval_live: null;
    }>;
    source: string;
    meta_approval_live: null;
  };

  assert.strictEqual(catalog.source, "configured_catalog");
  assert.strictEqual(catalog.meta_approval_live, null);
  assert.strictEqual(catalog.data.length, 13);
  assert.ok(catalog.data.every((template) => template.variable_labels.length === template.body_parameter_count));
  assert.ok(catalog.data.every((template) => template.meta_approval_live === null));
  const serviceReminder = catalog.data.find((template) => template.key === "appointmentReminderService");
  assert.ok(serviceReminder);
  assert.strictEqual(serviceReminder.body_parameter_count, 5);
  assert.deepStrictEqual(serviceReminder.variable_labels,
    ["Clínica ou destinatário", "Pet", "Data", "Horário", "Serviço agendado"]);
  const existingReminder = catalog.data.find((template) => template.key === "appointmentReminder");
  assert.strictEqual(existingReminder?.body_parameter_count, 4, "the legacy reminder remains separately selectable");

  const serviceDefinition = APPROVED_UTILITY_TEMPLATES.appointmentReminderService as unknown as { metaId: string };
  const originalMetaId = serviceDefinition.metaId;
  const originalBusinessAccountId = process.env.WHATSAPP_BUSINESS_ACCOUNT_ID;
  const originalConnect = pool.connect;
  let databaseConnections = 0;
  let sendStatus = 200;
  let sendPayload: unknown;
  try {
    pool.connect = (async () => { databaseConnections++; throw new Error("pending approval must not connect to the database"); }) as typeof pool.connect;
    for (const approval of [
      { metaId: "PENDING_META_APPROVAL", account: "1369494994627980" },
      { metaId: originalMetaId, account: undefined },
      { metaId: originalMetaId, account: "" },
      { metaId: originalMetaId, account: "invalid" },
      { metaId: originalMetaId, account: "4413513738886247" },
      { metaId: originalMetaId, account: "1369494994627980 " }
    ]) {
      serviceDefinition.metaId = approval.metaId;
      if (approval.account === undefined) delete process.env.WHATSAPP_BUSINESS_ACCOUNT_ID;
      else process.env.WHATSAPP_BUSINESS_ACCOUNT_ID = approval.account;
      sendStatus = 200;
      sendPayload = undefined;
      await sendApprovedUtilityTemplate({ body: {
        template_key: "appointmentReminderService", subject_type: "agendamento", subject_id: 42,
        destination: "558500000000", idempotency_key: "synthetic-service-reminder-approval-gate",
        parameters: ["Clínica teste", "Pet teste", "15/10/2026", "14:00", "Eletrocardiograma"]
      } } as Request, {
        status(value: number) { sendStatus = value; return this; },
        json(value: unknown) { sendPayload = value; return this; }
      } as unknown as Response);
      assert.strictEqual(sendStatus, 409);
      assert.deepStrictEqual(sendPayload, {
        code: "WHATSAPP_TEMPLATE_APPROVAL_PENDING",
        error: "O lembrete com serviço aguarda aprovação da Meta."
      });
    }
    assert.strictEqual(databaseConnections, 0, "approval is checked before reserving or writing a delivery");
  } finally {
    serviceDefinition.metaId = originalMetaId;
    if (originalBusinessAccountId === undefined) delete process.env.WHATSAPP_BUSINESS_ACCOUNT_ID;
    else process.env.WHATSAPP_BUSINESS_ACCOUNT_ID = originalBusinessAccountId;
    pool.connect = originalConnect;
  }

  const receiptPdf = catalog.data.find((template) => template.key === "receiptPdf");
  assert.ok(receiptPdf);
  assert.strictEqual(receiptPdf?.requires_document, true);
  assert.strictEqual(receiptPdf?.can_copy_as_free_text, false);

  const report = catalog.data.find((template) => template.key === "portalReportAvailable");
  assert.ok(report);
  assert.strictEqual(report?.requires_document, false);
  assert.strictEqual(report?.can_copy_as_free_text, true);

  console.log("Inbox status and configured template catalog contracts passed.");
}

void run().catch((error) => {
  console.error("Inbox UI contract test failed:", error);
  process.exit(1);
});
