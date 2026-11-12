import { createHash, randomBytes } from "crypto";
import { Request, Response } from "express";
import { query, queryWithClient, withTransaction } from "../services/dbService";
import {
  sendWhatsAppApprovedUtilityTemplateWithRetry,
  uploadWhatsAppPdfWithRetry,
  WhatsAppGraphApiError
} from "../services/whatsappService";
import {
  APPROVED_UTILITY_TEMPLATES,
  getTemplateBodyParameterCount,
  renderApprovedTemplateBody,
  templateRequiresDocumentHeader
} from "../templates/approvedTemplates";
import { logger } from "../utils/logger";
import { canonicalWhatsAppIdentity } from "../utils/phoneNumber";

type DocumentTemplateKey = "receiptPdf" | "receiptPdfBulk" | "homeReportPdf";

interface DocumentTemplateRequest {
  template_key: DocumentTemplateKey;
  subject_type: "ordem_servico" | "laudo";
  subject_id: number;
  subject_ids: number[];
  destination: string;
  idempotency_key: string;
  parameters: string[];
  filename: string;
  document: Buffer;
  document_sha256: string;
}

interface DocumentTemplateRow {
  id: string;
  request_hash: string;
  wa_media_id: string | null;
  wa_message_id: string | null;
  processing_status: string;
  button_bindings: Array<{ action: string; payload: string; index: number }> | string;
}

const MAX_PDF_BYTES = 8 * 1024 * 1024;

function cleanText(value: unknown, field: string, maxLength: number): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${field} is required`);
  }
  const normalized = value.trim();
  if (normalized.length > maxLength) {
    throw new Error(`${field} exceeds ${maxLength} characters`);
  }
  return normalized;
}

function normalizeDestination(value: unknown): string {
  const digits = String(value ?? "").replace(/\D+/g, "");
  if (digits.length < 12 || digits.length > 15) {
    throw new Error("destination must use international digits");
  }
  return digits;
}

function parseJsonArray(value: unknown, field: string): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value !== "string") {
    throw new Error(`${field} must be a JSON array`);
  }
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      throw new Error();
    }
    return parsed;
  } catch {
    throw new Error(`${field} must be a JSON array`);
  }
}

function sanitizePdfFilename(value: unknown): string {
  const raw = cleanText(value, "filename", 160);
  const basename = raw.replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^\.+/, "");
  if (!basename || !basename.toLowerCase().endsWith(".pdf")) {
    throw new Error("filename must be a safe .pdf name");
  }
  return basename;
}

export function validatePdfDocument(file: Express.Multer.File | undefined): Buffer {
  if (!file || !Buffer.isBuffer(file.buffer) || file.buffer.length === 0) {
    throw new Error("document PDF is required");
  }
  if (file.buffer.length > MAX_PDF_BYTES) {
    throw new Error("document PDF exceeds 8 MiB");
  }
  if (file.mimetype !== "application/pdf" || file.buffer.subarray(0, 4).toString("ascii") !== "%PDF") {
    throw new Error("document must be a valid application/pdf file");
  }
  return file.buffer;
}

export function parseDocumentTemplateRequest(
  body: Record<string, unknown>,
  file: Express.Multer.File | undefined
): DocumentTemplateRequest {
  const templateKey = cleanText(body.template_key, "template_key", 80) as DocumentTemplateKey;
  if (templateKey !== "receiptPdf" && templateKey !== "receiptPdfBulk" && templateKey !== "homeReportPdf") {
    throw new Error("template_key is not an approved document template");
  }
  if (!templateRequiresDocumentHeader(templateKey)) {
    throw new Error(`template '${templateKey}' does not accept a document header`);
  }
  const subjectType = templateKey === "homeReportPdf" ? "laudo" : "ordem_servico";
  if (cleanText(body.subject_type, "subject_type", 40) !== subjectType) {
    throw new Error(`template '${templateKey}' requires subject_type '${subjectType}'`);
  }

  const subjectIds = Array.from(
    new Set(parseJsonArray(body.subject_ids, "subject_ids").map((value) => Number(value)))
  );
  const expectedMinimum = templateKey === "receiptPdfBulk" ? 2 : 1;
  const expectedMaximum = templateKey === "receiptPdfBulk" ? 20 : 1;
  if (
    subjectIds.length < expectedMinimum ||
    subjectIds.length > expectedMaximum ||
    subjectIds.some((value) => !Number.isSafeInteger(value) || value <= 0)
  ) {
    throw new Error(
      `template '${templateKey}' requires between ${expectedMinimum} and ${expectedMaximum} positive subject_ids`
    );
  }

  const parameters = parseJsonArray(body.parameters, "parameters").map((value, index) =>
    cleanText(value, `parameters[${index}]`, 300)
  );
  const expectedParameters = getTemplateBodyParameterCount(templateKey);
  if (parameters.length !== expectedParameters) {
    throw new Error(`template '${templateKey}' expects ${expectedParameters} parameters, received ${parameters.length}`);
  }
  if (renderApprovedTemplateBody(templateKey, parameters).length > 1024) {
    throw new Error(`template '${templateKey}' rendered body exceeds 1024 characters`);
  }

  const document = validatePdfDocument(file);
  const filename = sanitizePdfFilename(body.filename || file?.originalname);
  return {
    template_key: templateKey,
    subject_type: subjectType,
    subject_id: subjectIds[0],
    subject_ids: subjectIds,
    destination: normalizeDestination(body.destination),
    idempotency_key: cleanText(body.idempotency_key, "idempotency_key", 128),
    parameters,
    filename,
    document,
    document_sha256: createHash("sha256").update(document).digest("hex")
  };
}

function computeRequestHash(payload: DocumentTemplateRequest): string {
  return createHash("sha256")
    .update(
      JSON.stringify({
        template_key: payload.template_key,
        subject_type: payload.subject_type,
        subject_id: payload.subject_id,
        subject_ids: payload.subject_ids,
        destination: payload.destination,
        idempotency_key: payload.idempotency_key,
        parameters: payload.parameters,
        filename: payload.filename,
        document_sha256: payload.document_sha256
      })
    )
    .digest("hex");
}

function buildButtonBindings(templateKey: DocumentTemplateKey) {
  return APPROVED_UTILITY_TEMPLATES[templateKey].buttonActions.map((action, index) => ({
    action,
    index,
    payload: `fc_template_${randomBytes(24).toString("base64url")}`
  }));
}

function parseBindings(value: DocumentTemplateRow["button_bindings"]) {
  if (Array.isArray(value)) {
    return value;
  }
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function reserveDelivery(payload: DocumentTemplateRequest) {
  const requestHash = computeRequestHash(payload);
  return withTransaction(async (client) => {
    const existing = await queryWithClient<DocumentTemplateRow>(
      client,
      "SELECT * FROM approved_template_messages WHERE idempotency_key = $1 FOR UPDATE",
      [payload.idempotency_key]
    );
    if (existing.rows[0]) {
      const row = existing.rows[0];
      if (row.request_hash !== requestHash) {
        throw Object.assign(new Error("idempotency_key was already used with different content"), { statusCode: 409 });
      }
      if (row.processing_status === "sent" && row.wa_message_id) {
        return { row, idempotent: true };
      }
      if (row.processing_status === "pending" || row.processing_status === "ambiguous") {
        throw Object.assign(
          new Error("delivery is pending or ambiguous and requires operational review before retry"),
          { statusCode: 409 }
        );
      }
      const retried = await queryWithClient<DocumentTemplateRow>(
        client,
        `UPDATE approved_template_messages
         SET processing_status = 'pending', processing_error = NULL, updated_at = now()
         WHERE id = $1 RETURNING *`,
        [row.id]
      );
      return { row: retried.rows[0], idempotent: false };
    }

    const definition = APPROVED_UTILITY_TEMPLATES[payload.template_key];
    const buttonBindings = buildButtonBindings(payload.template_key);
    const inserted = await queryWithClient<DocumentTemplateRow>(
      client,
      `INSERT INTO approved_template_messages (
         template_key, template_name, language_code, subject_type, subject_id, subject_ids,
         destination, idempotency_key, request_hash, body_parameters, button_bindings, rendered_body,
         document_filename, document_sha256, processing_status, created_at, updated_at
       ) VALUES (
         $1, $2, 'pt_BR', $3, $4, $5::jsonb, $6, $7, $8, $9::jsonb, $10::jsonb, $11,
         $12, $13, 'pending', now(), now()
       ) RETURNING *`,
      [
        payload.template_key,
        definition.name,
        payload.subject_type,
        payload.subject_id,
        JSON.stringify(payload.subject_ids),
        payload.destination,
        payload.idempotency_key,
        requestHash,
        JSON.stringify(payload.parameters),
        JSON.stringify(buttonBindings),
        renderApprovedTemplateBody(payload.template_key, payload.parameters),
        payload.filename,
        payload.document_sha256
      ]
    );
    return { row: inserted.rows[0], idempotent: false };
  });
}

async function persistSentMessage(
  row: DocumentTemplateRow,
  payload: DocumentTemplateRequest,
  waMediaId: string,
  waMessageId: string
): Promise<void> {
  const definition = APPROVED_UTILITY_TEMPLATES[payload.template_key];
  const renderedBody = renderApprovedTemplateBody(payload.template_key, payload.parameters);
  await withTransaction(async (client) => {
    const conversation = await queryWithClient<{ id: string }>(
      client,
      `INSERT INTO conversations (
         wa_phone_number, wa_psid, status, last_activity_at, created_at, updated_at
       ) VALUES ($1, $1, 'open', now(), now(), now())
       ON CONFLICT (wa_phone_number)
       DO UPDATE SET updated_at = now(), last_activity_at = now()
       RETURNING id`,
      [canonicalWhatsAppIdentity(payload.destination)]
    );
    await queryWithClient(
      client,
      `INSERT INTO messages (
         conversation_id, wa_message_id, from_me, body, type, metadata, status, created_at
       ) VALUES ($1, $2, true, $3, 'document', $4::jsonb, 'sent', now())
       ON CONFLICT (wa_message_id) DO NOTHING`,
      [
        conversation.rows[0].id,
        waMessageId,
        renderedBody,
        JSON.stringify({
          source: `template.${payload.subject_type}`,
          template_key: payload.template_key,
          template_name: definition.name,
          subject_type: payload.subject_type,
          subject_id: payload.subject_id,
          subject_ids: payload.subject_ids,
          language_code: "pt_BR",
          document_filename: payload.filename,
          document_sha256: payload.document_sha256,
          wa_media_id: waMediaId
        })
      ]
    );
    await queryWithClient(
      client,
      `UPDATE approved_template_messages
       SET wa_media_id = $2, wa_message_id = $3, processing_status = 'sent', processing_error = NULL,
           sent_at = now(), updated_at = now()
       WHERE id = $1`,
      [row.id, waMediaId, waMessageId]
    );
  });
}

export async function sendApprovedDocumentTemplate(req: Request, res: Response): Promise<void> {
  let payload: DocumentTemplateRequest;
  try {
    payload = parseDocumentTemplateRequest(req.body as Record<string, unknown>, req.file);
  } catch (error) {
    res.status(422).json({ error: error instanceof Error ? error.message : "invalid document request" });
    return;
  }

  if (payload.template_key === "homeReportPdf" &&
      process.env.WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED !== "true") {
    res.status(503).json({ code: "TEMPLATE_PENDING_APPROVAL", error: "O modelo de laudo ao tutor ainda nao esta habilitado para esta conta da Meta." });
    return;
  }

  let reserved: { row: DocumentTemplateRow; idempotent: boolean };
  try {
    reserved = await reserveDelivery(payload);
  } catch (error) {
    const statusCode = Number((error as { statusCode?: number }).statusCode) || 500;
    res.status(statusCode).json({ error: error instanceof Error ? error.message : "delivery reservation failed" });
    return;
  }

  if (reserved.idempotent && reserved.row.wa_message_id) {
    res.status(200).json({
      message_id: reserved.row.wa_message_id,
      media_id: reserved.row.wa_media_id,
      idempotent: true
    });
    return;
  }

  const phoneNumberId = String(process.env.PHONE_NUMBER_ID || "").trim();
  const accessToken = String(process.env.WHATSAPP_ACCESS_TOKEN || "").trim();
  let mediaId: string | null = null;
  let providerMessageId: string | null = null;
  try {
    mediaId = (
      await uploadWhatsAppPdfWithRetry({
        phoneNumberId,
        accessToken,
        filename: payload.filename,
        content: payload.document
      })
    ).id;
    await query(
      `UPDATE approved_template_messages SET wa_media_id = $2, updated_at = now() WHERE id = $1`,
      [reserved.row.id, mediaId]
    );

    const provider = await sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId,
      accessToken,
      to: payload.destination,
      templateKey: payload.template_key,
      bodyParameters: payload.parameters,
      quickReplyPayloads: parseBindings(reserved.row.button_bindings).map((binding) => binding.payload),
      documentHeader: { mediaId, filename: payload.filename }
    });
    const messageId = provider.messages?.[0]?.id;
    if (!messageId) {
      throw new Error("Meta response did not include a message id");
    }
    providerMessageId = messageId;
    await persistSentMessage(reserved.row, payload, mediaId, messageId);
    res.status(201).json({ message_id: messageId, media_id: mediaId, idempotent: false });
  } catch (error) {
    const graphError = error instanceof WhatsAppGraphApiError ? error : null;
    const ambiguous = Boolean(
      providerMessageId || (graphError && (graphError.status === undefined || graphError.status >= 500))
    );
    await query(
      `UPDATE approved_template_messages
       SET processing_status = $2, processing_error = $3,
           wa_media_id = COALESCE(wa_media_id, $4), wa_message_id = COALESCE(wa_message_id, $5), updated_at = now()
       WHERE id = $1 AND processing_status <> 'sent'`,
      [
        reserved.row.id,
        ambiguous ? "ambiguous" : "failed",
        error instanceof Error ? error.message : "unknown provider failure",
        mediaId,
        providerMessageId
      ]
    );
    logger.error("Approved document template delivery failed", {
      templateKey: payload.template_key,
      subjectType: payload.subject_type,
      subjectIds: payload.subject_ids,
      status: graphError?.status,
      code: graphError?.code,
      ambiguous
    });
    res.status(graphError?.status && graphError.status < 500 ? 502 : 503).json({
      error: "WhatsApp provider rejected or did not complete the document template delivery"
    });
  }
}
