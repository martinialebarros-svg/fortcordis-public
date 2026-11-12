import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import api from "@/lib/axios";
import type { AssistenteLote } from "@/lib/atendimento-assistente-lote";
import type { AssistenteIAResultado } from "@/lib/atendimento-assistente-ia";
import AtendimentoAssistenteLote from "./AtendimentoAssistenteLote";

vi.mock("@/lib/axios", () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
const result: AssistenteIAResultado = {
  modelo: "gpt-6.1-sol", esforco: "medium", revisao_obrigatoria: true, bloqueado_integracao: false,
  campos: [{ campo: "anamnese", texto: "Relato sintético de tosse.", fonte: "transcricao", evidencia: "tosse" }],
  fontes: [], achados_exames: [], sugestoes: [], pendencias: [], avisos: [],
};
const files = [new File(["audio"], "trecho-01.mp3", { type: "audio/mpeg" }), new File(["pdf"], "exame.pdf", { type: "application/pdf" })];
let stored: AssistenteLote | null;
const response = () => ({ data: structuredClone(stored) });
const pendingJob = (): AssistenteLote => ({
  id: "batch-1", atendimento_id: 1, paciente_id: 2, status: "uploading", erro: null, resultado: null, transcricao: null,
  arquivos: files.map((file, index) => ({ id: `file-${index}`, nome: file.name, tamanho: file.size, mime: file.type, tipo: index ? "exame" : "audio", status: "pending", erro: null })),
});
const breedJob = (): AssistenteLote => ({
  ...pendingJob(), status: "completed", resultado: { ...result, bloqueado_integracao: true },
  arquivos: [0, 1].map((i) => ({ id: `exam-${i}`, nome: `exame-${i}.pdf`, tamanho: 3, mime: "application/pdf", tipo: "exame", status: "completed", erro: null })),
  revisao_raca: { token: "snapshot-original", pode_revisar: true, raca_cadastrada: "Poodle", fontes: [0, 1].map((i) => ({
    arquivo_id: `exam-${i}`, nome: `exame-${i}.pdf`, paciente_nome: "Paciente Teste", especie: "canino", identidade: "divergente", motivo: "Raça diferente do cadastro: SRD.", elegivel: true, impedimento: null, confirmada: false, registrado_em: null,
  })) },
});
const props = () => ({ atendimentoId: 1, pacienteId: 2, usuarioId: 7, texto: "tosse", consentimento: true, habilitado: true, disabled: false,
  onReview: vi.fn(), onBusyChange: vi.fn(), onActiveChange: vi.fn(), onPendingChange: vi.fn(), onResultInvalidated: vi.fn(), onSnapshot: vi.fn(), onEnsureSaved: vi.fn().mockResolvedValue(true) });
beforeEach(() => {
  stored = null;
  vi.mocked(api.get).mockImplementation(async () => response());
  vi.mocked(api.post).mockImplementation(async (url, payload) => {
    if (String(url).endsWith("/lotes")) stored = { ...pendingJob(), arquivos: (payload as { arquivos: AssistenteLote["arquivos"] }).arquivos.map((item) => ({ ...item, status: "pending", erro: null })) };
    else if (stored) stored.status = "queued";
    return response();
  });
  vi.mocked(api.put).mockImplementation(async (url) => {
    const file = stored!.arquivos.find((item) => String(url).endsWith(item.id))!;
    file.status = "uploaded";
    return response();
  });
  vi.mocked(api.delete).mockImplementation(async () => { stored = null; return { data: null }; });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers(); });
async function open(overrides: Partial<ReturnType<typeof props>> = {}) {
  const handlers = { ...props(), ...overrides };
  const view = render(<AtendimentoAssistenteLote {...handlers} />);
  await waitFor(() => expect(screen.queryByText("Recuperando conjunto…")).toBeNull());
  return { ...view, ...handlers };
}
const select = (items = files) => fireEvent.change(screen.getByLabelText("Áudios e PDFs do conjunto"), { target: { files: items } });
const confirmBreed = () => {
  fireEvent.click(screen.getByLabelText("Conferi o original de exame-0.pdf"));
  fireEvent.click(screen.getByLabelText(/Confirmo que os documentos selecionados/));
  fireEvent.click(screen.getByLabelText(/Confirmei que a única divergência/));
};
const breedButton = () => screen.getByRole("button", { name: "Confirmar documentos e revisar raça depois" });
const saveBreedDecision = (confirmed = true) => {
  stored!.revisao_raca!.fontes[0].confirmada = confirmed;
  stored!.revisao_raca!.fontes[0].registrado_em = confirmed ? "2026-11-09T12:00:00Z" : null;
  stored!.revisao_raca!.token = confirmed ? "snapshot-confirmado" : "snapshot-revogado";
  stored!.resultado = null;
};

describe("análise de conjunto", () => {
  it("confirma documentos individualmente com duas declarações, preservando originais e leitura divergente", async () => {
    stored = breedJob();
    vi.mocked(api.post).mockImplementation(async () => { saveBreedDecision(); return response(); });
    const { onResultInvalidated, onEnsureSaved } = await open();
    expect(screen.getByText("Leitura concluída — identificação aguardando revisão")).toBeTruthy();
    expect(screen.queryByText("Análise conjunta concluída")).toBeNull();
    expect(breedButton().matches(":disabled")).toBe(true);
    fireEvent.click(screen.getByLabelText("Conferi o original de exame-0.pdf"));
    fireEvent.click(screen.getByLabelText(/Confirmo que os documentos selecionados/));
    expect(breedButton().matches(":disabled")).toBe(true);
    fireEvent.click(screen.getByLabelText(/Confirmei que a única divergência/));
    fireEvent.click(breedButton()); fireEvent.click(breedButton());
    await screen.findByText(/Decisão registrada. A raça continua pendente/);
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/batch-1/revisar-raca"), {
      request_id: expect.any(String), revisao_token: "snapshot-original", arquivo_ids: ["exam-0"], confirmo_mesmo_paciente: true, confirmo_apenas_raca: true, consentimento: true,
    }, expect.anything());
    expect(onEnsureSaved).toHaveBeenCalledTimes(1);
    expect(onResultInvalidated).toHaveBeenCalledWith("batch-1");
    expect(api.put).not.toHaveBeenCalled();
    expect(screen.getAllByRole("link", { name: "Baixar original" })).toHaveLength(2);
    expect(screen.getAllByText(/Identificação na leitura original: Raça diferente/)).toHaveLength(2);
    expect(screen.getByText("Identidade confirmada pelo veterinário. Raça pendente de revisão.")).toBeTruthy();
    expect(screen.getByLabelText("Conferi o original de exame-1.pdf")).toBeTruthy();
  });

  it("não oferece exceção para nome ou espécie incompatível e respeita consentimento e permissões", async () => {
    stored = breedJob();
    stored.revisao_raca!.fontes[1] = { ...stored.revisao_raca!.fontes[1], paciente_nome: "Outro paciente", elegivel: false, impedimento: "O nome do paciente não corresponde ao cadastro." };
    const view = await open({ consentimento: false });
    expect(screen.queryByLabelText("Conferi o original de exame-1.pdf")).toBeNull();
    expect(screen.getByText("O nome do paciente não corresponde ao cadastro.")).toBeTruthy();
    confirmBreed();
    expect(breedButton().matches(":disabled")).toBe(true);
    for (const restricted of [{ disabled: true }, { habilitado: false }]) {
      view.rerender(<AtendimentoAssistenteLote {...props()} {...restricted} />);
      expect(breedButton().matches(":disabled")).toBe(true);
      fireEvent.click(breedButton());
    }
    expect(api.post).not.toHaveBeenCalled();
  });

  it("exige novas declarações ao mudar fontes e recusa token que mudou após salvar o atendimento", async () => {
    stored = breedJob();
    const onEnsureSaved = vi.fn(async () => { stored!.revisao_raca!.token = "novo-contexto"; return true; });
    await open({ onEnsureSaved });
    confirmBreed();
    fireEvent.click(screen.getByLabelText("Conferi o original de exame-1.pdf"));
    expect((screen.getByLabelText(/Confirmo que os documentos selecionados/) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText(/Confirmei que a única divergência/) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByLabelText(/Confirmo que os documentos selecionados/));
    fireEvent.click(screen.getByLabelText(/Confirmei que a única divergência/));
    fireEvent.click(breedButton());
    await screen.findByText(/O conjunto mudou desde a conferência/);
    expect(api.post).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Conferi o original de exame-0.pdf") as HTMLInputElement).checked).toBe(false);
  });

  it("reconcilia confirmação salva com resposta perdida sem repetir solicitação", async () => {
    stored = breedJob();
    vi.mocked(api.post).mockImplementation(async () => { saveBreedDecision(); throw new Error("Resposta perdida"); });
    await open(); confirmBreed(); fireEvent.click(breedButton());
    await screen.findByText(/Decisão registrada. A raça continua pendente/);
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledTimes(3);
    expect(api.put).not.toHaveBeenCalled();
  });

  it("reutiliza request_id após resposta e reconciliação incertas, sem retransmitir PDFs", async () => {
    stored = breedJob();
    vi.mocked(api.post).mockImplementationOnce(async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error("Consulta indisponível"));
      throw new Error("Decisão sem resposta");
    }).mockImplementationOnce(async () => { saveBreedDecision(); return response(); });
    await open(); confirmBreed(); fireEvent.click(breedButton());
    await screen.findByText("Decisão sem resposta");
    fireEvent.click(breedButton());
    await screen.findByText(/Decisão registrada. A raça continua pendente/);
    const requests = vi.mocked(api.post).mock.calls.map((call) => call[1] as { request_id: string });
    expect(requests).toHaveLength(2);
    expect(requests[1].request_id).toBe(requests[0].request_id);
    expect(api.put).not.toHaveBeenCalled();
  });

  it("recupera decisão persistida e permite retirá-la sem acionar nova análise", async () => {
    stored = breedJob(); saveBreedDecision();
    vi.mocked(api.post).mockImplementation(async () => { saveBreedDecision(false); return response(); });
    const { onResultInvalidated } = await open({ consentimento: false });
    expect(screen.getByText("Identidade confirmada pelo veterinário. Raça pendente de revisão.")).toBeTruthy();
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retirar confirmação de exame-0.pdf" }));
    await screen.findByText(/Confirmação retirada. A análise anterior precisa ser revista/);
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/batch-1/revogar-revisao-raca"), {
      request_id: expect.any(String), revisao_token: "snapshot-confirmado", arquivo_ids: ["exam-0"],
    }, expect.anything());
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.put).not.toHaveBeenCalled();
    expect(onResultInvalidated).toHaveBeenCalledWith("batch-1");
  });

  it("envia todos os arquivos com uma ação e abre o resultado somente para revisão explícita", async () => {
    const { onReview } = await open();
    select();
    fireEvent.click(screen.getByRole("button", { name: "Analisar conjunto" }));
    await screen.findByText("Conjunto na fila de processamento");
    expect(api.put).toHaveBeenCalledTimes(2);
    expect((vi.mocked(api.put).mock.calls[0][1] as FormData).get("arquivo")).toBe(files[0]);
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(onReview).not.toHaveBeenCalled();
    stored = { ...stored!, status: "completed", resultado: result, transcricao: "tosse", arquivos: stored!.arquivos.map((file) => ({ ...file, status: "completed" })) };
    fireEvent.click(screen.getByRole("button", { name: "Consultar progresso" }));
    await screen.findByText("Análise conjunta concluída");
    expect(onReview).not.toHaveBeenCalled();
    expect(screen.getAllByRole("link", { name: "Baixar original" })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Abrir revisão do conjunto" }));
    expect(onReview).toHaveBeenCalledWith(stored);
  });

  it("retoma somente envio pendente após falha de um arquivo", async () => {
    let failed = false;
    vi.mocked(api.put).mockImplementation(async (url) => {
      const file = stored!.arquivos.find((item) => String(url).endsWith(item.id))!;
      if (file.tipo === "audio" && !failed) { failed = true; throw new Error("rede"); }
      file.status = "uploaded";
      return response();
    });
    await open(); select();
    fireEvent.click(screen.getByRole("button", { name: "Analisar conjunto" }));
    await screen.findByText(/Envio pendente de 1 arquivo/);
    expect(api.put).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Retomar envio dos arquivos" }));
    await screen.findByText("Conjunto na fila de processamento");
    expect(api.put).toHaveBeenCalledTimes(3);
    expect(String(vi.mocked(api.put).mock.calls[2][0])).toContain(stored!.arquivos[0].id);
    expect(vi.mocked(api.post).mock.calls.filter(([url]) => String(url).endsWith("/lotes"))).toHaveLength(1);
  });

  it("reconcilia upload aceito quando a resposta se perde", async () => {
    vi.mocked(api.put).mockImplementation(async (url) => {
      stored!.arquivos.find((item) => String(url).endsWith(item.id))!.status = "uploaded";
      throw new Error("resposta perdida");
    });
    await open(); select();
    fireEvent.click(screen.getByRole("button", { name: "Analisar conjunto" }));
    await screen.findByText("Conjunto na fila de processamento");
    expect(api.put).toHaveBeenCalledTimes(2);
  });

  it("retoma processamento sem reenviar os arquivos já recebidos", async () => {
    stored = { ...pendingJob(), status: "failed", arquivos: pendingJob().arquivos.map((item, index) => ({ ...item, status: index ? "failed" : "completed" })) };
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Retomar arquivos que falharam" }));
    await screen.findByText("Conjunto na fila de processamento");
    expect(api.put).not.toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/batch-1/retomar"), {}, expect.anything());
  });

  it("distingue retomada da análise quando todas as fontes já foram concluídas", async () => {
    stored = { ...pendingJob(), status: "failed", arquivos: pendingJob().arquivos.map((item) => ({ ...item, status: "completed" })) };
    await open();
    expect(screen.queryByRole("button", { name: "Retomar arquivos que falharam" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retomar análise do conjunto" }));
    await screen.findByText("Conjunto na fila de processamento");
    expect(api.put).not.toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/batch-1/retomar"), {}, expect.anything());
  });

  it("recupera envio após reload e pede apenas o arquivo ausente", async () => {
    stored = pendingJob(); stored.arquivos[1].status = "uploaded";
    await open();
    expect(screen.getByText(/Selecione novamente este arquivo/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Selecionar novamente arquivos pendentes"), { target: { files: [files[0]] } });
    fireEvent.click(screen.getByRole("button", { name: "Retomar envio dos arquivos" }));
    await screen.findByText("Conjunto na fila de processamento");
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.put).mock.calls[0][0]).toContain("file-0");
  });

  it("recupera criação aceita com resposta perdida sem criar outro conjunto", async () => {
    vi.mocked(api.post).mockImplementation(async (url, payload) => {
      if (String(url).endsWith("/lotes")) {
        stored = { ...pendingJob(), arquivos: (payload as { arquivos: AssistenteLote["arquivos"] }).arquivos.map((item) => ({ ...item, status: "pending", erro: null })) };
        throw new Error("Resposta perdida após criar");
      }
      stored!.status = "queued";
      return response();
    });
    await open(); select();
    fireEvent.click(screen.getByRole("button", { name: "Analisar conjunto" }));
    await screen.findByText("Resposta perdida após criar");
    fireEvent.click(screen.getByRole("button", { name: "Analisar conjunto" }));
    await screen.findByText("Conjunto na fila de processamento");
    expect(vi.mocked(api.post).mock.calls.filter(([url]) => String(url).endsWith("/lotes"))).toHaveLength(1);
    expect(api.put).toHaveBeenCalledTimes(2);
  });

  it("exige seleção por fonte quando dois pendentes têm nome e tamanho iguais", async () => {
    stored = pendingJob();
    stored.arquivos[1] = { ...stored.arquivos[0], id: "file-1" };
    await open();
    fireEvent.change(screen.getByLabelText("Selecionar novamente arquivos pendentes"), { target: { files: [files[0]] } });
    expect(screen.getByText(/Há arquivos com o mesmo nome e tamanho/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Original da fonte 1: trecho-01.mp3"), { target: { files: [files[0]] } });
    fireEvent.click(screen.getByRole("button", { name: "Retomar envio dos arquivos" }));
    await screen.findByText(/Envio pendente de 1 arquivo/);
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.put).mock.calls[0][0]).toContain("file-0");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("exige consentimento e rejeita seleção acima do limite", async () => {
    await open({ consentimento: false }); select();
    expect((screen.getByRole("button", { name: "Analisar conjunto" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
    select(Array.from({ length: 5 }, (_, i) => new File(["audio"], `audio-${i}.mp3`)));
    expect(screen.getByText("Selecione até cinco áudios por conjunto.")).toBeTruthy();
  });

  it("permite sair de conjunto que expirou antes de confirmar novo", async () => {
    stored = pendingJob();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Preparar novo conjunto" }));
    vi.mocked(api.get).mockRejectedValue({ response: { status: 410, data: { detail: "Conjunto expirado." } } });
    fireEvent.click(screen.getByRole("button", { name: "Encerrar conjunto" }));
    await waitFor(() => expect(screen.queryByText("Enviando fontes do conjunto")).toBeNull());
    expect(screen.getByLabelText("Áudios e PDFs do conjunto")).toBeTruthy();
    expect(api.delete).not.toHaveBeenCalled();
  });

  it("pausa polling durante a remoção e só limpa a tela após confirmar DELETE", async () => {
    vi.useFakeTimers();
    stored = { ...pendingJob(), status: "processing" };
    const handlers = props();
    await act(async () => { render(<AtendimentoAssistenteLote {...handlers} />); });
    expect(screen.getByText("Analisando áudios e exames")).toBeTruthy();

    const reads: Array<(value: ReturnType<typeof response>) => void> = [];
    vi.mocked(api.get).mockImplementation(() => new Promise((resolve) => { reads.push(resolve); }));
    let completeDelete!: () => void;
    vi.mocked(api.delete).mockImplementation(() => new Promise((resolve) => {
      completeDelete = () => { stored = null; resolve({ data: null }); };
    }));
    fireEvent.click(screen.getByRole("button", { name: "Preparar novo conjunto" }));
    fireEvent.click(screen.getByRole("button", { name: "Encerrar conjunto" }));
    expect(reads).toHaveLength(1);

    // A polling tick here used to supersede the removal read and skip DELETE.
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await act(async () => { reads[0](response()); });
    expect(api.delete).toHaveBeenCalledWith(expect.stringContaining("/batch-1"), expect.anything());
    expect(reads).toHaveLength(1);
    expect(screen.getByText("Analisando áudios e exames")).toBeTruthy();
    expect(screen.queryByLabelText("Áudios e PDFs do conjunto")).toBeNull();

    await act(async () => { completeDelete(); });
    expect(screen.queryByText("Analisando áudios e exames")).toBeNull();
    expect(screen.getByLabelText("Áudios e PDFs do conjunto")).toBeTruthy();
  });

  it("preserva remoção incerta e confirma ausência antes de limpar após resposta perdida", async () => {
    stored = pendingJob();
    await open();
    vi.mocked(api.delete).mockImplementation(async () => {
      stored = null;
      throw new Error("Resposta perdida após excluir");
    });
    fireEvent.click(screen.getByRole("button", { name: "Preparar novo conjunto" }));
    fireEvent.click(screen.getByRole("button", { name: "Encerrar conjunto" }));
    await screen.findByText("Resposta perdida após excluir");
    expect(api.delete).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Enviando fontes do conjunto")).toBeTruthy();
    expect(screen.queryByLabelText("Áudios e PDFs do conjunto")).toBeNull();

    vi.mocked(api.get).mockRejectedValue({ response: { status: 410, data: { detail: "Conjunto excluído." } } });
    fireEvent.click(screen.getByRole("button", { name: "Encerrar conjunto" }));
    await screen.findByLabelText("Áudios e PDFs do conjunto");
    expect(screen.queryByText("Enviando fontes do conjunto")).toBeNull();
    expect(api.delete).toHaveBeenCalledTimes(1);
  });

  it("descarta consulta que chega após desmontagem", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(api.get).mockImplementation(() => new Promise((done) => { resolve = done; }));
    const handlers = props();
    const view = render(<AtendimentoAssistenteLote {...handlers} />);
    view.unmount();
    await act(async () => resolve({ data: { ...pendingJob(), status: "completed", resultado: result } }));
    expect(handlers.onReview).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });
});
