import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AtendimentoAssistenteIA from "./AtendimentoAssistenteIA";
import AtendimentoTranscricaoRevisao from "./AtendimentoTranscricaoRevisao";
import api from "@/lib/axios";
import { useAtendimentoAudio } from "@/lib/use-atendimento-audio";
import { limparRascunhosAssistenteMemoria } from "@/lib/atendimento-assistente-memory";
import type { AssistenteIAResultado, AssistenteTranscricaoRevisao } from "@/lib/atendimento-assistente-ia";

vi.mock("@/lib/axios", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/use-atendimento-audio", () => ({ useAtendimentoAudio: vi.fn() }));

const status = { usuario_id: 7, habilitado: true, configurado: true, modelo: "gpt-6.1-sol", esforco: "medium", modelo_transcricao: "gpt-transcribe" };
const original = "  Paciente Órion. Não usa Med-X 0,5 mg.\n[inaudível]  ";
const alternativa = "Paciente Arion. Usa Med-X 5 mg.";
const revisao: AssistenteTranscricaoRevisao = {
  estado: "concluida", trechos_total: 1, trechos_revisados: 1, avisos: [],
  trechos: [{ indice: 1, inicio_segundos: 0, fim_segundos: 368.479, estado: "concluido", limitado: false,
    divergencias: [{ texto_original: original, leitura_alternativa: alternativa }], marcacoes_incerteza: ["[inaudível]"] }],
};
const resultado: AssistenteIAResultado = { modelo: "gpt-6.1-sol", esforco: "medium", revisao_obrigatoria: true, bloqueado_integracao: false,
  campos: [], fontes: [], achados_exames: [], sugestoes: [], pendencias: [], avisos: [] };

beforeEach(() => {
  limparRascunhosAssistenteMemoria();
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? null : status }));
  vi.mocked(api.post).mockResolvedValue({ data: { texto: original, modelo: "gpt-transcribe", avisos: [], revisao_transcricao: revisao } });
  vi.mocked(useAtendimentoAudio).mockReturnValue({
    audio: new File(["synthetic-audio"], "consulta-ficticia.webm", { type: "audio/webm" }),
    gravando: false, iniciando: false, carregandoBackup: false, seconds: 0, nivel: 0, aviso: "", erro: "", manterCopia: false,
    setManterCopia: vi.fn(), iniciar: vi.fn(), parar: vi.fn(), importar: vi.fn(), descartar: vi.fn(),
  });
  const OriginalURL = URL;
  vi.stubGlobal("URL", class extends OriginalURL {
    static createObjectURL = vi.fn(() => "blob:synthetic-audio");
    static revokeObjectURL = vi.fn();
  });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

async function abrir(pacienteId = 11, atendimentoId = 1, onApplyField = vi.fn()) {
  const view = render(<AtendimentoAssistenteIA atendimentoId={atendimentoId} pacienteId={pacienteId} patientLabel="Paciente cadastrado fictício" onApplyField={onApplyField} />);
  view.container.querySelector("details")?.setAttribute("open", "");
  await waitFor(() => expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).disabled).toBe(false));
  fireEvent.click(screen.getByLabelText(/Confirmei a autorização do tutor/));
  return { ...view, onApplyField };
}

async function transcrever() {
  fireEvent.click(screen.getByRole("button", { name: "Transcrever áudio" }));
  await screen.findByRole("button", { name: "Áudio transcrito" });
}

describe("incertezas da transcrição sem alteração clínica", () => {
  it("preserva literalmente o texto principal e o texto já revisado; exibe outra leitura sem incorporá-la", async () => {
    const { onApplyField } = await abrir();
    const textarea = screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Anotação já revisada.\n" } });
    await transcrever();
    expect(textarea.value).toBe(`Anotação já revisada.\n\n\n${original}`);
    const panel = screen.getByRole("region", { name: "Revisão das incertezas da transcrição" });
    expect(within(panel).getByText(alternativa)).toBeTruthy();
    expect(within(panel).getByText(/00:00–06:08/)).toBeTruthy();
    expect(within(panel).getByText(/não a posição exata da palavra/)).toBeTruthy();
    expect(within(panel).getByText(/Nenhum nome, medicamento ou dose foi substituído automaticamente/)).toBeTruthy();
    expect(within(panel).queryByRole("button")).toBeNull();
    expect(textarea.value).not.toContain(alternativa);
    expect(textarea.value).not.toContain("Paciente cadastrado fictício");
    expect(onApplyField).not.toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/atendimentos/1/assistente/transcrever", expect.any(FormData), expect.anything());
  });

  it("mantém a referência original após editar e navegar na mesma aba, sem repetir solicitação ou aplicação", async () => {
    const first = await abrir(); await transcrever();
    fireEvent.change(screen.getByLabelText("Transcrição para revisão"), { target: { value: "Texto editado manualmente pelo veterinário." } });
    expect(screen.getByText(/suas edições não foram reavaliadas/)).toBeTruthy();
    first.unmount();
    const next = await abrir();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("Texto editado manualmente pelo veterinário.");
    expect(screen.getByText(alternativa)).toBeTruthy();
    expect(screen.getByText(/suas edições não foram reavaliadas/)).toBeTruthy();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(first.onApplyField).not.toHaveBeenCalled();
    expect(next.onApplyField).not.toHaveBeenCalled();
  });

  it.each([
    { nome: "paciente", usuarioId: 7, pacienteId: 12, atendimentoId: 1 },
    { nome: "atendimento", usuarioId: 7, pacienteId: 11, atendimentoId: 2 },
    { nome: "usuário", usuarioId: 8, pacienteId: 11, atendimentoId: 1 },
  ])("não recupera incertezas para outro $nome", async ({ usuarioId, pacienteId, atendimentoId }) => {
    const first = await abrir(); await transcrever(); first.unmount();
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? null : { ...status, usuario_id: usuarioId } }));
    await abrir(pacienteId, atendimentoId);
    expect(screen.queryByRole("region", { name: "Revisão das incertezas da transcrição" })).toBeNull();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByText(alternativa)).toBeNull();
  });

  it("ignora resposta tardia de outro paciente inclusive as alternativas", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(api.post).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const view = await abrir();
    fireEvent.click(screen.getByRole("button", { name: "Transcrever áudio" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    view.rerender(<AtendimentoAssistenteIA atendimentoId={1} pacienteId={12} patientLabel="Outro paciente fictício" onApplyField={view.onApplyField} />);
    view.container.querySelector("details")?.setAttribute("open", "");
    await act(async () => resolve({ data: { texto: original, modelo: "gpt-transcribe", avisos: [], revisao_transcricao: revisao } }));
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByText(alternativa)).toBeNull();
    expect(view.onApplyField).not.toHaveBeenCalled();
  });

  it("carrega as revisões por fonte do lote sem alterar transcrição ou prontuário", async () => {
    const batch = { id: "lote-ficticio", atendimento_id: 1, paciente_id: 11, status: "completed", erro: null,
      arquivos: [], resultado, transcricao: original,
      revisoes_transcricao: [{ arquivo_id: "audio-1", nome: "fonte-ficticia.webm", revisao_transcricao: revisao }],
    };
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? batch : status }));
    const { onApplyField } = await abrir();
    fireEvent.click(await screen.findByRole("button", { name: "Abrir revisão do conjunto" }));
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe(original);
    const panel = screen.getByRole("region", { name: "Revisão das incertezas da transcrição" });
    expect(within(panel).getByText("fonte-ficticia.webm")).toBeTruthy();
    expect(within(panel).getByText(alternativa)).toBeTruthy();
    expect(onApplyField).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("mostra a revisão do áudio concluído mesmo se outra fonte do lote falhou", async () => {
    const batch = { id: "lote-ficticio", atendimento_id: 1, paciente_id: 11, status: "failed", erro: "Outra fonte pendente.",
      arquivos: [], resultado: null, transcricao: original,
      revisoes_transcricao: [{ arquivo_id: "audio-1", nome: "fonte-ficticia.webm", revisao_transcricao: revisao }],
    };
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? batch : status }));
    const { onApplyField } = await abrir();
    await screen.findByRole("region", { name: "Revisão das incertezas da transcrição" });
    expect(screen.getByText(alternativa)).toBeTruthy();
    expect(onApplyField).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it.each(["parcial", "indisponivel"] as const)("explica comparação %s sem esconder o texto ou sugerir certeza", async (estado) => {
    vi.mocked(api.post).mockResolvedValue({ data: { texto: original, modelo: "gpt-transcribe", avisos: [],
      revisao_transcricao: { ...revisao, estado, trechos_revisados: 0, trechos: [{ ...revisao.trechos[0], estado: "indisponivel", divergencias: [] }] } } });
    await abrir(); await transcrever();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe(original);
    expect(screen.getByText(/A comparação não ficou completa/)).toBeTruthy();
    expect(screen.getByText(/Este trecho não teve segunda leitura/)).toBeTruthy();
    expect(screen.getByText("Fala incerta na transcrição original")).toBeTruthy();
    expect(screen.queryByText(/Nenhuma divergência detectada/)).toBeNull();
  });

  it("distingue comparação limitada de concordância completa", () => {
    render(<AtendimentoTranscricaoRevisao fontes={[{ nome: "ficticio.wav", revisao_transcricao: {
      ...revisao, estado: "parcial", trechos: [{ ...revisao.trechos[0], limitado: true, divergencias: [] }],
    } }]} />);
    expect(screen.getByText(/A lista pode não mostrar todas as diferenças/)).toBeTruthy();
    expect(screen.queryByText(/Nenhuma divergência detectada/)).toBeNull();
    expect(screen.queryByText(/não teve segunda leitura/)).toBeNull();
  });
});
