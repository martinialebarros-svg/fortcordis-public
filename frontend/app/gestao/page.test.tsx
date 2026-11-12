import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GestaoWorkspace } from "./GestaoWorkspace";
import { premissasDoContexto, premissasVazias, type MetricasGestao, type PainelGestao, type PremissasSalvas } from "./types";
import { operationalTodayDateInput } from "@/lib/calendar-date";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: mocks }));
vi.mock("../layout-dashboard", () => ({ default: ({ children }: { children: React.ReactNode }) => children }));
const hoje = operationalTodayDateInput();
const context = { data_inicio: `${hoje.slice(0, 7)}-01`, data_fim: hoje, clinica_id: null, regiao: null };
const saved: PremissasSalvas = { revision: 3, updated_at: null, updated_by_id: 1, contexto: context, values: premissasVazias() };
const metrics: MetricasGestao = {
  contribuicao: { receita_competencia: 1000, tributos: null, taxas: null, repasses: null, custos_variaveis: null, horas_totais: null, valor: null, por_hora: null, estimado: false, lacunas: ["Custos e horas ainda não informados."], formula: "Receita menos custos, dividida pelas horas.", detalhes: [{ os_id: 1, numero_os: "OS-001", clinica_id: 1, clinica_nome: "Clínica sintética", data_atendimento: hoje, valor: 1000, status: "Pendente" }] },
  recebimento: { prazo_medio_dias: 3, valor_recebido_bruto: 400, credito_utilizado: 0, saldo_aberto: 600, vencido: 200, sem_vencimento: 400, os_pagas_sem_comprovante: 0, lacunas: [], formula: "Pagamentos parciais ponderados pelo valor.", detalhes: [] },
  concentracao: { base: "Competência das OS do período.", receita_total: 1000, top1_pct: 100, top3_pct: null, top5_pct: null, clinicas: [{ clinica_id: 1, clinica_nome: "Clínica sintética", ativa: false, regiao: "Norte", receita: 1000, participacao_pct: 100, quantidade_os: 1 }], evolucao: [], lacunas: [] },
  caixa: { saldo_inicial: null, saldo_final: null, entradas_confirmadas: 400, entradas_previstas: 600, saidas_confirmadas: 0, saidas_previstas: 0, parcial: true, semanas: [], meses: [], detalhes: [], lacunas: ["Saldo inicial não informado."], formula: "Saldo inicial + entradas − saídas." },
  ocupacao: { capacidade_minutos: 480, agendados_minutos: 120, agendados_totais_minutos: 120, realizados_minutos: 60, livres_minutos: 360, taxa_agendada_pct: 25, taxa_realizada_pct: 12.5, base: "Jornada global descontada dos bloqueios.", formula: "Minutos agendados / capacidade global.", parcial: false, lacunas: [], limites: [], dias: [], por_regiao: [], registros: [] },
  cancelamentos: { total_agendamentos: 4, total_cancelados: 1, taxa_pct: 25, por_status: [{ status: "Cancelado", quantidade: 1 }, { status: "Expirado", quantidade: 1 }, { status: "Faltou", quantidade: 1 }, { status: "Agendado", quantidade: 1 }], por_clinica: [], por_regiao: [], motivos: [], reativados_identificados: 1, reagendados_identificados: 0, base: "Estado atual pela data de agendamento.", formula: "Cancelados / agendamentos únicos.", parcial: true, lacunas: ["Motivos estruturados indisponíveis."] },
};
const response: PainelGestao = { atualizado_em: `${hoje}T12:00:00-03:00`, periodo: { inicio: context.data_inicio, fim: context.data_fim, anterior_inicio: "2026-09-01", anterior_fim: "2026-09-25" }, filtros: { clinicas: [{ id: 1, nome: "Clínica sintética", ativo: false }], regioes: ["Norte", "Não informada"] }, atual: metrics, anterior: metrics };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockImplementation((path: string) => Promise.resolve({ data: path === "/auth/me" ? { papeis: ["admin"] } : saved }));
  mocks.post.mockResolvedValue({ data: structuredClone(response) });
  mocks.put.mockResolvedValue({ data: { ...saved, revision: 4 } });
});

describe("painel de gestão administrativo", () => {
  it("preserva desconhecido, separa estados e permite inspecionar a origem sem dados clínicos", async () => {
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    const contribution = screen.getByRole("link", { name: /Contribuição por hora/ });
    expect(contribution).toHaveTextContent("Não disponível");
    expect(screen.getByLabelText("Tributos (%)")).toHaveValue(null);
    expect(screen.getByLabelText("Saldo inicial informado (R$)")).toHaveValue(null);
    expect(screen.getByText("Clínica sintética (inativa)", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Expirado", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("Faltou", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("OS-001")).toBeInTheDocument();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("mostra denominadores vazios e tabelas vazias sem NaN, infinito ou percentuais inventados", async () => {
    const empty = structuredClone(metrics);
    empty.contribuicao.detalhes = [];
    empty.contribuicao.receita_competencia = 0;
    empty.ocupacao.capacidade_minutos = 0;
    empty.ocupacao.taxa_agendada_pct = null;
    empty.ocupacao.taxa_realizada_pct = null;
    empty.ocupacao.livres_minutos = 0;
    empty.cancelamentos.total_agendamentos = 0;
    empty.cancelamentos.total_cancelados = 0;
    empty.cancelamentos.taxa_pct = null;
    empty.concentracao.clinicas = [];
    empty.concentracao.top1_pct = null;
    empty.recebimento.prazo_medio_dias = null;
    mocks.post.mockResolvedValue({ data: { ...response, atual: empty, anterior: empty } });
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    expect(screen.getByRole("link", { name: /Ocupação agendada/ })).toHaveTextContent("Não disponível");
    expect(screen.getByRole("link", { name: /Cancelamentos/ })).toHaveTextContent("Não disponível");
    expect(screen.getByText(/Receita dos serviços: nenhum registro/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/NaN|Infinity/);
  });

  it("nega a interface e não consulta números quando o usuário não é administrador", async () => {
    mocks.get.mockResolvedValue({ data: { papeis: ["veterinario"] } });
    render(<GestaoWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent("exclusivo de administradores");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });

  it("simula zero explícito sem salvar e grava apenas no comando de salvar com revisão e contexto", async () => {
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    fireEvent.change(screen.getByLabelText("Tributos (%)"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Horas de atendimento"), { target: { value: "5" } });
    fireEvent.click(screen.getByText("Simular sem salvar"));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1]).toMatchObject({ ...context, premissas: { tributos_percentual: 0, horas_atendimento: 5, saldo_inicial: null } });
    expect(mocks.put).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText("Salvar premissas deste recorte")).not.toBeDisabled());
    fireEvent.click(screen.getByText("Salvar premissas deste recorte"));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/gestao/premissas", expect.objectContaining({ expected_revision: 3, contexto: context, values: expect.objectContaining({ tributos_percentual: 0, horas_atendimento: 5, taxas_percentual: null }) }), expect.any(Object)));
  });

  it("limpa premissas ao trocar filtro e ignora resposta atrasada de outro recorte", async () => {
    const late = deferred<{ data: PainelGestao }>();
    mocks.post.mockResolvedValueOnce({ data: response }).mockReturnValueOnce(late.promise).mockResolvedValueOnce({ data: { ...response, atual: { ...metrics, contribuicao: { ...metrics.contribuicao, por_hora: 77 } } } });
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    fireEvent.change(screen.getByLabelText("Horas de atendimento"), { target: { value: "10" } });
    fireEvent.click(screen.getByText("Simular sem salvar"));
    fireEvent.change(screen.getByLabelText("Clínica"), { target: { value: "1" } });
    expect(screen.getByLabelText("Horas de atendimento")).toHaveValue(null);
    fireEvent.click(screen.getByText("Atualizar painel"));
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    expect(mocks.post.mock.calls[2][1]).toMatchObject({ clinica_id: 1, premissas: { horas_atendimento: null } });
    await act(async () => late.resolve({ data: { ...response, atual: { ...metrics, contribuicao: { ...metrics.contribuicao, por_hora: 9999 } } } }));
    expect(screen.getByRole("link", { name: /Contribuição por hora/ })).toHaveTextContent("77,00");
    expect(screen.queryByText(/9\.999,00/)).toBeNull();
    expect(mocks.post.mock.calls[1][2].signal.aborted).toBe(true);
  });

  it("mantém consulta e simulação disponíveis quando a persistência de premissas falha", async () => {
    mocks.get.mockImplementation((path: string) => path === "/auth/me" ? Promise.resolve({ data: { papeis: ["admin"] } }) : Promise.reject({ isAxiosError: true, response: { status: 503 } }));
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    expect(screen.getByText(/As premissas salvas estão indisponíveis/)).toBeInTheDocument();
    expect(screen.getByText("Salvar premissas deste recorte")).toBeDisabled();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("conflito de revisão não sobrescreve premissas e orienta recuperação explícita", async () => {
    mocks.put.mockRejectedValue({ isAxiosError: true, response: { status: 409 } });
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    fireEvent.click(screen.getByText("Salvar premissas deste recorte"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Outro administrador alterou as premissas");
    expect(mocks.put).toHaveBeenCalledTimes(1);
  });

  it("exibe limite de detalhes e mantém valores reais zerados distintos dos desconhecidos", async () => {
    mocks.post.mockResolvedValue({ data: { ...response, atual: { ...metrics, contribuicao: { ...metrics.contribuicao, detalhes_limitados: true, total_registros: 700, taxas: 0 } } } });
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    expect(screen.getByText(/cálculo usa todos os 700 registros/)).toBeInTheDocument();
    const section = screen.getByRole("region", { name: "Contribuição por hora" });
    expect(within(section).getByText("Taxas").nextElementSibling).toHaveTextContent("0,00");
    expect(within(section).getByText("Tributos").nextElementSibling).toHaveTextContent("Não disponível");
  });

  it("distingue movimentos de mesmo valor pela descrição, preserva recorrências e identifica descrições ausentes", async () => {
    const detalhes: MetricasGestao["caixa"]["detalhes"] = [
      { fonte: "premissa", id: 1, descricao: "Aluguel estimado", clinica_id: null, data: "2026-10-10", tipo: "saida", valor: 300, natureza: "premissa" },
      { fonte: "premissa", id: 2, descricao: "Manutenção estimada", clinica_id: null, data: "2026-10-10", tipo: "saida", valor: 300, natureza: "premissa" },
      { fonte: "premissa", id: 1, descricao: "Aluguel estimado", clinica_id: null, data: "2026-11-10", tipo: "saida", valor: 300, natureza: "premissa" },
      { fonte: "conta_pagar", id: 7, clinica_id: null, data: "2026-10-11", tipo: "saida", valor: 300, natureza: "previsto" },
      { fonte: "premissa", id: 8, descricao: null, clinica_id: null, data: "2026-10-12", tipo: "saida", valor: 300, natureza: "premissa" },
    ];
    mocks.post.mockResolvedValue({ data: { ...response, atual: { ...metrics, caixa: { ...metrics.caixa, detalhes } } } });
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    fireEvent.click(screen.getByText("Ver movimentos que formam a projeção"));
    const table = screen.getByRole("table", { name: /Movimentos por origem/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    expect(within(table).getByRole("columnheader", { name: "Descrição" })).toBeVisible();
    expect(within(rows[0]).getByRole("cell", { name: "Aluguel estimado" })).toBeVisible();
    expect(within(rows[1]).getByRole("cell", { name: "Manutenção estimada" })).toBeVisible();
    expect(within(rows[2]).getByRole("cell", { name: "Aluguel estimado" })).toBeVisible();
    expect(rows[0]).toHaveTextContent("10/10/2026");
    expect(rows[2]).toHaveTextContent("10/11/2026");
    expect(rows[0]).toHaveTextContent("Premissa informada #1");
    expect(rows[1]).toHaveTextContent("Premissa informada #2");
    expect(rows[2]).toHaveTextContent("Premissa informada #1");
    expect(rows[3]).toHaveTextContent("Conta a pagar #7");
    expect(rows[4]).toHaveTextContent("Premissa informada #8");
    for (const row of rows) expect(row).toHaveTextContent("300,00");
    expect(within(rows[3]).getByRole("cell", { name: "Não informada" })).toBeVisible();
    expect(within(rows[4]).getByRole("cell", { name: "Não informada" })).toBeVisible();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("renderiza descrições de premissas como texto sem interpretar HTML", async () => {
    const descricao = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    const detalhes: MetricasGestao["caixa"]["detalhes"] = [
      { fonte: "premissa", id: 1, descricao, clinica_id: null, data: hoje, tipo: "saida", valor: 50, natureza: "premissa" },
    ];
    mocks.post.mockResolvedValue({ data: { ...response, atual: { ...metrics, caixa: { ...metrics.caixa, detalhes } } } });
    render(<GestaoWorkspace />);
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    fireEvent.click(screen.getByText("Ver movimentos que formam a projeção"));
    const table = screen.getByRole("table", { name: /Movimentos por origem/ });
    expect(within(table).getByRole("cell", { name: descricao })).toBeVisible();
    expect(table.querySelector("img, script")).toBeNull();
  });

  it("não envia movimentos incompletos e permite recuperar erros de consulta", async () => {
    mocks.post.mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ data: response });
    render(<GestaoWorkspace />);
    fireEvent.click(await screen.findByText("Tentar novamente"));
    await screen.findByRole("navigation", { name: "Indicadores de gestão" });
    fireEvent.click(screen.getByText("Adicionar movimento"));
    fireEvent.click(screen.getByText("Simular sem salvar"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Preencha data, descrição e valor");
    expect(mocks.post).toHaveBeenCalledTimes(2);
  });
});

it("associa premissas ao recorte exato e deixa todos os campos desconhecidos nos demais", () => {
  const specific = { ...saved, values: { ...premissasVazias(), saldo_inicial: 500, horas_atendimento: 9 } };
  expect(premissasDoContexto(specific, context).saldo_inicial).toBe(500);
  expect(premissasDoContexto(specific, { ...context, regiao: "Norte" }).saldo_inicial).toBeNull();
  expect(premissasDoContexto(specific, { ...context, clinica_id: 2 }).horas_atendimento).toBeNull();
  expect(premissasDoContexto(specific, { ...context, data_fim: "2027-01-01" }).saldo_inicial).toBeNull();
});
