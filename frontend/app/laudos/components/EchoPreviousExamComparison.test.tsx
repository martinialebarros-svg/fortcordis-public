import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EchoPreviousExamComparison from "./EchoPreviousExamComparison";
import type { EchoPreviousExamResponse } from "@/lib/echo-previous-exam-comparison";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/axios", () => ({ default: { get } }));
const measures = { DIVEd: "30", VE_tecnica_relatorio: "modo_m", AE_Ao: "1.4", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" };
function data(reportId = 20, patientId = 7): EchoPreviousExamResponse { return {
  estado: "disponivel", paciente_id: patientId,
  atual: { id: reportId, paciente_id: patientId, status: "Rascunho", data_exame: "2026-10-27", medidas: { ...measures, DIVEd: "32" } },
  anterior: { id: 10, paciente_id: patientId, status: "Finalizado", data_exame: "2026-01-10", medidas: { ...measures } },
  opcoes: [{ id: 10, data_exame: "2026-01-10" }],
}; }
function deferred() { let resolve!: (value: { data: EchoPreviousExamResponse }) => void; let reject!: (value: Error) => void;
  const promise = new Promise<{ data: EchoPreviousExamResponse }>((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
function toggle(container: HTMLElement, open = true) { const details = container.querySelector("details")!; details.open = open; fireEvent(details, new Event("toggle")); }

describe("consulta opcional de exames anteriores", () => {
  beforeEach(() => { get.mockReset(); get.mockResolvedValue({ data: data() }); });
  it("consulta apenas ao abrir, limita a espera e exibe origem e diferenças neutras sem escrever", async () => {
    const view = render(<EchoPreviousExamComparison laudoId={20} pacienteId={7} />);
    expect(get).not.toHaveBeenCalled();
    toggle(view.container);
    await screen.findByText("+2,00 mm");
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("/laudos/20/comparacao-anterior", { params: undefined, timeout: 8000, signal: expect.any(AbortSignal) });
    expect(screen.getByRole("link", { name: "Abrir laudo #10" })).toHaveAttribute("href", "/laudos/10");
    expect(screen.getByText(/A consulta não altera o laudo nem o PDF/)).toBeInTheDocument();
  });
  it("permite recuperar falha local sem bloquear o conteúdo principal", async () => {
    get.mockRejectedValueOnce(new Error("timeout"));
    const view = render(<><h1>Laudo atual disponível</h1><EchoPreviousExamComparison laudoId={20} pacienteId={7} /></>);
    toggle(view.container);
    await screen.findByRole("button", { name: "Tentar novamente" });
    expect(screen.getByRole("heading", { name: "Laudo atual disponível" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    await screen.findByText("+2,00 mm");
    expect(get).toHaveBeenCalledTimes(2);
  });
  it("exibe o histórico concluído também após liberação no portal", async () => {
    const published = data(); published.anterior!.status = "Liberado no portal";
    get.mockResolvedValue({ data: published });
    const view = render(<EchoPreviousExamComparison laudoId={20} pacienteId={7} />); toggle(view.container);
    await screen.findByText("+2,00 mm");
    expect(screen.getByRole("link", { name: "Abrir laudo #10" })).toHaveAttribute("href", "/laudos/10");
  });
  it("cancela a solicitação ao fechar/desmontar e ignora resposta tardia", async () => {
    const pending = deferred(); get.mockReturnValue(pending.promise);
    const view = render(<EchoPreviousExamComparison laudoId={20} pacienteId={7} />);
    toggle(view.container);
    await screen.findByText("Consultando exames anteriores…");
    const signal = get.mock.calls[0][1].signal as AbortSignal;
    toggle(view.container, false);
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve({ data: data() }));
    expect(screen.queryByText("+2,00 mm")).not.toBeInTheDocument();
    toggle(view.container); await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    const second = get.mock.calls[1][1].signal as AbortSignal;
    view.unmount(); expect(second.aborted).toBe(true);
  });
  it("não deixa a resposta de outro laudo/paciente vencer após mudar a rota", async () => {
    const old = deferred(), fresh = deferred(); get.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const view = render(<EchoPreviousExamComparison laudoId={20} pacienteId={7} />); toggle(view.container);
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    view.rerender(<EchoPreviousExamComparison laudoId={21} pacienteId={8} />);
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(get.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => fresh.resolve({ data: { ...data(21, 8), atual: { ...data(21, 8).atual, medidas: { ...measures, DIVEd: "35" } } } }));
    await screen.findByText("+5,00 mm");
    await act(async () => old.resolve({ data: data() }));
    expect(screen.queryByText("+2,00 mm")).not.toBeInTheDocument();
    expect(screen.getByText("+5,00 mm")).toBeInTheDocument();
  });
  it("rejeita resposta com identidade incompatível antes de mostrar valores", async () => {
    get.mockResolvedValue({ data: data(20, 8) });
    const view = render(<EchoPreviousExamComparison laudoId={20} pacienteId={7} />); toggle(view.container);
    await screen.findByRole("button", { name: "Tentar novamente" });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("exige escolha manual para a mesma data e envia somente o ID selecionado", async () => {
    const ambiguous = data(); ambiguous.estado = "data_anterior_ambigua"; ambiguous.anterior = null;
    ambiguous.opcoes.push({ id: 11, data_exame: "2026-01-10" });
    const selected = data(); selected.opcoes = ambiguous.opcoes;
    get.mockResolvedValueOnce({ data: ambiguous }).mockResolvedValueOnce({ data: selected });
    const view = render(<EchoPreviousExamComparison laudoId={20} pacienteId={7} />); toggle(view.container);
    await screen.findByText(/Há mais de um laudo/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Exame anterior" }), { target: { value: "10" } });
    await screen.findByText("+2,00 mm");
    expect(get.mock.calls[1][1].params).toEqual({ anterior_id: 10 });
  });
  it.each(["sem_anterior", "data_atual_ausente"] as const)("mostra estado específico %s sem tabela", async (state) => {
    const empty = data(); empty.estado = state; empty.anterior = null; empty.opcoes = [];
    if (state === "data_atual_ausente") empty.atual.data_exame = null;
    get.mockResolvedValue({ data: empty });
    const view = render(<EchoPreviousExamComparison laudoId={20} pacienteId={7} />); toggle(view.container);
    await screen.findByText(state === "sem_anterior" ? /Nenhum ecocardiograma finalizado/ : /Confirme a data do exame atual/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("permite sair de uma seleção que deixou de existir sem recarregar o laudo", async () => {
    get.mockResolvedValueOnce({ data: data() }).mockRejectedValueOnce(new Error("404"))
      .mockResolvedValueOnce({ data: data() });
    const view = render(<EchoPreviousExamComparison laudoId={20} pacienteId={7} />); toggle(view.container);
    await screen.findByText("+2,00 mm");
    fireEvent.change(screen.getByRole("combobox", { name: "Exame anterior" }), { target: { value: "10" } });
    await screen.findByRole("button", { name: "Voltar à seleção automática" });
    fireEvent.click(screen.getByRole("button", { name: "Voltar à seleção automática" }));
    await screen.findByText("+2,00 mm");
    expect(get.mock.calls[2][1].params).toBeUndefined();
  });
});
