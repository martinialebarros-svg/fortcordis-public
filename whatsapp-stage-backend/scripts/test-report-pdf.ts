import assert from "assert";
import { sendReportPdfInCustomerWindow } from "../src/controllers/reportPdfAutomationController";
import * as dbService from "../src/services/dbService";
import * as whatsappService from "../src/services/whatsappService";

function response() {
  let status = 200;
  let body: Record<string, unknown> = {};
  const res = {
    status(code: number) { status = code; return this; },
    json(value: Record<string, unknown>) { body = value; return this; }
  };
  return { res, result: () => ({ status, body }) };
}

async function main() {
  process.env.WHATSAPP_INTERNAL_API_TOKEN = "test-internal-token";
  process.env.PHONE_NUMBER_ID = "test-phone";
  process.env.WHATSAPP_ACCESS_TOKEN = "test-access-token";
  const unauthorized = response();
  await sendReportPdfInCustomerWindow({ header: () => "wrong" } as any, unauthorized.res as any);
  assert.strictEqual(unauthorized.result().status, 403);

  const invalid = response();
  await sendReportPdfInCustomerWindow({
    header: () => "test-internal-token",
    body: { laudo_id: 7, destination: "5585999991234", idempotency_key: "chave-teste-123", filename: "laudo.pdf" },
    file: { mimetype: "application/pdf", buffer: Buffer.from("not a PDF") }
  } as any, invalid.res as any);
  assert.strictEqual(invalid.result().status, 422);

  type Row = { id: string; request_hash: string; status: string; wa_message_id: string | null; wa_media_id: string | null };
  const deliveries = new Map<string, Row>();
  let inbound: Date | null = null;
  let uploadCount = 0;
  let sendCount = 0;
  let failSend = false;
  let uncertainSend = false;
  const db = dbService as any;
  db.query = async (sql: string, params: unknown[]) => {
    if (sql.startsWith("SELECT * FROM report_pdf_messages")) {
      return { rows: deliveries.has(String(params[0])) ? [deliveries.get(String(params[0]))] : [] };
    }
    if (sql.includes("FROM approved_template_messages")) {
      return { rows: [] };
    }
    if (sql.includes("FROM conversations")) {
      return { rows: [{ id: "1", last_inbound_at: inbound }] };
    }
    if (sql.startsWith("UPDATE report_pdf_messages SET status")) {
      const row = [...deliveries.values()].find((item) => item.id === params[0]);
      assert.ok(row);
      row.status = String(params[1]);
      row.wa_media_id = String(params[2] || "") || null;
      row.wa_message_id = String(params[3] || "") || null;
      return { rows: [] };
    }
    throw new Error(`Unexpected query: ${sql}`);
  };
  db.withTransaction = async (callback: (client: any) => Promise<unknown>) => callback({
    query: async (sql: string, params: unknown[]) => {
      if (sql.startsWith("SELECT * FROM report_pdf_messages")) {
        return { rows: deliveries.has(String(params[0])) ? [deliveries.get(String(params[0]))] : [] };
      }
      if (sql.startsWith("INSERT INTO report_pdf_messages")) {
        const row: Row = { id: String(deliveries.size + 1), request_hash: String(params[4]),
          status: "pending", wa_message_id: null, wa_media_id: null };
        deliveries.set(String(params[3]), row);
        return { rows: [row] };
      }
      if (sql.startsWith("UPDATE report_pdf_messages SET status = 'pending'")) {
        const row = [...deliveries.values()].find((item) => item.id === params[0]);
        assert.ok(row);
        row.status = "pending";
        return { rows: [row] };
      }
      if (sql.startsWith("UPDATE report_pdf_messages SET status = 'sent'")) {
        const row = [...deliveries.values()].find((item) => item.id === params[0]);
        assert.ok(row);
        row.status = "sent";
        row.wa_message_id = String(params[1]);
        row.wa_media_id = String(params[2]);
        return { rows: [] };
      }
      if (sql.startsWith("INSERT INTO messages")) return { rows: [] };
      throw new Error(`Unexpected transaction query: ${sql}`);
    }
  });
  const wa = whatsappService as any;
  wa.uploadWhatsAppPdfWithRetry = async () => { uploadCount += 1; return { id: "media-test" }; };
  wa.sendWhatsAppDocumentMessageWithRetry = async () => {
    sendCount += 1;
    if (uncertainSend) throw new whatsappService.WhatsAppGraphApiError({ message: "timeout", isRetryable: true, attempt: 1 });
    if (failSend) throw new whatsappService.WhatsAppGraphApiError({ message: "rejected", status: 400, isRetryable: false, attempt: 1 });
    return { messages: [{ id: "wamid.test" }] };
  };
  const request = (key: string) => ({
    header: () => "test-internal-token",
    body: { laudo_id: 7, destination: "5585999991234", idempotency_key: key, filename: "laudo.pdf" },
    file: { mimetype: "application/pdf", buffer: Buffer.from("%PDF-test") }
  } as any);
  const call = async (key: string) => {
    const output = response();
    await sendReportPdfInCustomerWindow(request(key), output.res as any);
    return output.result();
  };

  inbound = new Date(Date.now() - 25 * 60 * 60 * 1000);
  assert.strictEqual((await call("closed-window" )).status, 409);
  assert.strictEqual(uploadCount, 0);
  inbound = new Date();
  assert.strictEqual((await call("successful-send")).status, 201);
  assert.strictEqual((await call("successful-send")).body.idempotent, true);
  assert.strictEqual(sendCount, 1);

  failSend = true;
  assert.strictEqual((await call("definite-failure")).status, 502);
  assert.strictEqual(deliveries.get("definite-failure")?.status, "failed");
  failSend = false;
  assert.strictEqual((await call("definite-failure")).status, 201);

  uncertainSend = true;
  assert.strictEqual((await call("uncertain-send")).status, 502);
  assert.strictEqual(deliveries.get("uncertain-send")?.status, "ambiguous");
  const sendsBeforeRetry = sendCount;
  assert.strictEqual((await call("uncertain-send")).status, 409);
  assert.strictEqual(sendCount, sendsBeforeRetry);
  console.log("Report PDF window, authorization, idempotency and failure tests passed.");
}

void main();
