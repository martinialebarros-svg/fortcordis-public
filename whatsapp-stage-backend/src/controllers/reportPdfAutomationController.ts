import { createHash } from "crypto";
import { Request, Response } from "express";
import { query, withTransaction } from "../services/dbService";
import { describeCustomerServiceWindow } from "../services/customerServiceWindow";
import { sendWhatsAppDocumentMessageWithRetry, uploadWhatsAppPdfWithRetry, WhatsAppGraphApiError } from "../services/whatsappService";
import { canonicalWhatsAppIdentity, whatsappGraphRecipient } from "../utils/phoneNumber";

type Delivery = { id: string; request_hash: string; status: string; wa_message_id: string | null; wa_media_id: string | null };

export async function sendReportPdfInCustomerWindow(req: Request, res: Response): Promise<void> {
  const internalToken = String(process.env.WHATSAPP_INTERNAL_API_TOKEN || "").trim();
  if (!internalToken || req.header("x-whatsapp-internal-token") !== internalToken) {
    res.status(403).json({ error: "Internal automation token required" });
    return;
  }
  const reportId = Number(req.body?.laudo_id);
  const destination = String(req.body?.destination || "").replace(/\D/g, "");
  const idempotencyKey = String(req.body?.idempotency_key || "").trim();
  const filename = String(req.body?.filename || "").trim();
  const file = req.file;
  if (!Number.isSafeInteger(reportId) || reportId <= 0 || !/^\d{12,15}$/.test(destination)
      || idempotencyKey.length < 8 || idempotencyKey.length > 128
      || filename.length > 160 || !/^[a-zA-Z0-9._-]+\.pdf$/i.test(filename)
      || !file || file.mimetype !== "application/pdf" || !file.buffer.subarray(0, 4).equals(Buffer.from("%PDF"))) {
    res.status(422).json({ error: "Invalid report PDF request" });
    return;
  }
  const identity = canonicalWhatsAppIdentity(destination);
  const hash = createHash("sha256").update(JSON.stringify({
    reportId, destination, filename,
    document_sha256: createHash("sha256").update(file.buffer).digest("hex")
  })).digest("hex");
  const previous = await query<Delivery>(
    "SELECT * FROM report_pdf_messages WHERE idempotency_key = $1", [idempotencyKey]
  );
  if (previous.rows[0]) {
    if (previous.rows[0].request_hash !== hash) {
      res.status(409).json({ error: "Chave de envio ja usada com outro PDF." });
      return;
    }
    if (previous.rows[0].status === "sent" && previous.rows[0].wa_message_id) {
      res.json({ message_id: previous.rows[0].wa_message_id, media_id: previous.rows[0].wa_media_id, idempotent: true });
      return;
    }
    if (previous.rows[0].status !== "failed") {
      res.status(409).json({ error: "Envio anterior pendente ou incerto. Verifique a conversa antes de repetir." });
      return;
    }
  }
  const templateDelivery = await query<{
    subject_type: string; subject_id: string; destination: string; document_sha256: string | null;
    document_filename: string | null; processing_status: string; wa_message_id: string | null; wa_media_id: string | null;
  }>("SELECT subject_type, subject_id, destination, document_sha256, document_filename, processing_status, wa_message_id, wa_media_id FROM approved_template_messages WHERE idempotency_key = $1", [idempotencyKey]);
  if (templateDelivery.rows[0]) {
    const prior = templateDelivery.rows[0];
    if (prior.subject_type !== "laudo" || Number(prior.subject_id) !== reportId || prior.destination !== destination
        || prior.document_filename !== filename
        || prior.document_sha256 !== createHash("sha256").update(file.buffer).digest("hex")) {
      res.status(409).json({ error: "Chave de envio ja usada com outro documento." });
      return;
    }
    if (prior.processing_status === "sent" && prior.wa_message_id) {
      res.json({ message_id: prior.wa_message_id, media_id: prior.wa_media_id, idempotent: true });
      return;
    }
    if (prior.processing_status !== "failed") {
      res.status(409).json({ error: "Envio anterior pendente ou incerto. Verifique a conversa antes de repetir." });
      return;
    }
  }
  const conversation = await query<{ id: string; last_inbound_at: Date | null }>(
    "SELECT id, last_inbound_at FROM conversations WHERE wa_phone_number = $1", [identity]
  );
  if (!conversation.rows[0] || !describeCustomerServiceWindow(conversation.rows[0].last_inbound_at).is_open) {
    res.status(409).json({ code: "CUSTOMER_WINDOW_CLOSED", error: "A janela de atendimento do tutor esta fechada." });
    return;
  }
  let reserved: { row: Delivery; idempotent: boolean };
  try {
    reserved = await withTransaction(async (client) => {
      const existing = await client.query<Delivery>(
        "SELECT * FROM report_pdf_messages WHERE idempotency_key = $1 FOR UPDATE", [idempotencyKey]
      );
      if (existing.rows[0]) {
        const row = existing.rows[0];
        if (row.request_hash !== hash) throw new Error("Chave de envio ja usada com outro PDF.");
        if (row.status === "sent" && row.wa_message_id) return { row, idempotent: true };
        if (row.status === "failed") {
          const retried = await client.query<Delivery>(
            "UPDATE report_pdf_messages SET status = 'pending', updated_at = now() WHERE id = $1 RETURNING *", [row.id]
          );
          return { row: retried.rows[0], idempotent: false };
        }
        throw new Error("Envio anterior pendente ou incerto. Verifique a conversa antes de repetir.");
      }
      const inserted = await client.query<Delivery>(
        `INSERT INTO report_pdf_messages (laudo_id, conversation_id, destination, idempotency_key, request_hash, filename, status)
         VALUES ($1, $2, $3, $4, $5, $6, 'pending') RETURNING *`,
        [reportId, conversation.rows[0].id, destination, idempotencyKey, hash, filename]
      );
      return { row: inserted.rows[0], idempotent: false };
    });
  } catch (error) {
    res.status(409).json({ error: error instanceof Error ? error.message : "Falha ao reservar envio." });
    return;
  }
  if (reserved.idempotent) {
    res.json({ message_id: reserved.row.wa_message_id, media_id: reserved.row.wa_media_id, idempotent: true });
    return;
  }
  let mediaId: string | null = null;
  let messageId: string | null = null;
  try {
    const phoneNumberId = String(process.env.PHONE_NUMBER_ID || "").trim();
    const accessToken = String(process.env.WHATSAPP_ACCESS_TOKEN || "").trim();
    if (!phoneNumberId || !accessToken) throw new Error("WhatsApp nao configurado.");
    mediaId = (await uploadWhatsAppPdfWithRetry({ phoneNumberId, accessToken, filename, content: file.buffer })).id;
    const response = await sendWhatsAppDocumentMessageWithRetry({
      phoneNumberId, accessToken, to: whatsappGraphRecipient(destination), mediaId, filename
    });
    messageId = response.messages?.[0]?.id || null;
    if (!messageId) throw new Error("Meta nao confirmou o identificador da mensagem.");
    await withTransaction(async (client) => {
      await client.query(
        `INSERT INTO messages (conversation_id, wa_message_id, from_me, body, type, metadata, status, created_at)
         VALUES ($1, $2, true, $3, 'document', $4::jsonb, 'sent', now()) ON CONFLICT (wa_message_id) DO NOTHING`,
        [conversation.rows[0].id, messageId, filename, JSON.stringify({ source: "laudo_domiciliar", laudo_id: reportId,
          wa_media_id: mediaId, document_filename: filename })]
      );
      await client.query(
        "UPDATE report_pdf_messages SET status = 'sent', wa_message_id = $2, wa_media_id = $3, updated_at = now() WHERE id = $1",
        [reserved.row.id, messageId, mediaId]
      );
    });
    res.status(201).json({ message_id: messageId, media_id: mediaId, idempotent: false });
  } catch (error) {
    const graphError = error instanceof WhatsAppGraphApiError ? error : null;
    const ambiguous = Boolean(messageId || (graphError && (graphError.status === undefined || graphError.status >= 500)));
    await query("UPDATE report_pdf_messages SET status = $2, wa_media_id = $3, wa_message_id = $4, updated_at = now() WHERE id = $1",
      [reserved.row.id, ambiguous ? "ambiguous" : "failed", mediaId, messageId]);
    res.status(502).json({ error: ambiguous ? "Envio incerto. Verifique a conversa antes de repetir." : "Falha ao enviar o PDF pelo WhatsApp." });
  }
}
