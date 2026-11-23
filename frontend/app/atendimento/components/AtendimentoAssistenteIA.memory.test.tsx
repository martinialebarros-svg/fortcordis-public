import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AtendimentoAssistenteIA from "./AtendimentoAssistenteIA";
import api from "@/lib/axios";
import { useAtendimentoAudio } from "@/lib/use-atendimento-audio";
import type { AssistenteIAResultado } from "@/lib/atendimento-assistente-ia";
import { guardarRevisaoAssistenteMemoria, lerRascunhoAssistenteMemoria, limparRascunhosAssistenteMemoria } from "@/lib/atendimento-assistente-memory";
import type { AssistenteLote } from "@/lib/atendimento-assistente-lote";

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
function abrir(onApplyFields = vi.fn(() => true), pacienteId = 11, atendimentoId = 1) {
  const view = render(<AtendimentoAssistenteIA atendimentoId={atendimentoId} pacienteId={pacienteId} patientLabel={`Paciente ${pacienteId}`} onApplyFields={onApplyFields} />);
  view.container.querySelector("details")?.setAttribute("open", "");
  return { ...view, onApplyFields };
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
  const batch = {
    id: "lote-ficticio", atendimento_id: 1, paciente_id: 11, status: "completed",
    arquivos: [], resultado, transcricao: transcript,
  };
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? batch : status }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Consultar progresso" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Consultar progresso" }));
  fireEvent.click(await screen.findByRole("button", { name: "Abrir revisão do conjunto" }));
  await screen.findByLabelText("Anamnese");
  fireEvent.change(screen.getByLabelText("Anamnese"), { target: { value: "Tutor nega desmaios; tosse confirmada na revisão." } });
  const checks = screen.getAllByLabelText(/Conferi este trecho com a fonte/);
  fireEvent.click(checks[0]); fireEvent.click(checks[1]);
  fireEvent.click(screen.getAllByRole("button", { name: "Adicionar ao atendimento" })[0]);
  await waitFor(() => expect(view.onApplyFields).toHaveBeenCalledTimes(1));
  return { ...view, file };
}

describe("rascunho de IA em memória após navegação", () => {
  it("recupera fontes, edições e aprovação sem repetir incorporação", async () => {
    const original = await prepararRevisao(); original.unmount();
    const nextApply = vi.fn(() => true); abrir(nextApply);
    await aguardarIdentidade();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe(transcript);
    expect(screen.getByText("exame-sintetico.pdf")).toBeTruthy();
    // Identity readiness restores the file before the child effect creates its URL.
    const originalLink = await screen.findByRole("link", { name: "Ver original" });
    expect(originalLink).toHaveAttribute("href", "blob:exame-memory");
    expect(URL.createObjectURL).toHaveBeenLastCalledWith(original.file);
    expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).value).toBe("Tutor nega desmaios; tosse confirmada na revisão.");
    expect((screen.getByRole("button", { name: "Adicionado ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    const checks = screen.getAllByLabelText(/Conferi este trecho com a fonte/);
    expect((checks[0] as HTMLInputElement).checked).toBe(true);
    expect((checks[1] as HTMLInputElement).checked).toBe(true);
    expect(nextApply).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Adicionar ao atendimento" }));
    await waitFor(() => expect(nextApply).toHaveBeenCalledTimes(1));
    expect(nextApply).toHaveBeenCalledWith([{ campo: "queixa_principal", texto: "Tosse relatada pelo tutor." }]);
    expect(screen.getAllByRole("button", { name: "Adicionado ao atendimento" })).toHaveLength(2);
  });
  it("atualiza lote legado bloqueado preservando edições e inclusões até abrir a nova revisão", async () => {
    const identity = { usuarioId: 7, atendimentoId: 1, pacienteId: 11 };
    const avisoAntigo = "Identidade não confirmada: este achado não pode ser incorporado ao paciente.";
    const resultadoLegado: AssistenteIAResultado = {
      ...structuredClone(resultado), bloqueado_integracao: true,
      fontes: [{ arquivo: "exame.pdf", paciente_nome: "Jully", especie: "canina", data_exame: "2026-10-31", identidade: "divergente", motivo: "Grafia diferente do cadastro." }],
      achados_exames: [{ arquivo: "exame.pdf", pagina: 1, descricao: "Creatinina", evidencia: "Creatinina 1,2 mg/dL", valor: "1,2", unidade: "mg/dL", referencia: null, confianca: "alta", alertas: [avisoAntigo, avisoAntigo] }],
    };
    const textoEditado = "Texto já revisado pelo veterinário e incluído no atendimento.";
    guardarRevisaoAssistenteMemoria(identity, {
      texto: transcript, arquivos: [], resultado: resultadoLegado,
      edicoes: { 0: textoEditado }, revisados: { 0: true, 1: true }, aplicados: { 0: true },
      achadosEditados: { 0: "Achado revisado e já incluído." }, achadosRevisados: { 0: true }, achadosAplicados: { 0: true },
      audioTranscrito: null, anexados: false, resultadoLoteId: "lote-legado",
    });
    const resultadoProjetado: AssistenteIAResultado = {
      ...structuredClone(resultadoLegado), bloqueado_integracao: false,
      achados_exames: resultadoLegado.achados_exames.map((achado) => ({ ...achado, alertas: [] })),
    };
    let batch: AssistenteLote = {
      id: "lote-legado", atendimento_id: 1, paciente_id: 11, status: "completed", erro: null,
      arquivos: [{ id: "exame-1", nome: "exame.pdf", tipo: "exame", tamanho: 50, status: "completed", erro: null }],
      resultado: resultadoProjetado, transcricao: transcript, sintese_pendente: true,
    };
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? structuredClone(batch) : status }));
    vi.mocked(api.post).mockImplementation(async (url) => {
      expect(url).toBe("/atendimentos/1/assistente/lotes/lote-legado/retomar");
      batch = { ...batch, status: "queued", resultado: null, sintese_pendente: false };
      return { data: structuredClone(batch) };
    });
    const { onApplyFields } = abrir();
    await screen.findByText("Leituras disponíveis — análise aguardando atualização");
    await screen.findByText(/Esta revisão está desatualizada/);
    expect(screen.getByLabelText("Anamnese")).toHaveValue(textoEditado);
    expect(screen.getByRole("button", { name: "Adicionado ao atendimento" })).toBeDisabled();
    expect(screen.getAllByLabelText(/Conferi este trecho com a fonte/)[1]).toBeChecked();
    expect(screen.queryByText("Confirmar paciente por arquivo")).toBeNull();
    expect(screen.queryByText("Revisar a raça depois")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Abrir revisão do conjunto" }));
    fireEvent.click(await screen.findByRole("button", { name: "Manter revisão atual" }));
    await waitFor(() => {
      const review = lerRascunhoAssistenteMemoria(identity)?.review;
      expect(review?.edicoes[0]).toBe(textoEditado);
      expect(review?.aplicados[0]).toBe(true);
      expect(review?.achadosAplicados[0]).toBe(true);
    });
    fireEvent.click(screen.getByLabelText(/Confirmei a autorização do tutor/));
    fireEvent.click(screen.getByRole("button", { name: "Atualizar análise com arquivos processados" }));
    await screen.findByText("Conjunto na fila de processamento");
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Anamnese")).toHaveValue(textoEditado);
    expect(onApplyFields).not.toHaveBeenCalled();
    batch = {
      ...batch, status: "completed", sintese_pendente: false,
      resultado: { ...resultadoProjetado, campos: [{ ...resultadoProjetado.campos[0], texto: "Nova síntese das fontes já processadas." }] },
    };
    fireEvent.click(screen.getByRole("button", { name: "Consultar progresso" }));
    await screen.findByText("Análise conjunta concluída");
    fireEvent.click(screen.getByRole("button", { name: "Abrir revisão do conjunto" }));
    const abrirNova = await screen.findByRole("button", { name: "Abrir nova revisão" });
    expect(screen.getByLabelText("Anamnese")).toHaveValue(textoEditado);
    expect(screen.getByRole("button", { name: "Adicionado ao atendimento" })).toBeDisabled();
    fireEvent.click(abrirNova);
    expect(screen.getByLabelText("Anamnese")).toHaveValue("Nova síntese das fontes já processadas.");
    expect(screen.queryByText(/Esta revisão está desatualizada/)).toBeNull();
    expect(screen.queryByText(avisoAntigo)).toBeNull();
    expect(screen.getByRole("button", { name: "Adicionar ao atendimento" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Adicionar achado aos dados clínicos" })).toBeDisabled();
    expect(screen.getByLabelText(/Conferi este achado no exame original/)).not.toBeChecked();
    expect(onApplyFields).not.toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledTimes(1);
  });
  it.each([
    { scenario: "outro usuário", usuarioId: 8, pacienteId: 11, atendimentoId: 1 },
    { scenario: "outro paciente no mesmo atendimento", usuarioId: 7, pacienteId: 22, atendimentoId: 1 },
    { scenario: "outro atendimento do mesmo paciente", usuarioId: 7, pacienteId: 11, atendimentoId: 2 },
  ])("não restaura dados para $scenario", async ({ usuarioId, pacienteId, atendimentoId }) => {
    const original = await prepararRevisao(); original.unmount();
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? null : { ...status, usuario_id: usuarioId, paciente_id: pacienteId } }));
    const next = abrir(vi.fn(() => true), pacienteId, atendimentoId); await aguardarIdentidade();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByText("exame-sintetico.pdf")).toBeNull();
    expect(screen.queryByLabelText("Anamnese")).toBeNull();
    expect(screen.queryByRole("button", { name: "Adicionado ao atendimento" })).toBeNull();
    expect(next.onApplyFields).not.toHaveBeenCalled();
  });
  it("não revela rascunho antes de confirmar identidade autenticada", async () => {
    const original = await prepararRevisao(); original.unmount();
    let resolveStatus!: (value: unknown) => void;
    vi.mocked(api.get).mockImplementationOnce(() => new Promise((resolve) => { resolveStatus = resolve; }));
    const next = abrir();
    const textarea = screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(true); expect(textarea.value).toBe("");
    expect(screen.queryByText("exame-sintetico.pdf")).toBeNull(); expect(screen.queryByLabelText("Anamnese")).toBeNull();
    expect(next.onApplyFields).not.toHaveBeenCalled();
    await act(async () => resolveStatus({ data: status })); await aguardarIdentidade();
    expect(textarea.value).toBe(transcript); expect(screen.getByText("exame-sintetico.pdf")).toBeTruthy();
    expect(next.onApplyFields).not.toHaveBeenCalled();
  });
});
