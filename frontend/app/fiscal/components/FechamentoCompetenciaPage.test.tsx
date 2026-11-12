import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FiscalPrevia, FiscalServico } from "@/lib/fiscal-fechamento";
import FechamentoCompetenciaPage from "./FechamentoCompetenciaPage";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: mocks }));
vi.mock("@/lib/calendar-date", () => ({
  operationalTodayDateInput: () => "2026-10-14",
  formatCalendarDate: (value: string | null) => value ? value.slice(0, 10).split("-").reverse().join("/") : "—",
}));

function servico(overrides: Partial<FiscalServico> = {}): FiscalServico {
  return {
    os_id: 1, numero_os: "OS-001", data_atendimento: "2026-10-02T09:00:00", data_prestacao: "2026-10-02",
    competencia: "2026-10", valor_final: 250, status_os: "Pendente", tipo_cliente: "PJ", cliente_nome: "Clínica Alfa",
    cliente_documento: "12345678000195", clinica_id: 10, clinica_nome: "Clínica Alfa", servico_nome: "Serviço veterinário",
    elegivel: true, motivos_pendencia: [], fechamento_id: null, exportacoes_anteriores: 0, ...overrides,
  };
}

function previa(items: FiscalServico[] = [servico()], competencia = "2026-10"): FiscalPrevia {
  return {
    competencia, data_inicio: `${competencia}-01`, data_fim: `${competencia}-31`, items,
    resumo: { quantidade_os: items.length, quantidade_aptas: items.filter((item) => item.elegivel).length,
      quantidade_pendentes: 1, quantidade_canceladas: 1, quantidade_ja_preparadas: 1,
      quantidade_exportadas_anteriormente: 0, valor_total: 1000, valor_apto: 250 },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

const pacoteResponse = () => ({ data: new Blob(["zip"]), headers: { "x-fechamento-id": "42", "content-disposition": 'attachment; filename="FortCordis_2026-10.zip"' } });

describe("FechamentoCompetenciaPage", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.get.mockImplementation(async (url: string) => url === "/fiscal/fechamentos/previa"
      ? { data: previa() } : { data: { items: [], total: 0 } });
    mocks.post.mockResolvedValue(pacoteResponse());
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("usa competência obrigatória e impede canceladas, pendentes de cadastro e já preparadas na seleção", async () => {
    const items = [servico(),
      servico({ os_id: 2, numero_os: "OS-002", status_os: "Cancelado", elegivel: false, motivos_pendencia: ["OS cancelada"] }),
      servico({ os_id: 3, numero_os: "OS-003", elegivel: false, motivos_pendencia: ["CNPJ pendente"] }),
      servico({ os_id: 4, numero_os: "OS-004", elegivel: false, fechamento_id: 12, motivos_pendencia: ["Já preparada"] }),
    ];
    mocks.get.mockImplementation(async (url: string) => url.endsWith("previa") ? { data: previa(items) } : { data: { items: [] } });
    render(<FechamentoCompetenciaPage />);
    expect(await screen.findByText("OS-001")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/fiscal/fechamentos/previa", expect.objectContaining({ params: { competencia: "2026-10" } }));
    expect(screen.getByRole("checkbox", { name: "Selecionar OS OS-001" })).toBeChecked();
    for (const id of ["OS-002", "OS-003", "OS-004"]) {
      expect(screen.getByRole("checkbox", { name: `Selecionar OS ${id}` })).toBeDisabled();
      expect(screen.getByRole("checkbox", { name: `Selecionar OS ${id}` })).not.toBeChecked();
    }
    const submit = screen.getByRole("button", { name: "Preparar e baixar pacote" });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi que as datas/i }));
    fireEvent.click(submit);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][1]).toEqual({ competencia: "2026-10", os_ids: [1], chave_idempotencia: expect.any(String), confirmar_datas_prestacao: true, confirmar_exportacoes_anteriores: false });
    expect(await screen.findByText(/Pacote #42 preparado/)).toBeInTheDocument();
  });

  it("ignora resposta atrasada de outro mês e limpa a seleção antes da nova prévia", async () => {
    const outubro = deferred<{ data: FiscalPrevia }>();
    const agosto = deferred<{ data: FiscalPrevia }>();
    mocks.get.mockImplementation((url: string, config?: { params?: { competencia: string } }) => {
      if (url.endsWith("previa")) return config?.params?.competencia === "2026-10" ? outubro.promise : agosto.promise;
      return Promise.resolve({ data: { items: [] } });
    });
    render(<FechamentoCompetenciaPage />);
    fireEvent.change(screen.getByLabelText("Competência"), { target: { value: "2026-08" } });
    await act(async () => {
      agosto.resolve({ data: previa([servico({ os_id: 8, numero_os: "OS-AGO", competencia: "2026-08", data_prestacao: "2026-08-31" })], "2026-08") });
    });
    expect(await screen.findByText("OS-AGO")).toBeInTheDocument();
    await act(async () => { outubro.resolve({ data: previa() }); });
    expect(screen.queryByText("OS-001")).not.toBeInTheDocument();
    expect(screen.getByText("31/08/2026")).toBeInTheDocument();
    expect(mocks.get.mock.calls.find((call) => call[1]?.params?.competencia === "2026-10")?.[1].signal.aborted).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi que as datas/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote" }));
    await waitFor(() => expect(mocks.post.mock.calls[0][1]).toMatchObject({ competencia: "2026-08", os_ids: [8] }));
  });

  it("mantém a chave e a seleção no retry e impede preparação concorrente", async () => {
    const retry = deferred<ReturnType<typeof pacoteResponse>>();
    mocks.post.mockRejectedValueOnce(new Error("Rede indisponível")).mockImplementationOnce(() => retry.promise);
    render(<FechamentoCompetenciaPage />);
    await screen.findByText("OS-001");
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi que as datas/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote" }));
    expect(await screen.findByText("Rede indisponível")).toBeInTheDocument();
    const firstBody = mocks.post.mock.calls[0][1];
    expect(screen.getByRole("checkbox", { name: "Selecionar OS OS-001" })).toBeChecked();
    const submit = screen.getByRole("button", { name: "Preparar e baixar pacote" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(mocks.post.mock.calls[1][1].chave_idempotencia).toBe(firstBody.chave_idempotencia);
    expect(screen.getByLabelText("Competência")).toBeDisabled();
    await act(async () => { retry.resolve(pacoteResponse()); });
  });

  it("gera outra chave quando o conteúdo selecionado muda", async () => {
    mocks.get.mockImplementation(async (url: string) => url.endsWith("previa") ? { data: previa([servico(), servico({ os_id: 5, numero_os: "OS-005" })]) } : { data: { items: [] } });
    mocks.post.mockRejectedValue(new Error("Sem conexão"));
    render(<FechamentoCompetenciaPage />);
    await screen.findByText("OS-005");
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi que as datas/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote" }));
    await screen.findByText("Sem conexão");
    const firstKey = mocks.post.mock.calls[0][1].chave_idempotencia;
    fireEvent.click(screen.getByRole("checkbox", { name: "Selecionar OS OS-005" }));
    expect(screen.getByRole("checkbox", { name: /conferi que as datas/i })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi que as datas/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1].chave_idempotencia).not.toBe(firstKey);
    expect(mocks.post.mock.calls[1][1].os_ids).toEqual([1]);
  });

  it("exige reconhecimento explícito de exportações anteriores e oferece segunda via em conflito", async () => {
    mocks.get.mockImplementation(async (url: string) => url.endsWith("previa") ? { data: previa([servico({ exportacoes_anteriores: 2 })]) } : url.endsWith("download") ? { data: new Blob(["zip"]), headers: {} } : { data: { items: [] } });
    mocks.post.mockRejectedValue({ response: { status: 409, data: { detail: { message: "OS já pertence a outro pacote.", fechamento_id: 77 } } } });
    render(<FechamentoCompetenciaPage />);
    await screen.findByText("OS-001");
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi que as datas/i }));
    expect(screen.getByRole("button", { name: "Preparar e baixar pacote" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi as exportações anteriores/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote" }));
    expect(await screen.findByText("OS já pertence a outro pacote.")).toBeInTheDocument();
    expect(mocks.post.mock.calls[0][1].confirmar_exportacoes_anteriores).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Baixar pacote anterior #77" }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/fiscal/fechamentos/77/download", { responseType: "blob" }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it("distingue falha de histórico de lista vazia e baixa segunda via sem preparar outro pacote", async () => {
    let historyFailed = false;
    mocks.get.mockImplementation(async (url: string) => {
      if (url.endsWith("previa")) return { data: previa() };
      if (url.endsWith("download")) return { data: new Blob(["zip"]), headers: {} };
      if (!historyFailed) { historyFailed = true; throw new Error("Histórico indisponível"); }
      return { data: { items: [{ id: 8, competencia: "2026-08", quantidade_os: 1, valor_total: 250, preparado_em: "2026-10-14T16:20:00", usuario_nome: "Usuário", arquivo_nome: "FortCordis_2026-08.zip" }] } };
    });
    render(<FechamentoCompetenciaPage />);
    expect(await screen.findByText("Histórico indisponível")).toBeInTheDocument();
    expect(screen.queryByText("Nenhum pacote preparado ainda.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tentar consultar histórico novamente" }));
    fireEvent.click(await screen.findByRole("button", { name: "Baixar segunda via #8" }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/fiscal/fechamentos/8/download", { responseType: "blob" }));
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
