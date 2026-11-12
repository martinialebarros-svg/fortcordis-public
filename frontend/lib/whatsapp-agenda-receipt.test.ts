import { describe, expect, it } from "vitest";
import { agendaReceiptLabel } from "./whatsapp-agenda-receipt";

const incomingButton = (receipt: unknown) => ({
  type: "button", from_me: false, metadata: { agenda_receipt: receipt },
});

describe("resultado da confirmação na agenda", () => {
  it.each(["Agendado", "Confirmado"])("mostra a presença registrada com status %s sem afirmar realização", (status) => {
    expect(agendaReceiptLabel(incomingButton({
      source: "appointmentReminder", action: "confirmar_presenca", result: "presenca_confirmada", status,
    }))).toBe("Presença registrada na agenda.");
  });

  it.each(["confirmado", "ja_confirmado"])("mostra a reserva confirmada com resultado %s, sem depender de identificador", (result) => {
    expect(agendaReceiptLabel(incomingButton({
      source: "reservation", action: "confirmar", result, status: "Confirmado",
    }))).toBe("Reserva confirmada na agenda.");
  });

  it.each([
    { action: "confirmar", result: "confirmado", status: "Confirmado" },
    { source: "appointmentReminder", action: "confirmar", result: "confirmado", status: "Confirmado" },
    { source: "reservation", action: "confirmar_presenca", result: "presenca_confirmada", status: "Agendado" },
    { source: "unknown", action: "confirmar", result: "confirmado", status: "Confirmado" },
    { source: "appointmentReminder", action: "confirmar_presenca", result: "confirmado", status: "Confirmado" },
    { source: "reservation", action: "confirmar", result: "presenca_confirmada", status: "Confirmado" },
    { source: "reservation", action: "confirmar", result: "confirmado", status: "Agendado" },
    { source: "appointmentReminder", action: "confirmar_presenca", result: "presenca_confirmada", status: "Realizado" },
    { source: "reservation", action: "confirmar", result: "confirmado", status: "Realizado" },
    { source: "appointmentReminder", action: "confirmar_presenca", result: "presenca_confirmada", status: "Cancelado" },
    { source: "reservation", action: "confirmar", result: "erro", status: "Confirmado" },
    { action: "cancelar", result: "confirmado", status: "Confirmado" },
    { source: "reservation", action: "confirmar", result: "confirmado" },
    { source: "reservation", action: "confirmar", result: "Confirmado", status: "Confirmado" },
  ])("não apresenta sucesso para pares incompatíveis, falhas ou status não autorizado: %j", (receipt) => {
    expect(agendaReceiptLabel(incomingButton(receipt))).toBeNull();
  });

  it.each([undefined, null, "confirmado", [], {}, { source: "reservation", action: "confirmar" }])("ignora recibo incompleto ou malformado: %j", (receipt) => {
    expect(agendaReceiptLabel(incomingButton(receipt))).toBeNull();
  });

  it.each([undefined, null, [], "confirmado", { button: { payload: "confirmar:1", text: "Confirmar" } }])(
    "não infere confirmação a partir de metadados ausentes ou do botão bruto: %j", (metadata) => {
      expect(agendaReceiptLabel({ type: "button", from_me: false, metadata })).toBeNull();
    },
  );

  it("não exibe recibo em mensagem enviada nem em mensagem que não é botão recebido", () => {
    const confirmed = incomingButton({ source: "reservation", action: "confirmar", result: "confirmado", status: "Confirmado" });
    expect(agendaReceiptLabel({ ...confirmed, from_me: true })).toBeNull();
    expect(agendaReceiptLabel({ ...confirmed, from_me: undefined })).toBeNull();
    expect(agendaReceiptLabel({ ...confirmed, type: "text" })).toBeNull();
    expect(agendaReceiptLabel({ ...confirmed, type: "interactive" })).toBeNull();
  });
});
