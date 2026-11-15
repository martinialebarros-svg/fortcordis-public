import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AtendimentoAssistenteIA from "./AtendimentoAssistenteIA";
import api from "@/lib/axios";
import { useAtendimentoAudio } from "@/lib/use-atendimento-audio";
import { limparRascunhosAssistenteMemoria } from "@/lib/atendimento-assistente-memory";
import type { AssistenteIAResultado } from "@/lib/atendimento-assistente-ia";

vi.mock("@/lib/axios", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/use-atendimento-audio", () => ({ useAtendimentoAudio: vi.fn() }));

const resultado: AssistenteIAResultado = {
  modelo: "gpt-6.1-sol", esforco: "medium", revisao_obrigatoria: true, bloqueado_integracao: false,
  campos: [{ campo: "anamnese", texto: "Relato fictício para revisão.", fonte: "transcricao", evidencia: "relato fictício" }],
  fontes: [], achados_exames: [], sugestoes: [], pendencias: [], avisos: [],
};
const batch = {
  id: "lote-revisao", atendimento_id: 1, paciente_id: 1, status: "completed",
  erro: null, arquivos: [], resultado, transcricao: "Texto original fictício do conjunto.",
};

beforeEach(() => {
  limparRascunhosAssistenteMemoria();
  vi.mocked(api.post).mockReset().mockResolvedValue({ data: resultado });
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes("/lotes/") ? batch : {
    usuario_id: 7, habilitado: true, configurado: true, modelo: "gpt-6.1-sol", esforco: "medium", modelo_transcricao: "gpt-transcribe",
  } }));
  vi.mocked(useAtendimentoAudio).mockReturnValue({
    audio: null, gravando: false, iniciando: false, carregandoBackup: false, seconds: 0, nivel: 0,
    aviso: "", erro: "", manterCopia: false, setManterCopia: vi.fn(), iniciar: vi.fn(), parar: vi.fn(), importar: vi.fn(), descartar: vi.fn(),
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function preparar(props: Partial<React.ComponentProps<typeof AtendimentoAssistenteIA>> = {}) {
  const onApplyField = vi.fn();
  const view = render(<AtendimentoAssistenteIA atendimentoId={1} pacienteId={1} patientLabel="Paciente fictício" onApplyField={onApplyField} {...props} />);
  view.container.querySelector("details")?.setAttribute("open", "");
  const abrir = await screen.findByRole("button", { name: "Abrir revisão do conjunto" });
  return { abrir, onApplyField };
}

describe("substituição explícita da revisão do conjunto", () => {
  it.each([false, true])("preserva transcrição existente até confirmar a substituição (editada após abrir: %s)", async (abertaAntes) => {
    const { abrir, onApplyField } = await preparar();
    if (abertaAntes) {
      fireEvent.click(abrir);
      await screen.findByLabelText("Anamnese");
    }
    const transcricao = screen.getByLabelText("Transcrição para revisão") as HTMLTextAreaElement;
    fireEvent.change(transcricao, { target: { value: "Nome e dose conferidos manualmente no áudio fictício." } });
    fireEvent.click(abrir);
    await screen.findByRole("button", { name: "Abrir nova revisão" });
    expect(transcricao.value).toBe("Nome e dose conferidos manualmente no áudio fictício.");
    fireEvent.click(screen.getByRole("button", { name: "Manter revisão atual" }));
    expect(transcricao.value).toBe("Nome e dose conferidos manualmente no áudio fictício.");
    expect(screen.queryByLabelText("Anamnese")).toBeNull();
    fireEvent.click(abrir);
    fireEvent.click(screen.getByRole("button", { name: "Abrir nova revisão" }));
    await screen.findByLabelText("Anamnese");
    expect(transcricao.value).toBe(batch.transcricao);
    expect(api.post).not.toHaveBeenCalled();
    expect(onApplyField).not.toHaveBeenCalled();
  });

  it("abre diretamente quando não há transcrição anterior e preserva a mesma revisão ao reabrir", async () => {
    const { abrir, onApplyField } = await preparar();
    fireEvent.click(abrir);
    const anamnese = await screen.findByLabelText("Anamnese") as HTMLTextAreaElement;
    fireEvent.change(anamnese, { target: { value: "Sugestão revisada manualmente." } });
    fireEvent.click(screen.getByLabelText(/Conferi este trecho/));
    fireEvent.click(abrir);
    expect(screen.queryByRole("button", { name: "Abrir nova revisão" })).toBeNull();
    expect(anamnese.value).toBe("Sugestão revisada manualmente.");
    expect((screen.getByLabelText(/Conferi este trecho/) as HTMLInputElement).checked).toBe(true);
    expect(onApplyField).not.toHaveBeenCalled();
  });

  it("não exige confirmação quando a transcrição existente é idêntica à do conjunto", async () => {
    const { abrir } = await preparar();
    fireEvent.change(screen.getByLabelText("Transcrição para revisão"), { target: { value: batch.transcricao } });
    fireEvent.click(abrir);
    await waitFor(() => expect(screen.queryByLabelText("Anamnese")).not.toBeNull());
    expect(screen.queryByRole("button", { name: "Abrir nova revisão" })).toBeNull();
  });
});

async function prepararNovaAnalise(props: Partial<React.ComponentProps<typeof AtendimentoAssistenteIA>> = {}) {
  const { abrir, onApplyField } = await preparar(props);
  fireEvent.click(abrir);
  fireEvent.change(await screen.findByLabelText("Anamnese"), { target: { value: "Edição veterinária que precisa permanecer." } });
  fireEvent.click(screen.getByLabelText(/Conferi este trecho/));
  fireEvent.click(screen.getByLabelText(/Confirmei a autorização do tutor/));
  return { onApplyField, analisar: screen.getByRole("button", { name: "Organizar e sugerir para revisão" }) };
}

function conferirRevisaoPreservada() {
  expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).value).toBe("Edição veterinária que precisa permanecer.");
  expect((screen.getByLabelText(/Conferi este trecho/) as HTMLInputElement).checked).toBe(true);
}

describe("preservação da revisão durante nova análise", () => {
  it("mantém a revisão anterior quando salvar o contexto falha", async () => {
    const { analisar, onApplyField } = await prepararNovaAnalise({ onEnsureSaved: vi.fn().mockResolvedValue(false) });
    fireEvent.click(analisar);
    await screen.findByText(/Salve o atendimento e confirme o paciente antes de analisar/);
    conferirRevisaoPreservada();
    expect(api.post).not.toHaveBeenCalled();
    expect(onApplyField).not.toHaveBeenCalled();
  });

  it("mantém a revisão anterior quando a nova análise falha na API", async () => {
    const { analisar, onApplyField } = await prepararNovaAnalise();
    vi.mocked(api.post).mockRejectedValueOnce({ response: { status: 504, data: { detail: "Falha simulada da análise." } } });
    fireEvent.click(analisar);
    await screen.findByText("Falha simulada da análise.");
    conferirRevisaoPreservada();
    expect(onApplyField).not.toHaveBeenCalled();
  });

  it("preserva a revisão quando a resposta não pode preparar os novos campos e achados", async () => {
    const { analisar, onApplyField } = await prepararNovaAnalise();
    vi.mocked(api.post).mockResolvedValueOnce({ data: { campos: [] } });
    fireEvent.click(analisar);
    await screen.findByRole("alert");
    conferirRevisaoPreservada();
    expect(onApplyField).not.toHaveBeenCalled();
  });

  it("preserva enquanto aguarda e ao cancelar, ignorando resposta tardia", async () => {
    const { analisar, onApplyField } = await prepararNovaAnalise();
    let resolver!: (value: unknown) => void;
    vi.mocked(api.post).mockImplementationOnce(() => new Promise((resolve) => { resolver = resolve; }));
    fireEvent.click(analisar);
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    conferirRevisaoPreservada();
    expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByLabelText(/Conferi este trecho/) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Adicionar ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Cancelar espera" }));
    conferirRevisaoPreservada();
    expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).disabled).toBe(false);
    await act(async () => resolver({ data: { ...resultado, campos: [{ ...resultado.campos[0], texto: "Resposta tardia fictícia." }] } }));
    conferirRevisaoPreservada();
    expect(onApplyField).not.toHaveBeenCalled();
  });

  it("só substitui no sucesso e exige nova aprovação para o conteúdo novo", async () => {
    const { analisar, onApplyField } = await prepararNovaAnalise();
    vi.mocked(api.post).mockResolvedValueOnce({ data: { ...resultado, campos: [{ ...resultado.campos[0], texto: "Nova sugestão fictícia." }] } });
    fireEvent.click(analisar);
    await waitFor(() => expect((screen.getByLabelText("Anamnese") as HTMLTextAreaElement).value).toBe("Nova sugestão fictícia."));
    const aprovar = screen.getByLabelText(/Conferi este trecho/) as HTMLInputElement;
    expect(aprovar.checked).toBe(false);
    expect((screen.getByRole("button", { name: "Adicionar ao atendimento" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onApplyField).not.toHaveBeenCalled();
    fireEvent.click(aprovar);
    fireEvent.click(screen.getByRole("button", { name: "Adicionar ao atendimento" }));
    expect(onApplyField).toHaveBeenCalledWith("anamnese", "Nova sugestão fictícia.");
    expect(onApplyField).toHaveBeenCalledTimes(1);
  });

  it("preserva achado editado e aprovado na falha e exige nova aprovação quando o achado muda", async () => {
    const resultadoComAchado: AssistenteIAResultado = {
      ...resultado,
      fontes: [{ arquivo: "exame-ficticio.pdf", paciente_nome: "Paciente fictício", especie: "Canina", data_exame: "2026-11-15", identidade: "compativel", motivo: "Fonte fictícia compatível." }],
      achados_exames: [{ arquivo: "exame-ficticio.pdf", pagina: 1, descricao: "Medida fictícia", evidencia: "Medida fictícia 1,2 unidades", valor: "1,2", unidade: "unidades", referencia: null, confianca: "alta", alertas: [] }],
    };
    const consultarOriginal = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation(async (url, config) => String(url).includes("/lotes/")
      ? { data: { ...batch, resultado: resultadoComAchado } }
      : consultarOriginal(url, config));
    const { analisar, onApplyField } = await prepararNovaAnalise();
    fireEvent.change(screen.getByLabelText("Texto para os dados clínicos"), { target: { value: "Achado fictício conferido e editado pelo veterinário." } });
    fireEvent.click(screen.getByLabelText(/Conferi este achado no exame original/));
    vi.mocked(api.post).mockRejectedValueOnce({ response: { status: 504, data: { detail: "Falha simulada ao reanalisar exame." } } });
    fireEvent.click(analisar);
    await screen.findByText("Falha simulada ao reanalisar exame.");
    expect((screen.getByLabelText("Texto para os dados clínicos") as HTMLTextAreaElement).value).toBe("Achado fictício conferido e editado pelo veterinário.");
    expect((screen.getByLabelText(/Conferi este achado no exame original/) as HTMLInputElement).checked).toBe(true);
    expect(onApplyField).not.toHaveBeenCalled();

    vi.mocked(api.post).mockResolvedValueOnce({ data: {
      ...resultadoComAchado,
      achados_exames: [{ ...resultadoComAchado.achados_exames[0], valor: "2,4", evidencia: "Nova leitura fictícia 2,4 unidades" }],
    } });
    fireEvent.click(analisar);
    await waitFor(() => expect((screen.getByLabelText("Texto para os dados clínicos") as HTMLTextAreaElement).value).toContain("2,4 unidades"));
    expect((screen.getByLabelText(/Conferi este achado no exame original/) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole("button", { name: "Adicionar achado aos dados clínicos" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onApplyField).not.toHaveBeenCalled();
  });
});
