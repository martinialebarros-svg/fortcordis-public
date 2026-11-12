import { describe, expect, it, vi } from "vitest";
import {
  buildFrontendPerformancePayload,
  FRONTEND_ROUTE_READY_EVENT,
  normalizeMonitoredFrontendRoute,
  signalFrontendRouteReady,
} from "./frontend-performance";

describe("frontend performance helpers", () => {
  it("aceita somente as quatro rotas exatas e remove query string", () => {
    expect(normalizeMonitoredFrontendRoute("/dashboard?aba=hoje")).toBe("/dashboard");
    expect(normalizeMonitoredFrontendRoute("/atendimento/")).toBe("/atendimento");
    expect(normalizeMonitoredFrontendRoute("/laudos/42/editar")).toBeNull();
    expect(normalizeMonitoredFrontendRoute("/financeiro")).toBeNull();
  });

  it("mantem content_ms maior ou igual ao shell e limita duracoes", () => {
    expect(buildFrontendPerformancePayload({
      route: "/dashboard",
      navigationType: "client",
      outcome: "ready",
      startedAt: 100,
      shellAt: 180,
      contentAt: 150,
    })).toEqual({
      route_group: "/dashboard",
      navigation_type: "client",
      outcome: "ready",
      shell_ms: 80,
      content_ms: 80,
    });
  });

  it("emite somente rota agrupada, desfecho e instante de prontidao", () => {
    const listener = vi.fn();
    window.addEventListener(FRONTEND_ROUTE_READY_EVENT, listener);
    signalFrontendRouteReady("/configuracoes?aba=observabilidade", "partial");
    window.removeEventListener(FRONTEND_ROUTE_READY_EVENT, listener);

    expect(listener).toHaveBeenCalledTimes(1);
    const detail = (listener.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.route).toBe("/configuracoes");
    expect(detail.outcome).toBe("partial");
    expect(Object.keys(detail).sort()).toEqual(["outcome", "readyAt", "route"]);
  });
});
