import assert from "assert";
import axios from "axios";
import {
  sendWhatsAppApprovedUtilityTemplateWithRetry,
  uploadWhatsAppPdfWithRetry
} from "../src/services/whatsappService";

async function run(): Promise<void> {
  process.env.DATABASE_URL ||= "postgres://postgres:postgres@127.0.0.1:5432/fortcordis_stage";
  const { parseDocumentTemplateRequest, validatePdfDocument, sendApprovedDocumentTemplate } = await import(
    "../src/controllers/documentTemplateAutomationController"
  );

  const pdf = Buffer.from("%PDF-1.4\n% FortCordis receipt test\n", "utf8");
  const file = {
    fieldname: "document",
    originalname: "recibo_os_123.pdf",
    encoding: "7bit",
    mimetype: "application/pdf",
    size: pdf.length,
    buffer: pdf
  } as Express.Multer.File;

  assert.strictEqual(validatePdfDocument(file), pdf);
  assert.throws(
    () => validatePdfDocument({ ...file, mimetype: "text/plain" }),
    /valid application\/pdf/
  );
  const oversizedPdf = Buffer.alloc(8 * 1024 * 1024 + 1);
  oversizedPdf.write("%PDF");
  assert.throws(
    () => validatePdfDocument({ ...file, size: oversizedPdf.length, buffer: oversizedPdf }),
    /exceeds 8 MiB/
  );
  const parsed = parseDocumentTemplateRequest(
    {
      template_key: "receiptPdf",
      subject_type: "ordem_servico",
      subject_ids: "[123]",
      destination: "558588281436",
      idempotency_key: "receipt-pdf-idempotency-123",
      parameters: JSON.stringify([
        "Animal Care",
        "123",
        "Ecocardiograma",
        "15/08/2026",
        "Maria",
        "Gamora",
        "R$ 350,00"
      ]),
      filename: "recibo_os_123.pdf"
    },
    file
  );
  assert.deepStrictEqual(parsed.subject_ids, [123]);
  assert.strictEqual(parsed.document_sha256.length, 64);
  const reportParsed = parseDocumentTemplateRequest(
    {
      template_key: "homeReportPdf",
      subject_type: "laudo",
      subject_ids: "[7]",
      destination: "558588281436",
      idempotency_key: "home-report-pdf-7",
      parameters: JSON.stringify(["Tutor teste", "Pet teste"]),
      filename: "laudo_7.pdf"
    },
    { ...file, originalname: "laudo_7.pdf" }
  );
  assert.deepStrictEqual(reportParsed.subject_ids, [7]);
  assert.throws(() => parseDocumentTemplateRequest({
    template_key: "homeReportPdf", subject_type: "ordem_servico", subject_ids: "[7]",
    destination: "558588281436", idempotency_key: "home-report-invalid",
    parameters: JSON.stringify(["Tutor teste", "Pet teste"]), filename: "laudo_7.pdf"
  }, file), /requires subject_type 'laudo'/);
  let pendingStatus = 0;
  let pendingBody: Record<string, unknown> = {};
  await sendApprovedDocumentTemplate({
    body: {
      template_key: "homeReportPdf", subject_type: "laudo", subject_ids: "[7]",
      destination: "558588281436", idempotency_key: "home-report-pending-7",
      parameters: JSON.stringify(["Tutor teste", "Pet teste"]), filename: "laudo_7.pdf"
    }, file: { ...file, originalname: "laudo_7.pdf" }
  } as any, {
    status(code: number) { pendingStatus = code; return this; },
    json(value: Record<string, unknown>) { pendingBody = value; return this; }
  } as any);
  assert.strictEqual(pendingStatus, 503);
  assert.strictEqual(pendingBody.code, "TEMPLATE_PENDING_APPROVAL");

  const originalPost = axios.post;
  const requests: Array<{ url: string; payload: any }> = [];
  try {
    (axios.post as unknown as (url: string, payload: unknown) => Promise<unknown>) = async (url, payload) => {
      requests.push({ url, payload });
      if (url.endsWith("/media")) {
        return { data: { id: "media.receipt.123" } };
      }
      return {
        data: {
          messaging_product: "whatsapp",
          messages: [{ id: "wamid.receipt.pdf.123" }]
        }
      };
    };

    const upload = await uploadWhatsAppPdfWithRetry({
      phoneNumberId: "1279142515283484",
      accessToken: "secret-token",
      filename: "recibo_os_123.pdf",
      content: pdf
    });
    assert.strictEqual(upload.id, "media.receipt.123");
    assert.ok(requests[0].payload instanceof FormData);
    assert.strictEqual(requests[0].payload.get("messaging_product"), "whatsapp");

    await sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId: "1279142515283484",
      accessToken: "secret-token",
      to: "558588281436",
      templateKey: "receiptPdf",
      bodyParameters: parsed.parameters,
      quickReplyPayloads: ["finance-contact-token"],
      documentHeader: {
        mediaId: upload.id,
        filename: parsed.filename
      }
    });

    const messagePayload = requests[1].payload;
    assert.strictEqual(messagePayload.template.name, "recibo_pagamento_pdf");
    assert.deepStrictEqual(messagePayload.template.components[0], {
      type: "header",
      parameters: [
        {
          type: "document",
          document: { id: "media.receipt.123", filename: "recibo_os_123.pdf" }
        }
      ]
    });
    assert.strictEqual(messagePayload.template.components[1].parameters.length, 7);
    assert.strictEqual(messagePayload.template.components[2].type, "button");

    await sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId: "1279142515283484",
      accessToken: "secret-token",
      to: "558588281436",
      templateKey: "homeReportPdf",
      bodyParameters: reportParsed.parameters,
      quickReplyPayloads: [],
      documentHeader: { mediaId: upload.id, filename: reportParsed.filename }
    });
    assert.strictEqual(requests[2].payload.template.name, "laudo_domiciliar_pdf_tutor");
    assert.strictEqual(requests[2].payload.template.components[0].parameters[0].type, "document");

    await assert.rejects(
      () =>
        sendWhatsAppApprovedUtilityTemplateWithRetry({
          phoneNumberId: "1279142515283484",
          accessToken: "secret-token",
          to: "558588281436",
          templateKey: "receiptPdf",
          bodyParameters: parsed.parameters,
          quickReplyPayloads: ["finance-contact-token"]
        }),
      /requires a document header/
    );
    assert.strictEqual(requests.length, 3);
  } finally {
    axios.post = originalPost;
  }

  console.log("Document template validation, upload and payload tests passed.");
}

void run().catch((error) => {
  console.error("Document template test failed:", error);
  process.exit(1);
});
