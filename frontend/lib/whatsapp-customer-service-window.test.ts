import { describe, expect, it } from "vitest";
import { evaluateCustomerServiceWindow } from "./whatsapp-customer-service-window";

describe("evaluateCustomerServiceWindow", () => {
  const serviceWindow = {
    last_inbound_at: "2026-08-16T12:00:00.000Z",
    expires_at: "2026-08-17T12:00:00.000Z",
    is_open: true,
  };

  it("mantem a resposta livre antes do prazo", () => {
    expect(
      evaluateCustomerServiceWindow(serviceWindow, new Date("2026-08-17T11:59:59.999Z").getTime())
    ).toEqual({
      isOpen: true,
      hasInboundMessage: true,
      expiresAt: serviceWindow.expires_at,
    });
  });

  it("fecha a resposta livre exatamente depois de 24 horas", () => {
    expect(
      evaluateCustomerServiceWindow(serviceWindow, new Date("2026-08-17T12:00:00.000Z").getTime())
        .isOpen
    ).toBe(false);
  });

  it("falha fechado quando nao existe mensagem recebida", () => {
    expect(evaluateCustomerServiceWindow(null)).toEqual({
      isOpen: false,
      hasInboundMessage: false,
      expiresAt: null,
    });
  });
});
