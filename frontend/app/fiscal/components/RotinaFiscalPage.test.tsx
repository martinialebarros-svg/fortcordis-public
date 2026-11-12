import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FiscalAndamento, FiscalPreviaRotina, FiscalRotinas, FiscalServicoRotina, ModoFiscalRotina } from "@/lib/fiscal-rotina";
import RotinaFiscalPage from "./RotinaFiscalPage";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: api }));
vi.mock("@/lib/calendar-date", () => ({ operationalTodayDateInput: () => "2026-10-14", formatCalendarDate: (value: string | null) => value ? value.slice(0, 10).split("-").reverse().join("/") : "—" }));

function servico(changes: Partial<FiscalServicoRotina> = {}): FiscalServicoRotina {
  return { os_id: 1, numero_os: "OS-001", data_atendimento: "2026-10-14T09:00:00-03:00", data_prestacao: "2026-10-14", competencia: "2026-10", valor_final: 250, status_os: "Pendente", tipo_cliente: "PJ", cliente_nome: "Clínica Alfa", cliente_documento: "12345678000195", clinica_id: 10, clinica_nome: "Clínica Alfa", servico_nome: "Serviço veterinário", elegivel: true, motivos_pendencia: [], fechamento_id: null, exportacoes_anteriores: 0, modo_preparacao: "semanal", pagamento_depende_nf: false, realizacao_confirmada: true, fonte_realizacao: "agenda", prazo_preparacao: "2026-10-18T17:00:00-03:00", ...changes };
}
function previa(modo: ModoFiscalRotina = "semanal", items = [servico()], competencia = "2026-10"): FiscalPreviaRotina {
  return { competencia, data_inicio: `${competencia}-01`, data_fim: `${competencia}-31`, items, rotina: { modo, data_corte: modo === "semanal" ? "2026-10-18" : null, corte_em: modo === "semanal" ? "2026-10-18T17:00:00-03:00" : null, proxima_preparacao_em: modo === "semanal" ? "2026-10-18T17:00:00-03:00" : null, horario: "17:00", timezone: "America/Fortaleza", automatico: false }, resumo: { quantidade_os: items.length, quantidade_aptas: items.filter((item) => item.elegivel).length, quantidade_pendentes: items.filter((item) => !item.elegivel).length, quantidade_canceladas: 0, quantidade_ja_preparadas: 0, quantidade_exportadas_anteriormente: 0, valor_total: 250, valor_apto: 250, quantidade_por_servico: items.filter((item) => item.modo_preparacao === "por_servico").length, quantidade_pagamento_depende_nf: items.filter((item) => item.pagamento_depende_nf).length } };
}
const configuracao = (): FiscalRotinas => ({ padrao: { modo: "semanal", dia_semana: "domingo", horario: "17:00", timezone: "America/Fortaleza", automatico: false }, clinicas: [{ clinica_id: 10, nome: "Clínica Alfa", modo: "semanal", pagamento_depende_nf: false, versao: 0, origem: "padrao" }, { clinica_id: 20, nome: "Parceiro com prioridade", modo: "por_servico", pagamento_depende_nf: true, versao: 3, origem: "vet_fauna" }] });
const pacote = { id: 7, competencia: "2026-10", quantidade_os: 2, valor_total: 500, arquivo_nome: "contador.zip", usuario_nome: "Equipe", preparado_em: "2026-10-14T10:00:00-03:00" };
const andamento = (changes: Partial<FiscalAndamento> = {}): FiscalAndamento => ({ os_id: 1, numero_os: "OS-001", cliente_nome: "Clínica Alfa", clinica_nome: "Clínica Alfa", etapa: "preparado", versao: 0, referencia_nota: null, atualizado_em: null, eventos: [], ...changes });
const zipResponse = () => ({ data: new Blob(["zip"]), headers: { "x-fechamento-id": "7", "content-disposition": 'attachment; filename="contador.zip"' } });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }
type Config = { params?: { modo?: ModoFiscalRotina; competencia?: string; data_corte?: string; clinica_id?: number; skip?: number; limit?: number }; signal?: AbortSignal };
function defaultGet(url: string, config?: Config): Promise<unknown> {
  if (url === "/fiscal/rotinas") return Promise.resolve({ data: configuracao() });
  if (url.endsWith("previa")) {
    const data = previa(config?.params?.modo, undefined, config?.params?.competencia);
    if (config?.params?.data_corte) {
      data.rotina.data_corte = config.params.data_corte;
      data.rotina.corte_em = `${config.params.data_corte}T17:00:00-03:00`;
    }
    return Promise.resolve({ data });
  }
  if (url.endsWith("andamentos")) return Promise.resolve({ data: { fechamento_id: 7, items: [andamento()] } });
  if (url.endsWith("download")) return Promise.resolve(zipResponse());
  return Promise.resolve({ data: { items: [pacote], total: 1 } });
}

describe("RotinaFiscalPage", () => {
  beforeEach(() => {
    api.get.mockReset(); api.post.mockReset(); api.put.mockReset();
    api.get.mockImplementation(defaultGet); api.post.mockResolvedValue(zipResponse());
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("inicia semanal no mês atual e prepara somente OS aptas após conferência explícita", async () => {
    api.get.mockImplementation((url: string, config?: Config) => url.endsWith("previa") ? Promise.resolve({ data: previa("semanal", [servico(), servico({ os_id: 2, numero_os: "OS-002", status_os: "Cancelado", elegivel: false, motivos_pendencia: ["OS cancelada"] }), servico({ os_id: 3, numero_os: "OS-003", realizacao_confirmada: false, elegivel: false, motivos_pendencia: ["Realização não confirmada"] })]) }) : defaultGet(url, config));
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    expect(screen.getByRole("button", { name: "Semana" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Competência dos serviços")).toHaveValue("2026-10");
    expect(screen.getByLabelText("Domingo de corte · 17h")).toHaveValue("2026-10-18");
    expect(api.get).toHaveBeenCalledWith("/fiscal/rotinas/previa", expect.objectContaining({ params: { competencia: "2026-10", modo: "semanal" } }));
    expect(screen.getByRole("checkbox", { name: "Selecionar OS OS-002" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Selecionar OS OS-003" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Preparar e baixar pacote semanal" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi as datas de prestação/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote semanal" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0]).toEqual(["/fiscal/rotinas/preparar", { competencia: "2026-10", modo: "semanal", os_ids: [1], data_corte: "2026-10-18", chave_idempotencia: expect.any(String), confirmar_datas_prestacao: true, confirmar_exportacoes_anteriores: false }, { responseType: "blob" }]);
    expect(await screen.findByText(/Pacote #7 preparado/)).toBeInTheDocument();
    expect(api.post.mock.calls.every(([url]) => !/notas-fiscais|whatsapp/.test(url))).toBe(true);
  });

  it("por serviço usa radio com exatamente uma OS, mostra dependência de NF e omite corte semanal", async () => {
    api.get.mockImplementation((url: string, config?: Config) => url.endsWith("previa") ? Promise.resolve({ data: previa(config?.params?.modo, [servico({ modo_preparacao: "por_servico", pagamento_depende_nf: true, clinica_id: 20 }), servico({ os_id: 2, numero_os: "OS-002", modo_preparacao: "por_servico", clinica_id: 20 })]) }) : defaultGet(url, config));
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    fireEvent.click(screen.getByRole("button", { name: "Por serviço · prioritário" }));
    const second = await screen.findByRole("radio", { name: "Selecionar OS OS-002" });
    fireEvent.click(second);
    expect(screen.getByRole("radio", { name: "Selecionar OS OS-001" })).not.toBeChecked();
    expect(second).toBeChecked();
    expect(screen.getByText("Pagamento depende da NF", { selector: "span.font-semibold" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi as datas de prestação/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote desta OS" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toMatchObject({ modo: "por_servico", os_ids: [2], clinica_id: 20 });
    expect(api.post.mock.calls[0][1]).not.toHaveProperty("data_corte");
    const request = api.get.mock.calls.find(([url, config]) => url.endsWith("previa") && config.params.modo === "por_servico");
    expect(request?.[1].params).not.toHaveProperty("data_corte");
  });

  it("conferência mensal consulta o mês sem seleção ou botão de preparação", async () => {
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    fireEvent.click(screen.getByRole("button", { name: "Conferência mensal" }));
    await screen.findByText("Conferência sem preparação");
    expect(screen.queryByRole("checkbox", { name: /Selecionar OS/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Preparar e baixar/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Configurar clínica")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Ver andamento das OS #7" }));
    const row = await screen.findByRole("article", { name: "Andamento da OS OS-001" });
    expect(within(row).getByRole("checkbox", { name: /Confirmo que enviei/ })).toBeDisabled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("rejeita corte que não seja domingo e ignora prévia atrasada de outro contexto", async () => {
    const old = deferred<unknown>();
    api.get.mockImplementation((url: string, config?: Config) => url.endsWith("previa") && config?.params?.modo === "semanal" ? old.promise : defaultGet(url, config));
    render(<RotinaFiscalPage />);
    fireEvent.click(screen.getByRole("button", { name: "Por serviço · prioritário" }));
    await screen.findByRole("radio", { name: "Selecionar OS OS-001" });
    await act(async () => { old.resolve({ data: previa("semanal", [servico({ numero_os: "OS-ANTIGA" })]) }); });
    expect(screen.queryByText("OS-ANTIGA")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Semana" }));
    await screen.findByText("OS-ANTIGA");
    const count = api.get.mock.calls.filter(([url]) => url.endsWith("previa")).length;
    fireEvent.change(screen.getByLabelText("Domingo de corte · 17h"), { target: { value: "2026-10-15" } });
    expect(await screen.findByText(/Escolha um domingo/)).toBeInTheDocument();
    expect(api.get.mock.calls.filter(([url]) => url.endsWith("previa"))).toHaveLength(count);
  });

  it("mostra e envia o corte conferido, mesmo que a próxima referência seja outro domingo", async () => {
    api.get.mockImplementation((url: string, config?: Config) => {
      if (!url.endsWith("previa")) return defaultGet(url, config);
      const data = previa();
      data.rotina.proxima_preparacao_em = "2026-10-25T17:00:00-03:00";
      return Promise.resolve({ data });
    });
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    expect(screen.getByText(/Corte deste pacote:/)).toHaveTextContent("18/10/2026, 17:00");
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi as datas de prestação/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote semanal" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1].data_corte).toBe("2026-10-18");
  });

  it("bloqueia preparação se a API devolver corte diferente do domingo escolhido", async () => {
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    api.get.mockImplementation((url: string, config?: Config) => url.endsWith("previa") ? Promise.resolve({ data: previa() }) : defaultGet(url, config));
    fireEvent.change(screen.getByLabelText("Domingo de corte · 17h"), { target: { value: "2026-10-25" } });
    await screen.findByText(/não corresponde ao domingo de corte escolhido/);
    expect(screen.queryByRole("button", { name: "Preparar e baixar pacote semanal" })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("retry conserva UUID, mas trocar corte muda a operação e exige nova conferência", async () => {
    api.post.mockRejectedValue(new Error("Rede indisponível"));
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi as datas de prestação/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote semanal" }));
    fireEvent.click(screen.getByRole("button", { name: /Preparar e baixar pacote semanal|Preparando pacote/ }));
    await screen.findByText("Rede indisponível");
    expect(api.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote semanal" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    expect(api.post.mock.calls[1][1].chave_idempotencia).toBe(api.post.mock.calls[0][1].chave_idempotencia);
    fireEvent.change(screen.getByLabelText("Domingo de corte · 17h"), { target: { value: "2026-10-25" } });
    await screen.findByText("OS-001");
    expect(screen.getByRole("checkbox", { name: /conferi as datas de prestação/i })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: /conferi as datas de prestação/i }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar e baixar pacote semanal" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(3));
    expect(api.post.mock.calls[2][1].chave_idempotencia).not.toBe(api.post.mock.calls[1][1].chave_idempotencia);
    expect(api.post.mock.calls[2][1].data_corte).toBe("2026-10-25");
  });

  it("preferência usa origem da API e só salva explicitamente com versão esperada", async () => {
    api.put.mockResolvedValue({ data: { ...configuracao().clinicas[1], modo: "semanal", pagamento_depende_nf: false, versao: 4, origem: "personalizada" } });
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    fireEvent.change(screen.getByLabelText("Configurar clínica"), { target: { value: "20" } });
    expect(screen.getByText(/Preferência inicial da Vet Fauna/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Preparação das informações"), { target: { value: "semanal" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /O pagamento desta clínica depende/ }));
    expect(api.put).not.toHaveBeenCalled();
    const count = api.get.mock.calls.filter(([url]) => url.endsWith("previa")).length;
    fireEvent.click(screen.getByRole("button", { name: "Salvar preferência" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/fiscal/rotinas/clinicas/20", { modo: "semanal", pagamento_depende_nf: false, versao_esperada: 3 }));
    expect(await screen.findByText("Preferência salva. A prévia foi atualizada.")).toBeInTheDocument();
    expect(api.get.mock.calls.filter(([url]) => url.endsWith("previa")).length).toBeGreaterThan(count);
  });

  it("conflito de preferência exige atualização e não sobrescreve outra versão", async () => {
    api.put.mockRejectedValue({ response: { status: 409, data: { detail: { message: "Preferência alterada por outra pessoa.", versao_atual: 4 } } } });
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    fireEvent.change(screen.getByLabelText("Configurar clínica"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar preferência" }));
    await screen.findByText("Preferência alterada por outra pessoa.");
    expect(screen.getByRole("button", { name: "Salvar preferência" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Atualizar preferências antes de tentar novamente" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Salvar preferência" })).toBeEnabled());
    expect(api.put).toHaveBeenCalledTimes(1);
  });

  it("pacote multiclínica registra apenas a OS confirmada e conserva UUID no retry do andamento", async () => {
    api.get.mockImplementation((url: string, config?: Config) => url.endsWith("andamentos") ? Promise.resolve({ data: { fechamento_id: 7, items: [andamento(), andamento({ os_id: 2, numero_os: "OS-002", cliente_nome: "Clínica Beta" })] } }) : defaultGet(url, config));
    api.post.mockRejectedValueOnce(new Error("Falha no registro")).mockResolvedValueOnce({ data: andamento({ etapa: "enviado_contador", versao: 1 }) });
    render(<RotinaFiscalPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver andamento das OS #7" }));
    const first = await screen.findByRole("article", { name: "Andamento da OS OS-001" });
    const second = screen.getByRole("article", { name: "Andamento da OS OS-002" });
    expect(within(first).getByRole("button", { name: "Registrar envio ao contador" })).toBeDisabled();
    fireEvent.click(within(first).getByRole("checkbox", { name: /Confirmo que enviei/ }));
    fireEvent.click(within(first).getByRole("button", { name: "Registrar envio ao contador" }));
    fireEvent.click(within(first).getByRole("button", { name: /Registrar envio ao contador|Registrando/ }));
    await screen.findByText("Falha no registro");
    expect(api.post).toHaveBeenCalledTimes(1);
    fireEvent.click(within(first).getByRole("button", { name: "Registrar envio ao contador" }));
    await waitFor(() => expect(within(first).getByText("Informações enviadas ao contador")).toBeInTheDocument());
    expect(api.post.mock.calls[0][0]).toBe("/fiscal/os/1/andamento");
    expect(api.post.mock.calls[0][1]).toMatchObject({ destino: "enviado_contador", versao_esperada: 0, confirmar_acao_manual: true });
    expect(api.post.mock.calls[1][1].chave_idempotencia).toBe(api.post.mock.calls[0][1].chave_idempotencia);
    expect(within(second).getByText("Informações preparadas")).toBeInTheDocument();
    expect(api.post.mock.calls.some(([url]) => url === "/fiscal/os/2/andamento")).toBe(false);
  });

  it("registrar nota exige referência, confirmação manual e preserva a etapa seguinte para outra ação", async () => {
    api.get.mockImplementation((url: string, config?: Config) => url.endsWith("andamentos") ? Promise.resolve({ data: { fechamento_id: 7, items: [andamento({ etapa: "enviado_contador", versao: 1 })] } }) : defaultGet(url, config));
    api.post.mockResolvedValue({ data: andamento({ etapa: "nota_recebida", versao: 2, referencia_nota: "NF 123" }) });
    render(<RotinaFiscalPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver andamento das OS #7" }));
    const row = await screen.findByRole("article", { name: "Andamento da OS OS-001" });
    fireEvent.click(within(row).getByRole("checkbox", { name: /Confirmo que recebi/ }));
    expect(within(row).getByRole("button", { name: "Registrar nota recebida" })).toBeDisabled();
    fireEvent.change(within(row).getByLabelText("Número ou referência da nota *"), { target: { value: "NF 123" } });
    fireEvent.click(within(row).getByRole("checkbox", { name: /Confirmo que recebi/ }));
    fireEvent.click(within(row).getByRole("button", { name: "Registrar nota recebida" }));
    await waitFor(() => expect(within(row).getByText("Referência da nota: NF 123")).toBeInTheDocument());
    expect(api.post).toHaveBeenCalledWith("/fiscal/os/1/andamento", expect.objectContaining({ destino: "nota_recebida", versao_esperada: 1, referencia_nota: "NF 123", confirmar_acao_manual: true }));
    expect(within(row).getByRole("button", { name: "Registrar encaminhamento da nota" })).toBeDisabled();
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it("conflito no andamento pede atualização e não reaplica automaticamente a ação", async () => {
    api.post.mockRejectedValue({ response: { status: 409, data: { detail: { message: "Andamento mudou. Atualize.", versao_atual: 1 } } } });
    render(<RotinaFiscalPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver andamento das OS #7" }));
    const row = await screen.findByRole("article", { name: "Andamento da OS OS-001" });
    fireEvent.click(within(row).getByRole("checkbox", { name: /Confirmo que enviei/ }));
    fireEvent.click(within(row).getByRole("button", { name: "Registrar envio ao contador" }));
    await screen.findByText("Andamento mudou. Atualize.");
    expect(within(row).getByRole("button", { name: "Registrar envio ao contador" })).toBeDisabled();
    fireEvent.click(within(row).getByRole("button", { name: "Atualizar andamento antes de continuar" }));
    await screen.findByRole("article", { name: "Andamento da OS OS-001" });
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it("histórico de outro mês não substitui a consulta mais recente", async () => {
    const older = deferred<unknown>();
    api.get.mockImplementation((url: string, config?: Config) => {
      if (url === "/fiscal/fechamentos") return config?.params?.competencia === "2026-10" ? older.promise : Promise.resolve({ data: { items: [{ ...pacote, id: 8, competencia: "2026-11" }], total: 1 } });
      return defaultGet(url, config);
    });
    render(<RotinaFiscalPage />);
    await screen.findByText("OS-001");
    fireEvent.change(screen.getByLabelText("Competência dos serviços"), { target: { value: "2026-11" } });
    await screen.findByRole("button", { name: "Ver andamento das OS #8" });
    await act(async () => { older.resolve({ data: { items: [pacote], total: 1 } }); });
    expect(screen.queryByRole("button", { name: "Ver andamento das OS #7" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ver andamento das OS #8" })).toBeInTheDocument();
  });

  it("permite alcançar pacotes mais antigos quando o mês tem mais de vinte preparações", async () => {
    api.get.mockImplementation((url: string, config?: Config) => {
      if (url === "/fiscal/fechamentos") return Promise.resolve({ data: { items: config?.params?.skip === 20 ? [{ ...pacote, id: 10 }] : Array.from({ length: 20 }, (_, index) => ({ ...pacote, id: 30 - index })), total: 21 } });
      return defaultGet(url, config);
    });
    render(<RotinaFiscalPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Carregar mais pacotes" }));
    expect(await screen.findByRole("button", { name: "Ver andamento das OS #10" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ver andamento das OS #30" })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/fiscal/fechamentos", { params: { competencia: "2026-10", skip: 20, limit: 20 } });
    expect(screen.queryByRole("button", { name: "Carregar mais pacotes" })).not.toBeInTheDocument();
    expect(screen.getByText("21 de 21 pacote(s) nesta competência.")).toBeInTheDocument();
  });
});
