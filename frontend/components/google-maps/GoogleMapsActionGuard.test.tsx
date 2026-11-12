import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AxiosHeaders, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import api from "@/lib/axios";
import { mapsConfirmationStore, type MapsQuote } from "@/lib/google-maps-control";
import GoogleMapsActionGuard from "./GoogleMapsActionGuard";

vi.mock("next/navigation", () => ({ usePathname: () => "/agenda" }));

const quote: MapsQuote = {
  required: true, blocked: false, quote_id: "quote-1", action: "Buscar horários",
  service: "Google Maps Platform", services: ["Routes Essentials"], max_calls: 4,
  estimated_cost_min_brl: 0, estimated_cost_max_brl: 0.16,
  limits: { action: { calls: 4, estimated_brl: 1 }, day: { calls: 20, estimated_brl: 5 }, month: { calls: 100, estimated_brl: 30 } },
  consumption: { day: { calls: 2, estimated_brl: 0.08 }, month: { calls: 8, estimated_brl: 0.32 } },
  remaining: { day: { calls: 18, estimated_brl: 4.92 }, month: { calls: 92, estimated_brl: 29.68 } },
};

describe("confirmação de custo antes do envio", () => {
  let requests: InternalAxiosRequestConfig[];
  let previousAdapter: typeof api.defaults.adapter;
  let quoteResult: MapsQuote;
  beforeEach(() => {
    requests = [];
    quoteResult = { ...quote };
    previousAdapter = api.defaults.adapter;
    const adapter: AxiosAdapter = async (config) => {
      requests.push(config);
      const data = config.url === "/google-maps-control/preview" ? quoteResult
        : config.url === "/google-maps-control/confirm" ? { token: `single-use-${requests.length}` } : { ok: true };
      return { config, data, status: 200, statusText: "OK", headers: new AxiosHeaders() };
    };
    api.defaults.adapter = adapter;
  });
  afterEach(() => {
    act(() => { mapsConfirmationStore.cancelAll(); mapsConfirmationStore.dismissNotice(); });
    api.defaults.adapter = previousAdapter;
  });

  it("geocodificação manual registrada no servidor despacha sem popup nem confirmação", async () => {
    quoteResult = { ...quote, required: false, blocked: false, confirmation_mode: "server_recorded", max_calls: 1 };
    render(<GoogleMapsActionGuard />);
    await api.post("/clinicas/geocode-endereco", { endereco: "Sintético" });
    expect(requests.map((item) => item.url)).toEqual(["/google-maps-control/preview", "/clinicas/geocode-endereco"]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(requests[1].headers.has("X-Google-Maps-Action")).toBe(false);
  });

  it("liberação temporária despacha a Agenda sem popup nem custo zero fictício", async () => {
    quoteResult = { ...quote, operation_mode: "temporary_open", required: false, blocked: false,
      max_calls: null, estimated_cost_min_brl: null, estimated_cost_max_brl: null };
    render(<GoogleMapsActionGuard />);
    await api.post("/agenda/sugestoes-horario", { clinica_id: 1 });
    expect(requests.map((item) => item.url)).toEqual(["/google-maps-control/preview", "/agenda/sugestoes-horario"]);
    expect(requests[1].headers.has("X-Google-Maps-Action")).toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
  });


  it("confirma Agenda acima da referência e mostra alerta sem bloquear o envio", async () => {
    quoteResult = { ...quote, budget_policy: "agenda_monitor", financial_limit_enforced: false, alerts: ["Referência diária atingida; Agenda liberada."] };
    render(<GoogleMapsActionGuard />);
    const result = api.post("/agenda", {});
    expect(await screen.findByRole("dialog")).toHaveTextContent("Agenda liberada com alertas");
    expect(screen.getByRole("dialog")).toHaveTextContent("Teto desta confirmação");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar esta ação" }));
    await result;
    expect(screen.getByRole("alert")).toHaveTextContent("Alerta de custo — Agenda liberada");
    expect(screen.getByRole("alert")).toHaveClass("bg-amber-50");
    expect(requests.filter((item) => item.url === "/agenda")).toHaveLength(1);
  });
  it("revisão vencida mostra data e alerta sem desabilitar a confirmação", async () => {
    quoteResult = { ...quote, budget_policy: "agenda_monitor", pricing_review_due: true, pricing_reference_valid_until: "2026-11-21T23:59:59-03:00", alerts: ["Revisão de preços/câmbio pendente: Agenda liberada."] };
    render(<GoogleMapsActionGuard />);
    const result = api.post("/agenda", {});
    expect(await screen.findByRole("dialog")).toHaveTextContent("Estimativa desatualizada — revisão pendente desde 21/11/2026");
    expect(screen.getByRole("button", { name: "Confirmar esta ação" })).toBeEnabled();
    expect(requests.filter((item) => item.url === "/agenda")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirmar esta ação" }));
    await result;
    expect(requests.filter((item) => item.url === "/agenda")).toHaveLength(1);
    expect(requests.filter((item) => item.url === "/google-maps-control/confirm")).toHaveLength(1);
  });

  it("georreferenciar tutor na Agenda pede consentimento limitado a uma unidade", async () => {
    quoteResult = { ...quote, budget_policy: "agenda_monitor", action: "Localizar endereço do tutor para agendamento", services: ["geocoding"], max_calls: 1, estimated_cost_max_brl: 0.06 };
    render(<GoogleMapsActionGuard />);
    const result = api.post("/agenda/geocode-endereco-tutor", { endereco: "Synthetic address" }).catch((error) => error);
    expect(await screen.findByRole("dialog")).toHaveTextContent("1 chamadas/unidades cobradas");
    expect(screen.getByRole("dialog")).toHaveTextContent("Geocoding");
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect((await result).code).toBe("ERR_CANCELED");
    expect(requests.map((item) => item.url)).toEqual(["/google-maps-control/preview"]);
  });

  it("cancelar não envia a ação nem pede um token", async () => {
    render(<GoogleMapsActionGuard />);
    const result = api.post("/agenda/sugestoes-horario", { clinica_id: 1 }).catch((error) => error);
    expect(await screen.findByRole("dialog")).toHaveTextContent("Buscar horários");
    expect(screen.getByText("4 chamadas/unidades cobradas")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect((await result).code).toBe("ERR_CANCELED");
    expect(requests.map((item) => item.url)).toEqual(["/google-maps-control/preview"]);
  });

  it("confirmar libera uma execução limitada; repetir exige outra confirmação", async () => {
    render(<GoogleMapsActionGuard />);
    const first = api.post("/agenda/sugestoes-horario", { clinica_id: 1 });
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar esta ação" }));
    await first;
    const sent = requests.find((item) => item.url === "/agenda/sugestoes-horario")!;
    expect(sent.headers.get("X-Google-Maps-Action")).toMatch(/^single-use-/);
    expect(requests.filter((item) => item.url === sent.url)).toHaveLength(1);
    const retry = api.request(sent).catch((error) => error);
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await retry;
    expect(requests.filter((item) => item.url === sent.url)).toHaveLength(1);
    expect(requests.filter((item) => item.url === "/google-maps-control/confirm")).toHaveLength(1);
  });

  it("ações simultâneas recebem confirmações separadas e não compartilham token", async () => {
    render(<GoogleMapsActionGuard />);
    const first = api.post("/agenda/sugestoes-horario", { clinica_id: 1 });
    const second = api.post("/agenda/sugestoes-horario", { clinica_id: 2 }).catch((error) => error);
    await waitFor(() => expect(mapsConfirmationStore.getSnapshot().queue).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar esta ação" }));
    await first;
    expect(screen.getByRole("dialog")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await second;
    expect(requests.filter((item) => item.url === "/agenda/sugestoes-horario")).toHaveLength(1);
    expect(requests.filter((item) => item.url === "/google-maps-control/confirm")).toHaveLength(1);
  });

  it("busca abortada remove o popup e não envia chamada paga", async () => {
    render(<GoogleMapsActionGuard />);
    const controller = new AbortController();
    const result = api.post("/agenda/sugestoes-horario", {}, { signal: controller.signal }).catch((error) => error);
    await screen.findByRole("dialog");
    act(() => controller.abort());
    await result;
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(requests).toHaveLength(1);
  });

  it("bloqueio fica visível na tela e nenhuma ação é despachada", async () => {
    quoteResult = { ...quote, blocked: true, reason: "month_limit", message: "Limite mensal atingido." };
    render(<GoogleMapsActionGuard />);
    await api.post("/agenda/sugestoes-horario", {}).catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("Limite mensal atingido.");
    expect(requests).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("mantém parâmetros repetidos e corpo exatos no orçamento da ação", async () => {
    quoteResult = { ...quote, required: false };
    await api.get("/logistica/deslocamento?clinica_ids=1&clinica_ids=2", { params: { perfil: "comercial" } });
    const preview = JSON.parse(requests[0].data);
    expect(preview).toEqual({ method: "GET", path: "/api/v1/logistica/deslocamento", query: "clinica_ids=1&clinica_ids=2&perfil=comercial", body: null });
  });

  it("suspende lote quando a verificação compartilhada está indisponível", async () => {
    const adapter = api.defaults.adapter as AxiosAdapter;
    api.defaults.adapter = async (config) => {
      if (config.url === "/google-maps-control/preview") throw new Error("Falha de rede");
      return adapter(config);
    };
    render(<GoogleMapsActionGuard />);
    await api.post("/logistica/recalcular", {}).catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível verificar o limite");
    expect(requests).toHaveLength(0);
  });

  it("não repete uma ação rejeitada pelo servidor após a confirmação", async () => {
    const adapter = api.defaults.adapter as AxiosAdapter;
    api.defaults.adapter = async (config) => {
      const response = await adapter(config);
      if (config.url === "/agenda") throw Object.assign(new Error("Bloqueado"), { response: { status: 409, data: { detail: { code: "GOOGLE_MAPS_COST_BLOCKED", message: "Limite diário atingido." } } } });
      return response;
    };
    render(<GoogleMapsActionGuard />);
    const result = api.post("/agenda", {}).catch((error) => error);
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar esta ação" }));
    await result;
    expect(await screen.findByRole("alert")).toHaveTextContent("Limite diário atingido.");
    expect(requests.filter((item) => item.url === "/agenda")).toHaveLength(1);
    expect(requests.filter((item) => item.url === "/google-maps-control/confirm")).toHaveLength(1);
  });

  it("consulta cache sem popup ou token de custo quando o servidor declara zero chamadas", async () => {
    quoteResult = { ...quote, operation_mode: "cache_only", required: false, max_calls: 0, estimated_cost_min_brl: 0, estimated_cost_max_brl: 0 };
    render(<GoogleMapsActionGuard />);
    await api.get("/logistica/deslocamento", { headers: { "X-Google-Maps-Action": "old-paid-token" } });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(requests.map((item) => item.url)).toEqual(["/google-maps-control/preview", "/logistica/deslocamento"]);
    expect(requests[1].headers.has("X-Google-Maps-Action")).toBe(false);
  });

  it("miss de cache mostra bloqueio e não tenta autorizar cobrança ou repetir a consulta", async () => {
    quoteResult = { ...quote, operation_mode: "cache_only", required: false, max_calls: 0, estimated_cost_min_brl: 0, estimated_cost_max_brl: 0 };
    const adapter = api.defaults.adapter as AxiosAdapter;
    api.defaults.adapter = async (config) => {
      const response = await adapter(config);
      if (config.url === "/logistica/deslocamento") throw Object.assign(new Error("Bloqueado"), { response: { status: 409, data: { detail: { code: "GOOGLE_MAPS_COST_BLOCKED", message: "Modo somente cache: não há rota válida disponível. Nenhuma chamada ao Google foi enviada." } } } });
      return response;
    };
    render(<GoogleMapsActionGuard />);
    await api.get("/logistica/deslocamento").catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("não há rota válida disponível");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(requests.map((item) => item.url)).toEqual(["/google-maps-control/preview", "/logistica/deslocamento"]);
  });
});
