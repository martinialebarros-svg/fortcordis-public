import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GoogleMapsAdminPanel from "./GoogleMapsAdminPanel";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: mocks }));

const existing = {
  configured: true, enabled: true, revision: 7,
  config: {
    enabled: true,
    limits: { action: { calls: 10, estimated_brl: "1" }, day: { calls: 100, estimated_brl: "10" }, month: { calls: 500, estimated_brl: "50" } },
    prices_usd: { routes_essentials: "0.005", routes_pro: "0.01", distance_matrix_essentials: "0.005", distance_matrix_pro: "0.01", geocoding: "0.005" },
    fx_brl_per_usd_upper: "6", price_multiplier: "1.2", pricing_valid_until: "2026-11-01T03:00:00Z",
    action_call_caps: { clinic_geocode: 1 }, automatic_policies: {},
    opening_usage: { day: { calls: 3, estimated_brl: "0.5" }, month: { calls: 20, estimated_brl: "4" } },
    opening_usage_as_of: "2026-10-18", opening_usage_basis: "synthetic_stage",
  },
  history: [{ id: 1, action: "agenda_search", kind: "blocked", created_at: "2026-10-18T15:00:00Z", reason: "day_limit", message: "Limite diário atingido.", calls: 0, estimated_brl: 0 }],
};

describe("administração de custos Google Maps", () => {
  it("informa liberação temporária sem mostrar saldo fictício ou formulário ineficaz", async () => {
    mocks.get.mockResolvedValue({ data: { operation_mode: "temporary_open", configured: false, config: null, revision: 0, blocked: false, limits: null, consumption: null, remaining: null } });
    render(<GoogleMapsAdminPanel />);
    expect(await screen.findByText("Liberação temporária ativa")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Pode haver cobrança");
    expect(screen.queryByRole("button", { name: "Salvar controles" })).toBeNull();
    expect(screen.queryByText(/Chamadas pagas suspensas/)).toBeNull();
    expect(screen.queryByLabelText("Modo de operação")).toBeNull();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  beforeEach(() => { mocks.get.mockReset(); mocks.put.mockReset(); });

  it("começa com limites vazios e chamadas suspensas; não presume um teto", async () => {
    mocks.get.mockResolvedValue({ data: { configured: false, revision: 0, config: null } });
    render(<GoogleMapsAdminPanel />);
    await screen.findByText(/Chamadas pagas suspensas/);
    expect(screen.getByRole("checkbox", { name: /Habilitar chamadas/ })).not.toBeChecked();
    expect(screen.getByLabelText("Máximo estimado em R$ — por mês")).toHaveValue(null);
    expect(screen.getByLabelText("Máximo de chamadas — por mês")).toHaveValue(null);
    fireEvent.submit(screen.getByRole("button", { name: "Salvar controles" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nenhum teto será presumido");
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("preserva a exceção manual sem modificar os limites ou liberar automações", async () => {
    mocks.get.mockResolvedValue({ data: { ...existing, config: { ...existing.config, clinic_geocode_manual_enabled: true } } });
    mocks.put.mockResolvedValue({ data: {} });
    render(<GoogleMapsAdminPanel />);
    expect(await screen.findByText(/Geocodificação manual de clínicas: uma chamada/)).toBeVisible();
    fireEvent.submit(screen.getByRole("button", { name: "Salvar controles" }).closest("form")!);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/google-maps-control/config", expect.objectContaining({
      clinic_geocode_manual_enabled: true, action_call_caps: { clinic_geocode: 1 }, automatic_policies: {},
      limits: expect.objectContaining({ day: { calls: 100, estimated_brl: 10 }, month: { calls: 500, estimated_brl: 50 } }),
    })));
  });

  it("preserva a revisão e o consumo inicial e salva apenas valores explícitos", async () => {
    mocks.get.mockResolvedValue({ data: existing });
    mocks.put.mockResolvedValue({ data: existing });
    render(<GoogleMapsAdminPanel />);
    await screen.findByText(/Chamadas habilitadas/);
    expect(screen.getByText(/Limite diário atingido/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Máximo estimado em R$ — por mês"), { target: { value: "42" } });
    fireEvent.submit(screen.getByRole("button", { name: "Salvar controles" }).closest("form")!);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/google-maps-control/config", expect.objectContaining({
      expected_revision: 7, enabled: true, action_call_caps: { clinic_geocode: 1 }, automatic_policies: {},
      opening_usage: existing.config.opening_usage,
      limits: expect.objectContaining({ month: { calls: 500, estimated_brl: 42 } }),
    })));
  });


  it("salva monitoramento explícito e mostra referências sem alterar valores", async () => {
    mocks.get.mockResolvedValue({ data: { ...existing, agenda_budget_mode: "monitor", config: { ...existing.config, agenda_budget_mode: "monitor" }, alerts: ["Referência atingida; Agenda liberada."] } });
    mocks.put.mockResolvedValue({ data: {} });
    render(<GoogleMapsAdminPanel />);
    expect(await screen.findByText("Agenda liberada com alertas; lotes e extras sob teto rígido")).toBeVisible();
    expect(screen.getByLabelText("Ao atingir o orçamento da Agenda")).toHaveValue("monitor");
    fireEvent.submit(screen.getByRole("button", { name: "Salvar controles" }).closest("form")!);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/google-maps-control/config", expect.objectContaining({ agenda_budget_mode: "monitor", limits: expect.objectContaining({ month: { calls: 500, estimated_brl: 50 } }) })));
  });

  it("mostra registro interno sem prometer popup quando a política vem do servidor", async () => {
    mocks.get.mockResolvedValue({ data: { ...existing, agenda_budget_mode: "monitor", agenda_confirmation_required: false,
      config: { ...existing.config, agenda_budget_mode: "monitor" },
      history: [{ ...existing.history[0], kind: "internal_authorized", reason: "agenda_internal_record", message: "Execução registrada com limite próprio." }] } });
    render(<GoogleMapsAdminPanel />);
    expect(await screen.findByText(/Custos registrados internamente, sem popup na Agenda/)).toBeVisible();
    expect(screen.getByText(/Registro interno — execução limitada/)).toBeVisible();
    expect(mocks.put).not.toHaveBeenCalled();
  });
  it("opt-in automático exige limites próprios e não copia os globais", async () => {
    mocks.get.mockResolvedValue({ data: existing });
    render(<GoogleMapsAdminPanel />);
    await screen.findByText(/Chamadas habilitadas/);
    fireEvent.click(screen.getByRole("checkbox", { name: /Autorizar consultas automáticas/ }));
    expect(screen.getByLabelText("Chamadas automáticas — por mês")).toHaveValue(null);
    fireEvent.submit(screen.getByRole("button", { name: "Salvar controles" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nenhum teto será presumido");
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("salva cache-only com limites zero, sem preços, câmbio ou consumo inicial fictícios", async () => {
    mocks.get.mockResolvedValue({ data: { configured: false, revision: 0, config: null } });
    mocks.put.mockResolvedValue({ data: {} });
    render(<GoogleMapsAdminPanel />);
    await screen.findByLabelText("Modo de operação");
    fireEvent.change(screen.getByLabelText("Modo de operação"), { target: { value: "cache_only" } });
    expect(screen.getByText(/Rotas já armazenadas e ainda válidas/)).toBeVisible();
    expect(screen.getByText(/Não presume saldo de franquia gratuita/)).toBeVisible();
    expect(screen.queryByLabelText("Câmbio máximo — R$ por USD")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /Habilitar chamadas/ })).toBeNull();
    fireEvent.submit(screen.getByRole("button", { name: "Salvar controles" }).closest("form")!);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/google-maps-control/config", {
      operation_mode: "cache_only", enabled: true, expected_revision: 0,
      limits: { action: { calls: 0, estimated_brl: 0 }, day: { calls: 0, estimated_brl: 0 }, month: { calls: 0, estimated_brl: 0 } },
    }));
  });

  it("alternar para cache não reescreve o consumo inicial já registrado no servidor", async () => {
    mocks.get.mockResolvedValue({ data: existing });
    mocks.put.mockResolvedValue({ data: {} });
    render(<GoogleMapsAdminPanel />);
    await screen.findByLabelText("Modo de operação");
    fireEvent.change(screen.getByLabelText("Modo de operação"), { target: { value: "cache_only" } });
    fireEvent.submit(screen.getByRole("button", { name: "Salvar controles" }).closest("form")!);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/google-maps-control/config", expect.objectContaining({
      operation_mode: "cache_only", expected_revision: 7,
    })));
    const payload = mocks.put.mock.calls[0][1];
    expect(payload).not.toHaveProperty("prices_usd");
    expect(payload).not.toHaveProperty("fx_brl_per_usd_upper");
    expect(payload).not.toHaveProperty("opening_usage");
    expect(payload).not.toHaveProperty("opening_usage_as_of");
    expect(payload).not.toHaveProperty("opening_usage_basis");
  });

  it("exibe histórico anterior no cache e exige nova escolha explícita para modo pago", async () => {
    mocks.get.mockResolvedValue({ data: {
      configured: true, enabled: true, revision: 8, blocked: false,
      config: { operation_mode: "cache_only", enabled: true, limits: { action: { calls: 0, estimated_brl: 0 }, day: { calls: 0, estimated_brl: 0 }, month: { calls: 0, estimated_brl: 0 } } },
      consumption: { day: { calls: 3, estimated_brl: 0.5 }, month: { calls: 20, estimated_brl: 4 } },
      history: existing.history,
    } });
    render(<GoogleMapsAdminPanel />);
    await screen.findByText(/Novas chamadas ao Google estão bloqueadas/);
    expect(screen.getByText(/20 chamadas/)).toBeVisible();
    expect(screen.getByText(/Limite diário atingido/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Modo de operação"), { target: { value: "paid_budget" } });
    expect(screen.getByLabelText("Máximo de chamadas — por mês")).toHaveValue(null);
    expect(screen.getByLabelText("Máximo estimado em R$ — por mês")).toHaveValue(null);
    expect(screen.getByRole("checkbox", { name: /Habilitar chamadas/ })).not.toBeChecked();
    fireEvent.submit(screen.getByRole("button", { name: "Salvar controles" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nenhum teto será presumido");
    expect(mocks.put).not.toHaveBeenCalled();
  });
});

it("mostra revisão vencida como alerta mantendo a Agenda habilitada", async () => {
  mocks.get.mockReset(); mocks.put.mockReset();
  mocks.get.mockResolvedValue({ data: { ...existing, blocked: false, agenda_budget_mode: "monitor", config: { ...existing.config, agenda_budget_mode: "monitor" }, alerts: ["Revisão de preços/câmbio pendente: a Agenda continua liberada com a última estimativa cadastrada."] } });
  render(<GoogleMapsAdminPanel />);
  expect(await screen.findByText(/Revisão de preços\/câmbio pendente/)).toBeVisible();
  expect(screen.getByText(/Chamadas habilitadas sob limites/)).toBeVisible();
  expect(screen.queryByText(/Chamadas pagas suspensas:/)).toBeNull();
  expect(mocks.put).not.toHaveBeenCalled();
});
