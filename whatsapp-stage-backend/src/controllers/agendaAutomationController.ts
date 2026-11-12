import { createHash, randomBytes } from "crypto";
import { Request, Response } from "express";
import {
  extractDbErrorDetails,
  query,
  queryWithClient,
  withTransaction
} from "../services/dbService";
import {
  sendWhatsAppReservationTemplateWithRetry,
  WhatsAppGraphApiError
} from "../services/whatsappService";
import { logger } from "../utils/logger";
import { canonicalWhatsAppIdentity } from "../utils/phoneNumber";
import { renderApprovedTemplateBody } from "../templates/approvedTemplates";

interface ReservationParameters {
  recipient_name: string;
  pet_name: string;
  appointment_date: string;
  appointment_time: string;
  confirmation_deadline: string;
}

interface ReservationRequest {
  reservation_id: number;
  destination: string;
  idempotency_key: string;
  parameters: ReservationParameters;
}

interface ReservationRow {
  id: string;
  reservation_id: string;
  destination: string;
  idempotency_key: string;
  request_hash: string;
  confirm_payload: string;
  change_payload: string;
  wa_message_id: string | null;
  processing_status: string;
}

function cleanText(value: unknown, field: string, maxLength = 160): string {
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

function parseRequest(body: unknown): ReservationRequest {
  const source = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  const reservationId = Number(source.reservation_id);
  if (!Number.isSafeInteger(reservationId) || reservationId <= 0) {
    throw new Error("reservation_id must be a positive integer");
  }

  const rawParameters = (
    source.parameters && typeof source.parameters === "object" ? source.parameters : {}
  ) as Record<string, unknown>;

  return {
    reservation_id: reservationId,
    destination: normalizeDestination(source.destination),
    idempotency_key: cleanText(source.idempotency_key, "idempotency_key", 128),
    parameters: {
      recipient_name: cleanText(rawParameters.recipient_name, "recipient_name", 120),
      pet_name: cleanText(rawParameters.pet_name, "pet_name", 120),
      appointment_date: cleanText(rawParameters.appointment_date, "appointment_date", 30),
      appointment_time: cleanText(rawParameters.appointment_time, "appointment_time", 20),
      confirmation_deadline: cleanText(rawParameters.confirmation_deadline, "confirmation_deadline", 50)
    }
  };
}

function computeRequestHash(payload: ReservationRequest): string {
  return createHash("sha256").update(JSON.stringify(payload)).digest("hex");
}

function newButtonPayload(prefix: "confirm" | "change"): string {
  return `fc_agenda_${prefix}_${randomBytes(24).toString("base64url")}`;
}

async function reserveDelivery(payload: ReservationRequest): Promise<{ row: ReservationRow; idempotent: boolean }> {
  const requestHash = computeRequestHash(payload);
  return withTransaction(async (client) => {
    const existing = await queryWithClient<ReservationRow>(
      client,
      `SELECT * FROM agenda_reservation_messages WHERE idempotency_key = $1 FOR UPDATE`,
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

      const retried = await queryWithClient<ReservationRow>(
        client,
        `
          UPDATE agenda_reservation_messages
          SET processing_status = 'pending', processing_error = NULL, updated_at = now()
          WHERE id = $1
          RETURNING *
        `,
        [row.id]
      );
      return { row: retried.rows[0], idempotent: false };
    }

    const inserted = await queryWithClient<ReservationRow>(
      client,
      `
        INSERT INTO agenda_reservation_messages (
          reservation_id, destination, idempotency_key, request_hash,
          template_name, language_code, confirm_payload, change_payload,
          processing_status, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', now(), now())
        RETURNING *
      `,
      [
        payload.reservation_id,
        payload.destination,
        payload.idempotency_key,
        requestHash,
        process.env.WHATSAPP_RESERVATION_TEMPLATE_NAME || "reserva_de_agendamento",
        process.env.WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE || "pt_BR",
        newButtonPayload("confirm"),
        newButtonPayload("change")
      ]
    );
    return { row: inserted.rows[0], idempotent: false };
  });
}

async function persistSentMessage(
  row: ReservationRow,
  payload: ReservationRequest,
  waMessageId: string
): Promise<void> {
  const renderedBody = renderApprovedTemplateBody("reservation", [
    payload.parameters.recipient_name,
    payload.parameters.pet_name,
    payload.parameters.appointment_date,
    payload.parameters.appointment_time,
    payload.parameters.confirmation_deadline
  ]);

  await withTransaction(async (client) => {
    const conversation = await queryWithClient<{ id: string }>(
      client,
      `
        INSERT INTO conversations (
          wa_phone_number, wa_psid, status, last_activity_at, created_at, updated_at
        ) VALUES ($1, $1, 'open', now(), now(), now())
        ON CONFLICT (wa_phone_number)
        DO UPDATE SET updated_at = now(), last_activity_at = now()
        RETURNING id
      `,
      [canonicalWhatsAppIdentity(payload.destination)]
    );
    await queryWithClient(
      client,
      `
        INSERT INTO messages (
          conversation_id, wa_message_id, from_me, body, type, metadata, status, created_at
        ) VALUES ($1, $2, true, $3, 'template', $4::jsonb, 'sent', now())
        ON CONFLICT (wa_message_id) DO NOTHING
      `,
      [
        conversation.rows[0].id,
        waMessageId,
        renderedBody,
        JSON.stringify({
          source: "agenda.reservation",
          reservation_id: payload.reservation_id,
          template_name: process.env.WHATSAPP_RESERVATION_TEMPLATE_NAME || "reserva_de_agendamento",
          language_code: process.env.WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE || "pt_BR"
        })
      ]
    );
    await queryWithClient(
      client,
      `
        UPDATE agenda_reservation_messages
        SET wa_message_id = $2,
            processing_status = 'sent',
            processing_error = NULL,
            sent_at = now(),
            updated_at = now()
        WHERE id = $1
      `,
      [row.id, waMessageId]
    );
  });
}

export async function sendAgendaReservation(req: Request, res: Response): Promise<void> {
  let payload: ReservationRequest;
  try {
    payload = parseRequest(req.body);
  } catch (error) {
    res.status(422).json({ error: error instanceof Error ? error.message : "invalid request" });
    return;
  }

  let reserved: { row: ReservationRow; idempotent: boolean };
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
    const provider = await sendWhatsAppReservationTemplateWithRetry({
      phoneNumberId,
      accessToken,
      to: payload.destination,
      templateName: process.env.WHATSAPP_RESERVATION_TEMPLATE_NAME || "reserva_de_agendamento",
      languageCode: process.env.WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE || "pt_BR",
      bodyParameters: [
        payload.parameters.recipient_name,
        payload.parameters.pet_name,
        payload.parameters.appointment_date,
        payload.parameters.appointment_time,
        payload.parameters.confirmation_deadline
      ],
      confirmPayload: reserved.row.confirm_payload,
      changePayload: reserved.row.change_payload
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
    const ambiguous = Boolean(
      providerMessageId ||
      (graphError && (graphError.status === undefined || graphError.status >= 500))
    );
    await query(
      `
        UPDATE agenda_reservation_messages
        SET processing_status = $2,
            processing_error = $3,
            wa_message_id = COALESCE(wa_message_id, $4),
            updated_at = now()
        WHERE id = $1 AND processing_status <> 'sent'
      `,
      [
        reserved.row.id,
        ambiguous ? "ambiguous" : "failed",
        error instanceof Error ? error.message.slice(0, 2000) : "unknown provider error",
        providerMessageId
      ]
    );
    logger.error("Agenda reservation template delivery failed", {
      reservationId: payload.reservation_id,
      details: extractDbErrorDetails(error)
    });
    const providerStatus = Number((error as { status?: number }).status);
    res.status(providerStatus >= 400 && providerStatus < 500 ? 502 : 503).json({
      error: "WhatsApp provider rejected or did not complete the template delivery"
    });
  }
}
