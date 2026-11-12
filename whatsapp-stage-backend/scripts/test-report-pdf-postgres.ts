import assert from "assert";
import { createHash } from "crypto";
import { sendReportPdfInCustomerWindow } from "../src/controllers/reportPdfAutomationController";
import { sendApprovedDocumentTemplate } from "../src/controllers/documentTemplateAutomationController";
import { pool, query } from "../src/services/dbService";
import * as whatsappService from "../src/services/whatsappService";
import { canonicalWhatsAppIdentity } from "../src/utils/phoneNumber";

async function main() {
  const databaseUrl = String(process.env.DATABASE_URL || "");
  if (process.env.TEST_REPORT_PDF_DB !== "1" || !/^postgres:\/\/[^/]*@?(?:localhost|127\.0\.0\.1):\d+\//.test(databaseUrl)) {
    throw new Error("This integration test requires an explicit temporary local PostgreSQL database.");
  }
  process.env.WHATSAPP_INTERNAL_API_TOKEN = "test-internal-token";
  process.env.PHONE_NUMBER_ID = "test-phone";
  process.env.WHATSAPP_ACCESS_TOKEN = "test-access-token";
  let uploads = 0;
  let sends = 0;
  const wa = whatsappService as any;
  wa.uploadWhatsAppPdfWithRetry = async () => { uploads += 1; return { id: "media-test" }; };
  wa.sendWhatsAppDocumentMessageWithRetry = async () => {
    sends += 1;
    return { messages: [{ id: "wamid.report-pdf-integration" }] };
  };

  const number = "5585999991234";
  const identity = canonicalWhatsAppIdentity(number);
  await query("INSERT INTO conversations (wa_phone_number, last_inbound_at) VALUES ($1, now())", [identity]);
  const call = async (key: string) => {
    let status = 200;
    let body: Record<string, unknown> = {};
    const res = {
      status(code: number) { status = code; return this; },
      json(value: Record<string, unknown>) { body = value; return this; }
    };
    await sendReportPdfInCustomerWindow({
      header: () => "test-internal-token",
      body: { laudo_id: 7, destination: number, idempotency_key: key, filename: "laudo.pdf" },
      file: { mimetype: "application/pdf", buffer: Buffer.from("%PDF-test") }
    } as any, res as any);
    return { status, body };
  };

  assert.strictEqual((await call("integration-send")).status, 201);
  assert.strictEqual((await call("integration-send")).body.idempotent, true);
  assert.strictEqual(uploads, 1);
  assert.strictEqual(sends, 1);
  const rows = await query<{ status: string; wa_message_id: string }>(
    "SELECT status, wa_message_id FROM report_pdf_messages WHERE idempotency_key = $1", ["integration-send"]
  );
  assert.deepStrictEqual(rows.rows.map((row) => [row.status, row.wa_message_id]),
    [["sent", "wamid.report-pdf-integration"]]);
  const messages = await query<{ total: string }>(
    "SELECT count(*)::text AS total FROM messages WHERE wa_message_id = $1", ["wamid.report-pdf-integration"]
  );
  assert.strictEqual(messages.rows[0].total, "1");

  await query("UPDATE conversations SET last_inbound_at = now() - interval '25 hours' WHERE wa_phone_number = $1", [identity]);
  assert.strictEqual((await call("integration-closed")).status, 409);
  assert.strictEqual(sends, 1);
  await query(
    `INSERT INTO approved_template_messages (
       template_key, template_name, language_code, subject_type, subject_id, subject_ids,
       destination, idempotency_key, request_hash, body_parameters, button_bindings, rendered_body,
       document_filename, document_sha256, processing_status, wa_message_id
     ) VALUES ('homeReportPdf', 'laudo_domiciliar_pdf_tutor', 'pt_BR', 'laudo', 7, '[7]'::jsonb,
       $1, 'integration-template-sent', repeat('a', 64), '[]'::jsonb, '[]'::jsonb, 'Teste',
       'laudo.pdf', $2, 'sent', 'wamid.template-sent')`,
    [number, createHash("sha256").update("%PDF-test").digest("hex")]
  );
  const templateRepeat = await call("integration-template-sent");
  assert.strictEqual(templateRepeat.status, 200);
  assert.strictEqual(templateRepeat.body.message_id, "wamid.template-sent");
  assert.strictEqual(sends, 1);
  const originalEnabled = process.env.WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED;
  process.env.WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED = "true";
  wa.sendWhatsAppApprovedUtilityTemplateWithRetry = async () => ({ messages: [{ id: "wamid.home-report-test" }] });
  try {
    const sendTemplate = async () => {
      let status = 200;
      let body: Record<string, unknown> = {};
      await sendApprovedDocumentTemplate({
        body: {
          template_key: "homeReportPdf", subject_type: "laudo", subject_ids: "[8]",
          destination: number, idempotency_key: "integration-home-template-8",
          parameters: JSON.stringify(["Tutor teste", "Pet teste"]), filename: "laudo_8.pdf"
        },
        file: { mimetype: "application/pdf", originalname: "laudo_8.pdf", buffer: Buffer.from("%PDF-test-8") }
      } as any, {
        status(code: number) { status = code; return this; },
        json(value: Record<string, unknown>) { body = value; return this; }
      } as any);
      return { status, body };
    };
    assert.strictEqual((await sendTemplate()).status, 201);
    const repeated = await sendTemplate();
    assert.strictEqual(repeated.status, 200);
    assert.strictEqual(repeated.body.idempotent, true);
    const persisted = await query<{ processing_status: string; subject_type: string }>(
      "SELECT processing_status, subject_type FROM approved_template_messages WHERE idempotency_key = $1",
      ["integration-home-template-8"]
    );
    assert.deepStrictEqual(persisted.rows.map((row) => [row.processing_status, row.subject_type]), [["sent", "laudo"]]);
  } finally {
    if (originalEnabled === undefined) delete process.env.WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED;
    else process.env.WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED = originalEnabled;
  }
  console.log("PostgreSQL report PDF delivery and closed-window integration passed without a Meta call.");
}

void main().finally(() => pool.end());
