import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AtendimentoAssistenteIA from "./AtendimentoAssistenteIA";
import api from "@/lib/axios";
import { useAtendimentoAudio } from "@/lib/use-atendimento-audio";
import type { AssistenteIAResultado } from "@/lib/atendimento-assistente-ia";
import { limparRascunhosAssistenteMemoria } from "@/lib/atendimento-assistente-memory";

vi.mock("@/lib/axios", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/use-atendimento-audio", () => ({ useAtendimentoAudio: vi.fn() }));

const status = { usuario_id: 7, habilitado: true, configurado: true, modelo: "gpt-6.1-sol", esforco: "max", esforco_texto: "medium", modelo_transcricao: "gpt-transcribe" };
const resultado: AssistenteIAResultado = {
  modelo: "gpt-6.1-sol", esforco: "medium", revisao_obrigatoria: true, bloqueado_integracao: false,
  campos: [{ campo: "anamnese", texto: "Tutor relata tosse há dois dias.", fonte: "transcricao", evidencia: "tosse há dois dias" }],
  fontes: [], achados_exames: [], sugestoes: [{ titulo: "Reavaliação", conduta: "Avaliar necessidade de investigação adicional.", justificativa: "Relato ainda incompleto.", limitacoes: ["Confirmar exame físico."] }],
  pendencias: [], avisos: [],
};

beforeEach(() => {
  limparRascunhosAssistenteMemoria();
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? null : status }));
  vi.mocked(api.post).mockResolvedValue({ data: resultado });
  vi.mocked(useAtendimentoAudio).mockReturnValue({
    audio: null, gravando: false, iniciando: false, carregandoBackup: false, seconds: 0, nivel: 0, aviso: "", erro: "", manterCopia: false,
    setManterCopia: vi.fn(), iniciar: vi.fn(), parar: vi.fn(), importar: vi.fn(), descartar: vi.fn(),
  });
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:audio"), revokeObjectURL: vi.fn() }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function preparar(props: Partial<React.ComponentProps<typeof AtendimentoAssistenteIA>> = {}) {
  const onApplyField = vi.fn();
  const view = render(<AtendimentoAssistenteIA atendimentoId={1} pacienteId={1} patientLabel="Paciente Teste" onApplyField={onApplyField} {...props} />);
  view.container.querySelector("details")?.setAttribute("open", "");
  await waitFor(() => expect(screen.queryByText("Verificando disponibilidade…")).toBeNull());
  fireEvent.click(screen.getByLabelText(/Confirmei a autorização do tutor/));
  fireEvent.change(screen.getByLabelText("Transcrição para revisão"), { target: { value: "tosse há dois dias" } });
  return { ...view, onApplyField };
}

describe("AtendimentoAssistenteIA", () => {
  it("recupera conjunto concluído e exige revisão antes de incorporar, preservando aprovação na mesma aba", async () => {
    const batch = {
      id: "lote-concluido", atendimento_id: 1, paciente_id: 1, status: "completed", erro: null,
      arquivos: [], resultado, transcricao: "tosse há dois dias",
    };
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? batch : status }));
    const { onApplyField } = await preparar();
    // Status readiness precedes the independent request that restores the batch.
    const abrirRevisao = await screen.findByRole("button", { name: "Abrir revisão do conjunto" });
    expect(screen.queryByRole("button", { name: "Adicionar ao atendimento" })).toBeNull();
    fireEvent.click(abrirRevisao);
    const adicionar = await screen.findByRole("button", { name: "Adicionar ao atendimento" });
    expect((adicionar as HTMLButtonElement).disabled).toBe(true);
    expect(onApplyField).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText(/Conferi este trecho/));
    fireEvent.click(adicionar);
    await waitFor(() => expect(onApplyField).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Abrir revisão do conjunto" }));
    expect((screen.getByRole("button", { name: "Adicionado ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onApplyField).toHaveBeenCalledTimes(1);
  });

  it("permite confirmar consentimento após recuperar envio incompleto", async () => {
    const batch = {
      id: "lote-pendente", atendimento_id: 1, paciente_id: 1, status: "uploading", erro: null,
      arquivos: [], resultado: null, transcricao: null,
    };
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? batch : status }));
    const view = render(<AtendimentoAssistenteIA atendimentoId={1} pacienteId={1} patientLabel="Teste" onApplyField={vi.fn()} />);
    view.container.querySelector("details")?.setAttribute("open", "");
    await screen.findByText("Enviando fontes do conjunto");
    const consent = screen.getByLabelText(/Confirmei a autorização do tutor/) as HTMLInputElement;
    expect(consent.disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Retomar envio dos arquivos" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(consent);
    expect((screen.getByRole("button", { name: "Retomar envio dos arquivos" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("invalida revisão antiga do mesmo conjunto preservando edições até abrir explicitamente a nova", async () => {
    const batch = {
      id: "lote-concluido", atendimento_id: 1, paciente_id: 1, status: "completed", erro: null,
      arquivos: [], resultado: structuredClone(resultado), transcricao: "tosse há dois dias",
    };
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? structuredClone(batch) : status }));
    const { onApplyField } = await preparar();
    fireEvent.click(await screen.findByRole("button", { name: "Abrir revisão do conjunto" }));
    fireEvent.change(await screen.findByLabelText("Anamnese"), { target: { value: "Edição veterinária a preservar." } });
    fireEvent.click(screen.getByLabelText(/Conferi este trecho/));
    expect((screen.getByRole("button", { name: "Adicionar ao atendimento" }) as HTMLButtonElement).disabled).toBe(false);
    batch.resultado = { ...structuredClone(resultado), campos: [{ ...resultado.campos[0], texto: "Nova análise após decisão veterinária." }], raca_pendente_revisao: true };
    fireEvent.click(screen.getByRole("button", { name: "Consultar progresso" }));
    await screen.findByText(/Esta revisão está desatualizada/);
    expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).value).toBe("Edição veterinária a preservar.");
    expect((screen.getByRole("button", { name: "Adicionar ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Abrir revisão do conjunto" }));
    await screen.findByRole("button", { name: "Abrir nova revisão" });
    fireEvent.click(screen.getByRole("button", { name: "Manter revisão atual" }));
    expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).value).toBe("Edição veterinária a preservar.");
    fireEvent.click(screen.getByRole("button", { name: "Abrir revisão do conjunto" }));
    fireEvent.click(screen.getByRole("button", { name: "Abrir nova revisão" }));
    expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).value).toBe("Nova análise após decisão veterinária.");
    expect((screen.getByLabelText(/Conferi este trecho/) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole("button", { name: "Adicionar ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText(/Esta revisão está desatualizada/)).toBeNull();
    expect(onApplyField).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it.each(["ausente", "revogado", "sem resposta"])("confere lote antes de incorporar e bloqueia resultado %s", async (cenario) => {
    let batch: unknown = {
      id: "lote-concluido", atendimento_id: 1, paciente_id: 1, status: "completed", erro: null,
      arquivos: [], resultado: structuredClone(resultado), transcricao: "tosse há dois dias",
    };
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? structuredClone(batch) : status }));
    const { onApplyField } = await preparar();
    fireEvent.click(await screen.findByRole("button", { name: "Abrir revisão do conjunto" }));
    fireEvent.change(await screen.findByLabelText("Anamnese"), { target: { value: "Texto que deve ser preservado." } });
    fireEvent.click(screen.getByLabelText(/Conferi este trecho/));
    if (cenario === "ausente") batch = null;
    else if (cenario === "revogado") batch = { ...(batch as object), resultado: { ...resultado, bloqueado_integracao: true } };
    else vi.mocked(api.get).mockRejectedValueOnce(new Error("Consulta indisponível"));
    fireEvent.click(screen.getByRole("button", { name: "Adicionar ao atendimento" }));
    await screen.findByText(/Esta revisão está desatualizada/);
    expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).value).toBe("Texto que deve ser preservado.");
    expect(onApplyField).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("invalida a revisão quando o conjunto deixa de existir ao consultar progresso", async () => {
    let batch: unknown = { id: "lote-concluido", atendimento_id: 1, paciente_id: 1, status: "completed", erro: null, arquivos: [], resultado, transcricao: "tosse" };
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? batch : status }));
    await preparar();
    fireEvent.click(await screen.findByRole("button", { name: "Abrir revisão do conjunto" }));
    await screen.findByLabelText("Anamnese");
    batch = null;
    fireEvent.click(screen.getByRole("button", { name: "Consultar progresso" }));
    await screen.findByText(/Esta revisão está desatualizada/);
    expect((screen.getByRole("button", { name: "Adicionar ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("exibe o esforço de texto ou de exames conforme a seleção", async () => {
    await preparar();
    expect(screen.getByText(/Análise: gpt-6.1-sol · medium/)).toBeTruthy();
    const exames = screen.getByLabelText("Fotografias ou PDFs dos exames");
    fireEvent.change(exames, { target: { files: [new File(["PDF"], "exame.pdf", { type: "application/pdf" })] } });
    expect(screen.getByText(/Análise: gpt-6.1-sol · max/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remover exame.pdf" }));
    expect(screen.getByText(/Análise: gpt-6.1-sol · medium/)).toBeTruthy();
  });

  it("exige atendimento salvo", () => {
    render(<AtendimentoAssistenteIA atendimentoId={null} pacienteId={1} patientLabel="Teste" onApplyField={vi.fn()} />);
    expect(screen.getByText(/Salve o atendimento e confirme o paciente/)).toBeTruthy();
    expect(api.get).not.toHaveBeenCalled();
  });
  it("só incorpora um campo após aprovação explícita e evita clique duplicado", async () => {
    const { onApplyField } = await preparar();
    fireEvent.click(screen.getByRole("button", { name: "Organizar e sugerir para revisão" }));
    const adicionar = await screen.findByRole("button", { name: "Adicionar ao atendimento" });
    expect(onApplyField).not.toHaveBeenCalled();
    expect((adicionar as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Conferi este trecho/));
    fireEvent.click(adicionar);
    expect(onApplyField).toHaveBeenCalledWith("anamnese", "Tutor relata tosse há dois dias.");
    expect((screen.getByRole("button", { name: "Adicionado ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onApplyField).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Plano e condutas para sua avaliação")).toBeTruthy();
  });
  it("invalida aprovação após edição do campo", async () => {
    const { onApplyField } = await preparar();
    fireEvent.click(screen.getByRole("button", { name: "Organizar e sugerir para revisão" }));
    await screen.findByRole("button", { name: "Adicionar ao atendimento" });
    fireEvent.click(screen.getByLabelText(/Conferi este trecho/));
    fireEvent.change(screen.getByLabelText("Anamnese"), { target: { value: "Texto revisado pelo veterinário." } });
    expect((screen.getByRole("button", { name: "Adicionar ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onApplyField).not.toHaveBeenCalled();
  });
  it("bloqueia incorporação quando a identidade da fonte não confere", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { ...resultado, bloqueado_integracao: true } });
    const { onApplyField } = await preparar();
    fireEvent.click(screen.getByRole("button", { name: "Organizar e sugerir para revisão" }));
    const adicionar = await screen.findByRole("button", { name: "Adicionar ao atendimento" });
    expect((adicionar as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText(/Conferi este trecho/) as HTMLInputElement).disabled).toBe(true);
    expect(onApplyField).not.toHaveBeenCalled();
  });
  it("descarta resultado obsoleto ao trocar o atendimento", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(api.post).mockImplementation(() => new Promise((res) => { resolve = res; }));
    const { rerender, container, onApplyField } = await preparar();
    fireEvent.click(screen.getByRole("button", { name: "Organizar e sugerir para revisão" }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    rerender(<AtendimentoAssistenteIA atendimentoId={2} pacienteId={2} patientLabel="Outro paciente" onApplyField={onApplyField} />);
    container.querySelector("details")?.setAttribute("open", "");
    await act(async () => resolve({ data: resultado }));
    expect(screen.queryByText("Tutor relata tosse há dois dias.")).toBeNull();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("");
    expect(onApplyField).not.toHaveBeenCalled();
  });
  it("não consulta IA quando salvar o contexto falha", async () => {
    const onEnsureSaved = vi.fn().mockResolvedValue(false);
    await preparar({ onEnsureSaved });
    fireEvent.click(screen.getByRole("button", { name: "Organizar e sugerir para revisão" }));
    await screen.findByText(/As fontes foram preservadas/);
    expect(api.post).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("tosse há dois dias");
  });
  it("conserva a transcrição após timeout e só tenta novamente por ação explícita", async () => {
    vi.mocked(api.post).mockRejectedValueOnce({ response: { status: 504, data: { detail: "A IA excedeu o tempo de resposta." } } });
    const { onApplyField } = await preparar();
    const analisar = screen.getByRole("button", { name: "Organizar e sugerir para revisão" });
    fireEvent.click(analisar);
    await screen.findByText("A IA excedeu o tempo de resposta.");
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("tosse há dois dias");
    expect(api.post).toHaveBeenCalledTimes(1);
    fireEvent.click(analisar);
    await screen.findByRole("button", { name: "Adicionar ao atendimento" });
    expect(api.post).toHaveBeenCalledTimes(2);
    expect((vi.mocked(api.post).mock.calls[1][1] as FormData).get("transcricao")).toBe("tosse há dois dias");
    expect(onApplyField).not.toHaveBeenCalled();
  });

  it("mantém áudio acessível quando a transcrição falha", async () => {
    const audioState = vi.mocked(useAtendimentoAudio).getMockImplementation()!;
    const original = audioState(1, 7, 1);
    vi.mocked(useAtendimentoAudio).mockReturnValue({ ...original, audio: new File(["audio"], "consulta.webm", { type: "audio/webm" }) });
    vi.mocked(api.post).mockRejectedValue(new Error("Serviço temporariamente indisponível"));
    await preparar();
    fireEvent.click(screen.getByRole("button", { name: "Transcrever áudio" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("link", { name: /Baixar áudio original/ })).toBeTruthy();
    expect(original.descartar).not.toHaveBeenCalled();
  });
  it("mostra o uso da referência e preserva nome divergente recebido da IA", async () => {
    const original = vi.mocked(useAtendimentoAudio).getMockImplementation()!(1, 7, 1);
    vi.mocked(useAtendimentoAudio).mockReturnValue({ ...original, audio: new File(["audio"], "consulta.webm") });
    const aviso = "O nome cadastrado foi usado apenas como pista de grafia. O texto recebido da IA é exibido sem substituições automáticas de nomes; confira diferenças com o áudio.";
    vi.mocked(api.post).mockResolvedValue({ data: { texto: "Paciente Órion-X9, sem desmaios.", modelo: "gpt-transcribe", avisos: [aviso] } });
    await preparar();
    fireEvent.click(screen.getByRole("button", { name: "Transcrever áudio" }));
    await screen.findByRole("button", { name: "Áudio transcrito" });
    expect(screen.getByText(aviso)).toBeTruthy();
    const texto = (screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value;
    expect(texto).toContain("Paciente Órion-X9, sem desmaios.");
    expect(texto).not.toContain("Paciente Teste");
  });
  it("adiciona novos trechos preservando texto revisado e impede retranscrição duplicada", async () => {
    const audioState = vi.mocked(useAtendimentoAudio).getMockImplementation()!(1, 7, 1);
    vi.mocked(useAtendimentoAudio).mockReturnValue({ ...audioState, audio: new File(["primeiro"], "primeiro.webm") });
    vi.mocked(api.post).mockResolvedValue({ data: { texto: "Primeiro trecho", modelo: "gpt-transcribe", avisos: [] } });
    const { rerender, onApplyField } = await preparar();
    fireEvent.click(screen.getByRole("button", { name: "Transcrever áudio" }));
    const concluido = await screen.findByRole("button", { name: "Áudio transcrito" });
    expect((concluido as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("tosse há dois dias\n\nPrimeiro trecho");
    fireEvent.change(screen.getByLabelText("Transcrição para revisão"), { target: { value: "Primeiro trecho revisado" } });
    vi.mocked(useAtendimentoAudio).mockReturnValue({ ...audioState, audio: new File(["segundo"], "segundo.webm") });
    vi.mocked(api.post).mockResolvedValue({ data: { texto: "Segundo trecho", modelo: "gpt-transcribe", avisos: [] } });
    rerender(<AtendimentoAssistenteIA atendimentoId={1} pacienteId={1} patientLabel="Paciente Teste" onApplyField={onApplyField} />);
    fireEvent.click(screen.getByRole("button", { name: "Transcrever áudio" }));
    await screen.findByRole("button", { name: "Áudio transcrito" });
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("Primeiro trecho revisado\n\nSegundo trecho");
    expect(api.post).toHaveBeenCalledTimes(2);
  });
  it("só incorpora achado com revisão e mantém arquivo, página, data e unidade", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { ...resultado, campos: [],
      fontes: [{ arquivo: "01_exame.pdf", paciente_nome: "Paciente Teste", especie: "canino", data_exame: "2026-10-25", identidade: "compativel", motivo: "Identificação compatível" }],
      achados_exames: [{ arquivo: "01_exame.pdf", pagina: 2, descricao: "Creatinina", evidencia: "Creatinina 1,2 mg/dL", valor: "1,2", unidade: "mg/dL", referencia: "0,5–1,5 mg/dL", confianca: "alta", alertas: [] }],
    } });
    const { onApplyField } = await preparar();
    fireEvent.click(screen.getByRole("button", { name: "Organizar e sugerir para revisão" }));
    const adicionar = await screen.findByRole("button", { name: "Adicionar achado aos dados clínicos" });
    expect((adicionar as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Creatinina 1,2 mg/dL")).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Conferi este achado no exame original/));
    fireEvent.click(adicionar);
    expect(onApplyField).toHaveBeenCalledWith("dados_clinicos", expect.stringContaining("01_exame.pdf, página 2, exame de 2026-10-25"));
    expect(onApplyField).toHaveBeenCalledWith("dados_clinicos", expect.stringContaining("1,2 mg/dL"));
  });
  it("avisa o integrador quando há fontes pendentes", async () => {
    const onPendingChange = vi.fn();
    const { unmount } = await preparar({ onPendingChange });
    await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(true));
    unmount();
    expect(onPendingChange).toHaveBeenLastCalledWith(false);
  });
  it("informa operação ativa e libera ao cancelar a espera", async () => {
    const onBusyChange = vi.fn();
    vi.mocked(api.post).mockImplementation(() => new Promise(() => {}));
    await preparar({ onBusyChange });
    fireEvent.click(screen.getByRole("button", { name: "Organizar e sugerir para revisão" }));
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar espera" }));
    expect(onBusyChange).toHaveBeenLastCalledWith(false);
    expect((screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement).value).toBe("tosse há dois dias");
  });
  it("salva anexos apenas na ação específica e transmite o original", async () => {
    const onAttachFiles = vi.fn().mockResolvedValue(undefined);
    await preparar({ onAttachFiles });
    const file = new File(["%PDF-test"], "exame.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Fotografias ou PDFs dos exames"), { target: { files: [file] } });
    expect(onAttachFiles).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Guardar arquivos no prontuário" }));
    await waitFor(() => expect(onAttachFiles).toHaveBeenCalledWith([file]));
    expect(api.post).not.toHaveBeenCalled();
  });
  it("não anexa arquivo se sincronizar o paciente salvo falha", async () => {
    const onAttachFiles = vi.fn();
    await preparar({ onAttachFiles, onEnsureSaved: vi.fn().mockResolvedValue(false) });
    fireEvent.change(screen.getByLabelText("Fotografias ou PDFs dos exames"), { target: { files: [new File(["%PDF-test"], "exame.pdf")] } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar arquivos no prontuário" }));
    await screen.findByText(/confirme o paciente antes de guardar os arquivos/);
    expect(onAttachFiles).not.toHaveBeenCalled();
    expect(screen.getByText("exame.pdf")).toBeTruthy();
  });
  it.each([
    { name: "gravacao.webm", size: 24_000_001, mime: "audio/webm", message: "24.000.000 bytes" },
    { name: "gravacao.ogg", size: 20, mime: "audio/ogg", message: "converta uma cópia" },
    { name: "gravacao.flac", size: 20, mime: "audio/flac", message: "converta uma cópia" },
  ])("preserva reprodução/download mas não envia arquivo inviável: $name", async ({ name, size, mime, message }) => {
    const audioState = vi.mocked(useAtendimentoAudio).getMockImplementation()!(1, 7, 1);
    const file = new File(["audio"], name, { type: mime });
    Object.defineProperty(file, "size", { value: size });
    vi.mocked(useAtendimentoAudio).mockReturnValue({ ...audioState, audio: file });
    const onEnsureSaved = vi.fn();
    await preparar({ onEnsureSaved });
    expect(screen.getByRole("alert").textContent).toContain(message);
    const transcrever = screen.getByRole("button", { name: "Transcrever áudio" }) as HTMLButtonElement;
    expect(transcrever.disabled).toBe(true);
    fireEvent.click(transcrever);
    expect(api.post).not.toHaveBeenCalled();
    expect(onEnsureSaved).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /Baixar áudio original/ })).toBeTruthy();
    expect(screen.getByLabelText("Ouvir áudio original")).toBeTruthy();
    expect(audioState.descartar).not.toHaveBeenCalled();
  });
});
