import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AtendimentoAssistenteIA from "./AtendimentoAssistenteIA";
import api from "@/lib/axios";
import { useAtendimentoAudio } from "@/lib/use-atendimento-audio";
import type { AssistenteIAResultado } from "@/lib/atendimento-assistente-ia";
import { limparRascunhosAssistenteMemoria } from "@/lib/atendimento-assistente-memory";

vi.mock("@/lib/axios", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/use-atendimento-audio", () => ({ useAtendimentoAudio: vi.fn() }));
const status = { usuario_id: 7, paciente_id: 11, habilitado: true, configurado: true, modelo: "gpt-6.1-sol", esforco: "max", modelo_transcricao: "gpt-transcribe" };
const transcript = "Tutor relata tosse, mas nega desmaios.";
const resultado: AssistenteIAResultado = {
  modelo: "gpt-6.1-sol", esforco: "max", revisao_obrigatoria: true, bloqueado_integracao: false,
  campos: [
    { campo: "anamnese", texto: transcript, fonte: "transcricao", evidencia: transcript },
    { campo: "queixa_principal", texto: "Tosse relatada pelo tutor.", fonte: "transcricao", evidencia: "Tutor relata tosse" },
  ], fontes: [], achados_exames: [], sugestoes: [], pendencias: [], avisos: [],
};
beforeEach(() => {
  limparRascunhosAssistenteMemoria();
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? null : status }));
  vi.mocked(api.post).mockResolvedValue({ data: resultado });
  vi.mocked(useAtendimentoAudio).mockReturnValue({
    audio: null, gravando: false, iniciando: false, carregandoBackup: false, seconds: 0, nivel: 0, aviso: "", erro: "", manterCopia: false,
    setManterCopia: vi.fn(), iniciar: vi.fn(), parar: vi.fn(), importar: vi.fn(), descartar: vi.fn(),
  });
  const OriginalURL = URL;
  vi.stubGlobal("URL", class extends OriginalURL {
    static createObjectURL = vi.fn(() => "blob:exame-memory");
    static revokeObjectURL = vi.fn();
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });
function abrir(onApplyField = vi.fn(), pacienteId = 11, atendimentoId = 1) {
  const view = render(<AtendimentoAssistenteIA atendimentoId={atendimentoId} pacienteId={pacienteId} patientLabel={`Paciente ${pacienteId}`} onApplyField={onApplyField} />);
  view.container.querySelector("details")?.setAttribute("open", "");
  return { ...view, onApplyField };
}
async function aguardarIdentidade() {
  await waitFor(() => expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).disabled).toBe(false));
}
async function prepararRevisao() {
  const view = abrir();
  await aguardarIdentidade();
  fireEvent.click(screen.getByLabelText(/Confirmei a autorização do tutor/));
  fireEvent.change(screen.getByLabelText("Transcrição para revisão"), { target: { value: transcript } });
  const file = new File(["%PDF-synthetic"], "exame-sintetico.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText("Fotografias ou PDFs dos exames"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Organizar e sugerir para revisão" }));
  await screen.findByLabelText("Anamnese");
  fireEvent.change(screen.getByLabelText("Anamnese"), { target: { value: "Tutor nega desmaios; tosse confirmada na revisão." } });
  const checks = screen.getAllByLabelText(/Conferi este trecho com a fonte/);
  fireEvent.click(checks[0]); fireEvent.click(checks[1]);
  fireEvent.click(screen.getAllByRole("button", { name: "Adicionar ao atendimento" })[0]);
  expect(view.onApplyField).toHaveBeenCalledTimes(1);
  return view;
}

describe("rascunho de IA em memória após navegação", () => {
  it("recupera fontes, edições e aprovação sem repetir incorporação", async () => {
    const original = await prepararRevisao(); original.unmount();
    const nextApply = vi.fn(); abrir(nextApply);
    await aguardarIdentidade();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe(transcript);
    expect(screen.getByText("exame-sintetico.pdf")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ver original" })).toBeTruthy();
    expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).value).toBe("Tutor nega desmaios; tosse confirmada na revisão.");
    expect((screen.getByRole("button", { name: "Adicionado ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    const checks = screen.getAllByLabelText(/Conferi este trecho com a fonte/);
    expect((checks[0] as HTMLInputElement).checked).toBe(true);
    expect((checks[1] as HTMLInputElement).checked).toBe(true);
    expect(nextApply).not.toHaveBeenCalled(); expect(api.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Adicionar ao atendimento" }));
    expect(nextApply).toHaveBeenCalledTimes(1);
    expect(nextApply).toHaveBeenCalledWith("queixa_principal", "Tosse relatada pelo tutor.");
  });
  it.each([
    { scenario: "outro usuário", usuarioId: 8, pacienteId: 11, atendimentoId: 1 },
    { scenario: "outro paciente no mesmo atendimento", usuarioId: 7, pacienteId: 22, atendimentoId: 1 },
    { scenario: "outro atendimento do mesmo paciente", usuarioId: 7, pacienteId: 11, atendimentoId: 2 },
  ])("não restaura dados para $scenario", async ({ usuarioId, pacienteId, atendimentoId }) => {
    const original = await prepararRevisao(); original.unmount();
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? null : { ...status, usuario_id: usuarioId, paciente_id: pacienteId } }));
    const next = abrir(vi.fn(), pacienteId, atendimentoId); await aguardarIdentidade();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByText("exame-sintetico.pdf")).toBeNull();
    expect(screen.queryByLabelText("Anamnese")).toBeNull();
    expect(screen.queryByRole("button", { name: "Adicionado ao atendimento" })).toBeNull();
    expect(next.onApplyField).not.toHaveBeenCalled();
  });
  it("não revela rascunho antes de confirmar identidade autenticada", async () => {
    const original = await prepararRevisao(); original.unmount();
    let resolveStatus!: (value: unknown) => void;
    vi.mocked(api.get).mockImplementationOnce(() => new Promise((resolve) => { resolveStatus = resolve; }));
    const next = abrir();
    const textarea = screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(true); expect(textarea.value).toBe("");
    expect(screen.queryByText("exame-sintetico.pdf")).toBeNull(); expect(screen.queryByLabelText("Anamnese")).toBeNull();
    expect(next.onApplyField).not.toHaveBeenCalled();
    await act(async () => resolveStatus({ data: status })); await aguardarIdentidade();
    expect(textarea.value).toBe(transcript); expect(screen.getByText("exame-sintetico.pdf")).toBeTruthy();
    expect(next.onApplyField).not.toHaveBeenCalled();
  });
});
