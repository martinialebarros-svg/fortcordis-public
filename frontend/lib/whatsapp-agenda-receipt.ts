interface WhatsAppAgendaReceiptMessage {
  type: unknown;
  from_me: unknown;
  metadata?: unknown;
}

type AgendaReceiptLabel = "Presença registrada na agenda." | "Reserva confirmada na agenda.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Exibe apenas o resultado persistido pela agenda, sem inferir sucesso do botão recebido. */
export function agendaReceiptLabel(message: WhatsAppAgendaReceiptMessage): AgendaReceiptLabel | null {
  if (message.from_me !== false || message.type !== "button" || !isRecord(message.metadata)) return null;
  const receipt = message.metadata.agenda_receipt;
  if (!isRecord(receipt)) return null;

  if (receipt.source === "appointmentReminder" && receipt.action === "confirmar_presenca" && receipt.result === "presenca_confirmada" &&
    (receipt.status === "Agendado" || receipt.status === "Confirmado")) {
    return "Presença registrada na agenda.";
  }
  if (receipt.source === "reservation" && receipt.action === "confirmar" && (receipt.result === "confirmado" || receipt.result === "ja_confirmado") &&
    receipt.status === "Confirmado") {
    return "Reserva confirmada na agenda.";
  }
  return null;
}
