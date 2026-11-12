import assert from "assert";
import axios, { AxiosError } from "axios";
import { Request, Response } from "express";
import {
  decodeMultipartFilename,
  sanitizeAttachmentFilename,
  sendConversationMessage
} from "../src/controllers/conversationsController";
import {
  sendWhatsAppDocumentMessageWithRetry,
  uploadWhatsAppDocumentWithRetry,
  uploadWhatsAppPdfWithRetry
} from "../src/services/whatsappService";

function createAxiosError(params: { message: string; status?: number }): AxiosError {
  const error = new Error(params.message) as AxiosError;
  error.name = "AxiosError";
  (error as { isAxiosError?: boolean }).isAxiosError = true;
  error.response = {
    status: params.status ?? 500,
    statusText: "Error",
    headers: {},
    config: {} as never,
    data: { error: { message: params.message } }
  };
  return error;
}

function fakeResponse(): { response: Response; status(): number; payload(): unknown } {
  let statusCode = 200;
  let captured: unknown = null;
  const response = {
    status(code: number) {
      statusCode = code;
      return this;
    },
    json(payload: unknown) {
      captured = payload;
      return this;
    }
  } as unknown as Response;
  return { response, status: () => statusCode, payload: () => captured };
}

async function run(): Promise<void> {
  const originalPost = axios.post;

  try {
    // uploadWhatsAppDocumentWithRetry: sends the actual file mime type (not hardcoded
    // to application/pdf like the approved-template PDF uploader) and returns the media id.
    (axios.post as unknown as (url: string, payload: unknown, config: unknown) => Promise<unknown>) = async (
      _url,
      _payload,
      config: any
    ) => {
      assert.strictEqual(config.headers.Authorization, "Bearer token-123");
      return { data: { id: "media-doc-1" } };
    };
    const uploaded = await uploadWhatsAppDocumentWithRetry({
      phoneNumberId: "123",
      accessToken: "token-123",
      filename: "exame.docx",
      content: Buffer.from("conteudo qualquer"),
      mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    });
    assert.strictEqual(uploaded.id, "media-doc-1");

    await assert.rejects(
      () =>
        uploadWhatsAppDocumentWithRetry({
          phoneNumberId: "123",
          accessToken: "token-123",
          filename: "vazio.txt",
          content: Buffer.alloc(0),
          mimeType: "text/plain"
        }),
      /must not be empty/,
      "empty attachment content should be rejected before any network call"
    );

    // Regression guard: the PDF uploader used by the approved-document-template flow
    // must keep validating the %PDF magic bytes after being refactored to share the
    // generic upload-with-retry helper.
    await assert.rejects(
      () =>
        uploadWhatsAppPdfWithRetry({
          phoneNumberId: "123",
          accessToken: "token-123",
          filename: "fake.pdf",
          content: Buffer.from("not a pdf")
        }),
      /valid PDF/
    );
    (axios.post as unknown as (url: string, payload: unknown, config: unknown) => Promise<unknown>) = async () => ({
      data: { id: "media-pdf-1" }
    });
    const uploadedPdf = await uploadWhatsAppPdfWithRetry({
      phoneNumberId: "123",
      accessToken: "token-123",
      filename: "recibo.pdf",
      content: Buffer.from("%PDF-1.4 conteudo")
    });
    assert.strictEqual(uploadedPdf.id, "media-pdf-1");

    // sendWhatsAppDocumentMessageWithRetry: payload shape sent to the Graph API,
    // with and without an optional caption.
    let lastPayload: any = null;
    (axios.post as unknown as (url: string, payload: unknown, config: unknown) => Promise<unknown>) = async (
      _url,
      payload
    ) => {
      lastPayload = payload;
      return { data: { messaging_product: "whatsapp", messages: [{ id: "wamid.doc.1" }] } };
    };
    const sent = await sendWhatsAppDocumentMessageWithRetry({
      phoneNumberId: "123",
      accessToken: "token-123",
      to: "5511999999999",
      mediaId: "media-doc-1",
      filename: "exame.docx"
    });
    assert.strictEqual(sent.messages?.[0]?.id, "wamid.doc.1");
    assert.deepStrictEqual(lastPayload, {
      messaging_product: "whatsapp",
      recipient_type: "individual",
      to: "5511999999999",
      type: "document",
      document: { id: "media-doc-1", filename: "exame.docx" }
    });

    await sendWhatsAppDocumentMessageWithRetry({
      phoneNumberId: "123",
      accessToken: "token-123",
      to: "5511999999999",
      mediaId: "media-doc-1",
      filename: "exame.docx",
      caption: "Segue o exame combinado"
    });
    assert.deepStrictEqual(lastPayload.document, {
      id: "media-doc-1",
      filename: "exame.docx",
      caption: "Segue o exame combinado"
    });

    // Retries on a transient failure before succeeding, same as the text-message path.
    let attempts = 0;
    (axios.post as unknown as (url: string, payload: unknown, config: unknown) => Promise<unknown>) = async () => {
      attempts += 1;
      if (attempts === 1) throw createAxiosError({ message: "Rate limited", status: 429 });
      return { data: { messaging_product: "whatsapp", messages: [{ id: "wamid.doc.retry" }] } };
    };
    const retried = await sendWhatsAppDocumentMessageWithRetry({
      phoneNumberId: "123",
      accessToken: "token-123",
      to: "5511999999999",
      mediaId: "media-doc-1",
      filename: "exame.docx"
    });
    assert.strictEqual(attempts, 2, "expected one retry after the 429");
    assert.strictEqual(retried.messages?.[0]?.id, "wamid.doc.retry");

    console.log("WhatsApp document attachment service tests passed.");
  } finally {
    axios.post = originalPost;
  }

  // Express 5 types route params as potentially array-shaped. Reject an
  // unexpected value before any database or Graph API work is attempted.
  const invalidRouteParamCall = fakeResponse();
  await sendConversationMessage(
    { params: { id: ["unexpected"] }, body: { body: "mensagem" } } as unknown as Request,
    invalidRouteParamCall.response
  );
  assert.strictEqual(invalidRouteParamCall.status(), 400, "an invalid conversation id should be rejected with 400");

  // sendConversationMessage: an unsupported attachment mime type is rejected with 422
  // before any database lookup or Graph API call is attempted (no DB/network needed).
  const rejectedCall = fakeResponse();
  await sendConversationMessage(
    {
      params: { id: "does-not-matter" },
      body: {},
      file: {
        originalname: "malware.exe",
        mimetype: "application/x-msdownload",
        buffer: Buffer.from("x"),
        size: 1
      } as Express.Multer.File
    } as unknown as Request,
    rejectedCall.response
  );
  assert.strictEqual(rejectedCall.status(), 422, "unsupported attachment mime type should be rejected with 422");

  // A request with neither a text body nor a file attached is rejected with 400,
  // also before any database lookup.
  const emptyCall = fakeResponse();
  await sendConversationMessage(
    { params: { id: "does-not-matter" }, body: {} } as unknown as Request,
    emptyCall.response
  );
  assert.strictEqual(emptyCall.status(), 400, "a message with no body and no attachment should be rejected with 400");

  // A zero-byte attachment with an otherwise allowed extension/mimetype must be
  // rejected before any pending message is created or upload attempted — no
  // DB/network needed, same as the mimetype rejection above.
  const emptyFileCall = fakeResponse();
  await sendConversationMessage(
    {
      params: { id: "does-not-matter" },
      body: {},
      file: {
        originalname: "vazio.pdf",
        mimetype: "application/pdf",
        buffer: Buffer.alloc(0),
        size: 0
      } as Express.Multer.File
    } as unknown as Request,
    emptyFileCall.response
  );
  assert.strictEqual(emptyFileCall.status(), 422, "a zero-byte attachment should be rejected with 422");

  console.log("Conversation attachment validation tests passed.");

  // Truncating an overlong filename must preserve the extension and stay
  // Unicode-safe (no broken surrogate pairs), not just chop the raw string.
  const longStem = "a".repeat(250);
  const truncated = sanitizeAttachmentFilename(`${longStem}.pdf`);
  assert.ok(truncated.endsWith(".pdf"), "truncated filename must keep its extension");
  assert.ok(truncated.length <= 200, "truncated filename must respect the max length");

  const longStemWithEmoji = `laudo-${"😀".repeat(120)}`;
  const truncatedEmoji = sanitizeAttachmentFilename(`${longStemWithEmoji}.docx`);
  assert.ok(truncatedEmoji.endsWith(".docx"), "truncated filename with emoji must keep its extension");
  assert.strictEqual(
    Array.from(truncatedEmoji).some((char) => char === "�"),
    false,
    "truncation must not split a surrogate pair into an invalid character"
  );

  assert.strictEqual(
    sanitizeAttachmentFilename("recibo.pdf"),
    "recibo.pdf",
    "a filename within the limit must be returned unchanged"
  );

  console.log("Attachment filename truncation tests passed.");

  // Busboy/Multer decode multipart filenames as latin1 by default even though
  // browsers send raw UTF-8 bytes — without the round-trip, accented filenames
  // (very common in Portuguese: "laudo-coração.pdf") arrive mangled.
  assert.strictEqual(
    decodeMultipartFilename("laudo-coraÃ§Ã£o.pdf"),
    "laudo-coração.pdf",
    "UTF-8 filename mis-decoded as latin1 by Multer should be recovered"
  );
  assert.strictEqual(
    decodeMultipartFilename("recibo.pdf"),
    "recibo.pdf",
    "plain ASCII filenames must round-trip unchanged"
  );

  console.log("Multipart filename decoding tests passed.");
}

void run()
  .catch((error) => {
    console.error("Message attachment test failed:", error);
    process.exit(1);
  });
