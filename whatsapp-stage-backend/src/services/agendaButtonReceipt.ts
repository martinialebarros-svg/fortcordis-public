export type AgendaButtonReceipt =
  | { source: "reservation"; action: "confirmar"; result: "confirmado" | "ja_confirmado"; status: "Confirmado" }
  | { source: "appointmentReminder"; action: "confirmar_presenca"; result: "presenca_confirmada"; status: "Agendado" | "Confirmado" };

/** Only the authenticated domain response can resolve this individual inbound. */
export function buildAgendaButtonReceipt(
  source: string,
  action: string,
  agendamentoId: number,
  response: unknown
): AgendaButtonReceipt | undefined {
  if (!response || typeof response !== "object" || Array.isArray(response)) return;
  const result = response as Record<string, unknown>;
  if (result.action !== action || result.agendamento_id !== agendamentoId) return;
  // Only this explicitly registered successor shares the reminder receipt contract.
  const receiptSource = source === "appointmentReminderService" ? "appointmentReminder" : source;
  if (source === "reservation" && action === "confirmar"
      && (result.result === "confirmado" || result.result === "ja_confirmado")
      && result.status === "Confirmado") {
    return { source, action, result: result.result, status: result.status };
  }
  if (receiptSource === "appointmentReminder" && action === "confirmar_presenca"
      && result.result === "presenca_confirmada"
      && (result.status === "Agendado" || result.status === "Confirmado")) {
    return { source: receiptSource, action, result: result.result, status: result.status };
  }
}
