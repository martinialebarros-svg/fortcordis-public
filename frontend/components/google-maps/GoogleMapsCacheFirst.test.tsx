import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AxiosError, AxiosHeaders, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import api from "@/lib/axios";
import { mapsConfirmationStore, type MapsQuote } from "@/lib/google-maps-control";
import GoogleMapsActionGuard from "./GoogleMapsActionGuard";

const quote: MapsQuote = {
  operation_mode: "paid_budget", required: true, blocked: false, quote_id: "synthetic-quote",
  action: "Criar agendamento e validar deslocamentos", service: "Google Maps Platform",
  services: ["routes_essentials"], max_calls: 4, estimated_cost_min_brl: 0, estimated_cost_max_brl: 0.24,
  limits: { action: { calls: 4, estimated_brl: 1 }, day: { calls: 20, estimated_brl: 5 }, month: { calls: 100, estimated_brl: 20 } },
  consumption: { day: { calls: 2, estimated_brl: 0.12 }, month: { calls: 8, estimated_brl: 0.48 } },
  remaining: { day: { calls: 18, estimated_brl: 4.88 }, month: { calls: 92, estimated_brl: 19.52 } },
};

describe("Agenda cache-first sem bloquear trabalho local", () => {
  let prior: typeof api.defaults.adapter;
  let requests: InternalAxiosRequestConfig[];
  let cacheHit: boolean;
  let paidCalls: number;
  let paidQuote: MapsQuote;
  let previewFailure: boolean;
  let paidDenial: boolean;
  let serverRecorded: boolean;
  beforeEach(() => {
    prior = api.defaults.adapter; requests = []; cacheHit = false; paidCalls = 0;
    paidQuote = { ...quote }; previewFailure = false; paidDenial = false;
    serverRecorded = false;
    const adapter: AxiosAdapter = async (config) => {
      requests.push(config);
      const ok = (data: unknown) => ({ config, data, status: 200, statusText: "OK", headers: new AxiosHeaders() });
      if (config.url === "/google-maps-control/preview") {
        if (previewFailure) throw new AxiosError("Synthetic preview offline", "ERR_NETWORK", config);
        const body = JSON.parse(config.data);
        return ok(body.paid_call_required ? paidQuote : { ...quote, operation_mode: "cache_first", required: false, quote_id: null, max_calls: 0, estimated_cost_max_brl: 0, confirmation_mode: serverRecorded ? "server_recorded" : "per_action" });
      }
      if (config.url === "/google-maps-control/confirm") return ok({ token: `synthetic-once-${requests.length}` });
      if (config.url === "/agenda") {
        if (serverRecorded) {
          if (paidDenial) throw new AxiosError("Synthetic ledger offline", "ERR_BAD_RESPONSE", config, undefined,
            { config, data: { detail: { code: "GOOGLE_MAPS_COST_BLOCKED", reason: "ledger_unavailable", message: "Não foi possível verificar o limite compartilhado." } }, status: 503, statusText: "Unavailable", headers: new AxiosHeaders() });
          paidCalls++; return ok({ id: 123 });
        }
        const authorized = config.headers.has("X-Google-Maps-Action");
        if (authorized) { paidCalls++; if (!paidDenial) return ok({ id: 123 }); }
        else if (cacheHit) return ok({ id: 123 });
        const detail = { code: "GOOGLE_MAPS_COST_BLOCKED", reason: authorized ? "day_limit" : "confirmation_required",
          message: authorized ? "Limite diário atingido." : "Confirme a consulta paga.", can_retry_with_confirmation: !authorized };
        throw new AxiosError("Synthetic Maps response", "ERR_BAD_REQUEST", config, undefined,
          { config, data: { detail }, status: 409, statusText: "Conflict", headers: new AxiosHeaders() });
      }
      return ok({});
    };
    api.defaults.adapter = adapter;
  });
  afterEach(() => {
    act(() => { mapsConfirmationStore.cancelAll(); mapsConfirmationStore.dismissNotice(); });
    api.defaults.adapter = prior;
  });

  it("cache válido cria sem popup nem token ou chamada paga", async () => {
    cacheHit = true; render(<GoogleMapsActionGuard />);
    const result = await api.post("/agenda", { inicio: "2099-05-25T11:30:00" });
    expect(result.data.id).toBe(123); expect(paidCalls).toBe(0);
    expect(requests.map((r) => r.url)).toEqual(["/google-maps-control/preview", "/agenda"]);
    expect(requests[0].timeout).toBe(3_000);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("registro interno conclui uma execução sem popup, confirmação ou repetição", async () => {
    serverRecorded = true; render(<GoogleMapsActionGuard />);
    const result = await api.post("/agenda", { inicio: "2099-05-25T11:30:00" });
    expect(result.data.id).toBe(123); expect(paidCalls).toBe(1);
    expect(requests.map((r) => r.url)).toEqual(["/google-maps-control/preview", "/agenda"]);
    expect(requests[1].headers.has("X-Google-Maps-Action")).toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("registro interno continua no servidor se a prévia estiver indisponível", async () => {
    serverRecorded = true; previewFailure = true; render(<GoogleMapsActionGuard />);
    await api.post("/agenda", {});
    expect(paidCalls).toBe(1);
    expect(requests.filter((r) => r.url === "/agenda")).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("falha real do ledger permanece visível sem popup de custo nem tentativas extras", async () => {
    serverRecorded = true; paidDenial = true; render(<GoogleMapsActionGuard />);
    await api.post("/agenda", {}).catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("limite compartilhado");
    expect(screen.queryByRole("dialog")).toBeNull(); expect(paidCalls).toBe(0);
    expect(requests.filter((r) => r.url === "/agenda")).toHaveLength(1);
  });

  it("cancelar após miss preserva formulário e não consulta Google", async () => {
    render(<><input aria-label="Paciente preenchido" defaultValue="Paciente sintético" /><GoogleMapsActionGuard /></>);
    const result = api.post("/agenda", { inicio: "2099-05-25T11:30:00" }).catch((e) => e);
    await screen.findByRole("dialog"); expect(paidCalls).toBe(0);
    expect(requests.filter((r) => r.url === "/agenda")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect((await result).code).toBe("ERR_CANCELED"); expect(paidCalls).toBe(0);
    expect(requests.some((r) => r.url === "/google-maps-control/confirm")).toBe(false);
    expect(screen.getByLabelText("Paciente preenchido")).toHaveValue("Paciente sintético");
  });

  it("confirma uma única repetição exata com teto e sem reutilizar consentimento", async () => {
    render(<GoogleMapsActionGuard />);
    const payload = { inicio: "2099-05-25T11:30:00", observacoes: "Sintético" };
    const result = api.post("/agenda", payload);
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar esta ação" }));
    await result; expect(paidCalls).toBe(1);
    const agenda = requests.filter((r) => r.url === "/agenda");
    expect(agenda).toHaveLength(2); expect(JSON.parse(agenda[0].data)).toEqual(payload); expect(JSON.parse(agenda[1].data)).toEqual(payload);
    expect(agenda[0].headers.has("X-Google-Maps-Action")).toBe(false);
    expect(agenda[1].headers.get("X-Google-Maps-Action")).toMatch(/^synthetic-once-/);
    const paidPreview = requests.find((r) => r.url === "/google-maps-control/preview" && JSON.parse(r.data).paid_call_required);
    expect(paidPreview?.timeout).toBe(15_000);
    const retry = api.request(agenda[1]).catch((e) => e);
    await screen.findByRole("dialog"); fireEvent.click(screen.getByRole("button", { name: "Cancelar" })); await retry;
    expect(paidCalls).toBe(1);
  });

  it("teto esgotado bloqueia apenas a consulta nova; cache permanece utilizável", async () => {
    paidQuote = { ...quote, blocked: true, reason: "day_limit", message: "Limite diário atingido." };
    render(<GoogleMapsActionGuard />);
    await api.post("/agenda", {}).catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("Os dados preenchidos permanecem no formulário");
    expect(screen.queryByRole("dialog")).toBeNull(); expect(paidCalls).toBe(0);
    cacheHit = true; await api.post("/agenda", {}); expect(paidCalls).toBe(0);
  });

  it("preview fora do ar não derruba agendamento em cache", async () => {
    previewFailure = true; cacheHit = true; render(<GoogleMapsActionGuard />);
    await api.post("/agenda", {}); expect(paidCalls).toBe(0); expect(screen.queryByRole("alert")).toBeNull();
  });

  it("preview fora do ar não libera a consulta externa necessária", async () => {
    previewFailure = true; render(<GoogleMapsActionGuard />);
    await api.post("/agenda", {}).catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível verificar"); expect(paidCalls).toBe(0);
    expect(requests.filter((r) => r.url === "/agenda")).toHaveLength(1);
  });

  it("recusa após consentimento não inicia um loop de repetição", async () => {
    paidDenial = true; render(<GoogleMapsActionGuard />);
    const result = api.post("/agenda", {}).catch((e) => e);
    await screen.findByRole("dialog"); fireEvent.click(screen.getByRole("button", { name: "Confirmar esta ação" })); await result;
    expect(requests.filter((r) => r.url === "/agenda")).toHaveLength(2);
    expect(requests.filter((r) => r.url === "/google-maps-control/confirm")).toHaveLength(1);
    expect(await screen.findByRole("alert")).toHaveTextContent("Limite diário");
  });

  it("ações simultâneas não compartilham confirmação", async () => {
    render(<GoogleMapsActionGuard />);
    const first = api.post("/agenda", { paciente_id: 1 }).catch((e) => e);
    const second = api.post("/agenda", { paciente_id: 2 }).catch((e) => e);
    await waitFor(() => expect(mapsConfirmationStore.getSnapshot().queue).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar esta ação" }));
    await waitFor(() => expect(paidCalls).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" })); await Promise.all([first, second]);
    expect(paidCalls).toBe(1);
  });
});
