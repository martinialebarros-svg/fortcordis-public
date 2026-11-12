import { createHash, randomBytes } from "crypto";
import { Request, Response } from "express";
import { extractDbErrorDetails, query, queryWithClient, withTransaction } from "../services/dbService";
import {
  sendWhatsAppApprovedUtilityTemplateWithRetry,
  WhatsAppGraphApiError
} from "../services/whatsappService";
import {
  APPROVED_UTILITY_TEMPLATES,
  ApprovedUtilityTemplateKey,
  assertTemplateDeliveryApproved,
  getTemplateBodyParameterCount,
  renderApprovedTemplateBody,
  templateRequiresDocumentHeader
} from "../templates/approvedTemplates";
import { logger } from "../utils/logger";
import { canonicalWhatsAppIdentity } from "../utils/phoneNumber";

type UtilityTemplateKey = Exclude<ApprovedUtilityTemplateKey, "reservation">;
type SubjectType = "agendamento" | "exame" | "laudo" | "ordem_servico" | "clinica";

interface UtilityTemplateRequest {
  template_key: UtilityTemplateKey;
  subject_type: SubjectType;
  subject_id: number;
  subject_ids: number[];
  destination: string;
  idempotency_key: string;
  parameters: string[];
}

interface UtilityTemplateRow {
  id: string;
  request_hash: string;
  wa_message_id: string | null;
  processing_status: string;
  button_bindings: Array<{ action: string; payload: string; index: number }> | string;
}

const SUBJECT_BY_TEMPLATE: Record<UtilityTemplateKey, SubjectType> = {
  appointmentReminder: "agendamento",
  appointmentReminderService: "agendamento",
  appointmentChange: "agendamento",
  appointmentCancellation: "agendamento",
  appointmentMissingData: "agendamento",
  appointmentFormalized: "agendamento",
  portalReportAvailable: "exame",
  portalReportLink: "exame",
  homeReportPdf: "laudo",
  receiptAvailable: "ordem_servico",
  receiptPdf: "ordem_servico",
  receiptPdfBulk: "ordem_servico",
  pendingPaymentReminder: "ordem_servico",
  pendingPaymentReminderBulk: "ordem_servico",
  portalClinicInviteActivation: "clinica",
  portalClinicInviteLoginAccess: "clinica",
  portalClinicInviteTemporaryPassword: "clinica"
};

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

function isUtilityTemplateKey(value: unknown): value is UtilityTemplateKey {
  return typeof value === "string" && value !== "reservation" && value in SUBJECT_BY_TEMPLATE;
}

function parseRequest(body: unknown): UtilityTemplateRequest {
  const source = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  if (!isUtilityTemplateKey(source.template_key)) {
    throw new Error("template_key is not an approved utility template");
  }
  const templateKey = source.template_key;
  if (templateRequiresDocumentHeader(templateKey)) {
    throw new Error(`template '${templateKey}' requires the document template route`);
  }
  const subjectType = cleanText(source.subject_type, "subject_type", 40) as SubjectType;
  if (subjectType !== SUBJECT_BY_TEMPLATE[templateKey]) {
    throw new Error(`template '${templateKey}' cannot be used with subject_type '${subjectType}'`);
  }
  const subjectId = Number(source.subject_id);
  if (!Number.isSafeInteger(subjectId) || subjectId <= 0) {
    throw new Error("subject_id must be a positive integer");
  }
  const subjectIdsRaw = source.subject_ids === undefined ? [subjectId] : source.subject_ids;
  if (!Array.isArray(subjectIdsRaw)) {
    throw new Error("subject_ids must be an array");
  }
  const subjectIds = Array.from(new Set(subjectIdsRaw.map((value) => Number(value))));
  if (
    subjectIds.length === 0 ||
    subjectIds.length > 20 ||
    subjectIds.some((value) => !Number.isSafeInteger(value) || value <= 0) ||
    !subjectIds.includes(subjectId)
  ) {
    throw new Error("subject_ids must contain subject_id and between 1 and 20 positive integers");
  }
  if (!Array.isArray(source.parameters)) {
    throw new Error("parameters must be an array");
  }
  const parameters = source.parameters.map((value, index) =>
    cleanText(
      value,
      `parameters[${index}]`,
      templateKey === "pendingPaymentReminderBulk" && index === 3 ? 900 : 300
    )
  );
  const expected = getTemplateBodyParameterCount(templateKey);
  if (parameters.length !== expected) {
    throw new Error(`template '${templateKey}' expects ${expected} parameters, received ${parameters.length}`);
  }
  if (renderApprovedTemplateBody(templateKey, parameters).length > 1024) {
    throw new Error(`template '${templateKey}' rendered body exceeds 1024 characters`);
  }

  return {
    template_key: templateKey,
    subject_type: subjectType,
    subject_id: subjectId,
    subject_ids: subjectIds,
    destination: normalizeDestination(source.destination),
    idempotency_key: cleanText(source.idempotency_key, "idempotency_key", 128),
    parameters
  };
}

function computeRequestHash(payload: UtilityTemplateRequest): string {
  return createHash("sha256").update(JSON.stringify(payload)).digest("hex");
}

function buildButtonBindings(templateKey: UtilityTemplateKey) {
  return APPROVED_UTILITY_TEMPLATES[templateKey].buttonActions.map((action, index) => ({
    action,
    index,
    payload: `fc_template_${randomBytes(24).toString("base64url")}`
  }));
}

function parseBindings(value: UtilityTemplateRow["button_bindings"]) {
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

async function reserveDelivery(payload: UtilityTemplateRequest) {
  const requestHash = computeRequestHash(payload);
  return withTransaction(async (client) => {
    const existing = await queryWithClient<UtilityTemplateRow>(
      client,
      "SELECT * FROM approved_template_messages WHERE idempotency_key = $1 FOR UPDATE",
      [payload.idempotency_key]
    );
    if (existing.rows[0]) {
      const row = existing.rows[0];
      if (row.request_hash !== requestHash) {
        throw Object.assign(new Error("idempotency_key was already used with different content"), {
          statusCode: 409
        });
      }
      if (row.processing_status === "sent" && row.wa_message_id) {
        return { row, idempotent: true };
      }
      if (row.processing_status === "pending" || row.processing_status === "ambiguous") {
        throw Object.assign(new Error("delivery is pending or ambiguous and requires operational review before retry"), {
          statusCode: 409
        });
      }
      const retried = await queryWithClient<UtilityTemplateRow>(
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
    const inserted = await queryWithClient<UtilityTemplateRow>(
      client,
      `INSERT INTO approved_template_messages (
         template_key, template_name, language_code, subject_type, subject_id, subject_ids,
         destination, idempotency_key, request_hash, body_parameters,
         button_bindings, rendered_body, processing_status, created_at, updated_at
       ) VALUES ($1, $2, 'pt_BR', $3, $4, $5::jsonb, $6, $7, $8, $9::jsonb, $10::jsonb, $11, 'pending', now(), now())
       RETURNING *`,
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
        renderApprovedTemplateBody(payload.template_key, payload.parameters)
      ]
    );
    return { row: inserted.rows[0], idempotent: false };
  });
}

async function persistSentMessage(
  row: UtilityTemplateRow,
  payload: UtilityTemplateRequest,
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
       ) VALUES ($1, $2, true, $3, 'template', $4::jsonb, 'sent', now())
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
          language_code: "pt_BR"
        })
      ]
    );
    await queryWithClient(
      client,
      `UPDATE approved_template_messages
       SET wa_message_id = $2, processing_status = 'sent', processing_error = NULL,
           sent_at = now(), updated_at = now()
       WHERE id = $1`,
      [row.id, waMessageId]
    );
  });
}

export async function sendApprovedUtilityTemplate(req: Request, res: Response): Promise<void> {
  let payload: UtilityTemplateRequest;
  try {
    payload = parseRequest(req.body);
  } catch (error) {
    res.status(422).json({ error: error instanceof Error ? error.message : "invalid request" });
    return;
  }

  try {
    assertTemplateDeliveryApproved(payload.template_key);
  } catch (error) {
    res.status(409).json({
      code: "WHATSAPP_TEMPLATE_APPROVAL_PENDING",
      error: error instanceof Error ? error.message : "O lembrete com serviço aguarda aprovação da Meta."
    });
    return;
  }

  let reserved: { row: UtilityTemplateRow; idempotent: boolean };
  try {
    reserved = await reserveDelivery(payload);
  } catch (error) {
    const statusCode = Number((error as { statusCode?: number }).statusCode) || 500;
    res.status(statusCode).json({ error: error instanceof Error ? error.message : "delivery reservation failed" });
    return;
  }

  if (reserved.idempotent && reserved.row.wa_message_id) {
    res.status(200).json({ message_id: reserved.row.wa_message_id, idempotent: true });
    return;
  }

  const phoneNumberId = String(process.env.PHONE_NUMBER_ID || "").trim();
  const accessToken = String(process.env.WHATSAPP_ACCESS_TOKEN || "").trim();
  let providerMessageId: string | null = null;
  try {
    const provider = await sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId,
      accessToken,
      to: payload.destination,
      templateKey: payload.template_key,
      bodyParameters: payload.parameters,
      quickReplyPayloads: parseBindings(reserved.row.button_bindings).map((binding) => binding.payload)
    });
    const messageId = provider.messages?.[0]?.id;
    if (!messageId) {
      throw new Error("Meta response did not include a message id");
    }
    providerMessageId = messageId;
    await persistSentMessage(reserved.row, payload, messageId);
    res.status(201).json({ message_id: messageId, idempotent: false });
  } catch (error) {
    const graphError = error instanceof WhatsAppGraphApiError ? error : null;
    const ambiguous = Boolean(providerMessageId || (graphError && (graphError.status === undefined || graphError.status >= 500)));
    await query(
      `UPDATE approved_template_messages
       SET processing_status = $2, processing_error = $3,
           wa_message_id = COALESCE(wa_message_id, $4), updated_at = now()
       WHERE id = $1 AND processing_status <> 'sent'`,
      [
        reserved.row.id,
        ambiguous ? "ambiguous" : "failed",
        error instanceof Error ? error.message.slice(0, 2000) : "unknown provider error",
        providerMessageId
      ]
    );
    logger.error("Approved utility template delivery failed", {
      templateKey: payload.template_key,
      subjectType: payload.subject_type,
      subjectId: payload.subject_id,
      details: extractDbErrorDetails(error)
    });
    const providerStatus = Number((error as { status?: number }).status);
    res.status(providerStatus >= 400 && providerStatus < 500 ? 502 : 503).json({
      error: "WhatsApp provider rejected or did not complete the template delivery"
    });
  }
}
