import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EditarLaudoPage from "./[id]/editar/page";
import { montarDescricaoEcocardiograma, criarEcocardiogramaEstruturadoInicial } from "@/lib/ecocardiograma-estruturado";
import type { EchoEditorDraftResponse } from "@/lib/echo-editor-draft";
import { makePulmonaryReviewStamp } from "@/lib/echo-pulmonary-probability";

const qa = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn(),
  router: { push: vi.fn(), replace: vi.fn() }, id: "905", records: new Map<string, EchoEditorDraftResponse>(),
  apply: null as null | ((patch: { fields: Record<string, string>; measurements: Record<string, string>; skipped: string[] }) => void),
  imported: null as null | ((data: unknown) => void),
  upload: null as null | { sessionId: string; onImagensChange: (images: any[]) => void; onUploadStateChange: (active: boolean) => void },
}));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: qa.id }), useRouter: () => qa.router }));
vi.mock("@/app/layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("@/lib/axios", () => ({ default: qa }));
vi.mock("@/lib/clinicas", () => ({ listarTodasClinicas: vi.fn(async () => [{ id: 3, nome: "CLÍNICA QA" }]) }));
vi.mock("@/app/laudos/components/EchoVoiceAssistant", () => ({ default: ({ currentMeasurements, onApply }: {
  currentMeasurements: Record<string, string>; onApply: NonNullable<typeof qa.apply>;
}) => { qa.apply = onApply; return <output data-testid="measurements">{JSON.stringify(currentMeasurements)}</output>; } }));
vi.mock("@/app/laudos/components/EcoStudyImportUploader", () => ({ default: ({ onDadosImportados }: { onDadosImportados: (data: unknown) => void }) => {
  qa.imported = onDadosImportados; return null;
} }));
vi.mock("@/app/laudos/components/XmlUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageHeaderUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageUploader", () => ({ default: (props: {
  imagensIniciais: unknown[]; sessionId: string; onImagensChange: (images: any[]) => void; onUploadStateChange: (active: boolean) => void;
}) => { qa.upload = props; return <><output data-testid="temp-images">{JSON.stringify(props.imagensIniciais)}</output>
  <button onClick={() => props.onUploadStateChange(true)}>Iniciar leitura QA</button></>; } }));
vi.mock("@/app/laudos/components/ImagePreviewModal", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoEditor", () => ({ default: ({ estado, onChange }: {
  estado: ReturnType<typeof criarEcocardiogramaEstruturadoInicial>; onChange: (v: unknown) => void;
}) => <button onClick={() => onChange({ ...estado, usar_no_laudo: true,
  textos: { funcao_diastolica: "Texto estruturado QA.", conclusao: "Conclusão estruturada QA." } })}>Aplicar estrutura QA</button> }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoBiblioteca", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoNarrativeConsistencyNotice", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoUnitReview", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ReferenciaComparison", () => ({ ReferenciaComparison: () => null }));

const REV = "echo-v1:" + "a".repeat(64);
const measures = { Aorta: "10", Atrio_esquerdo: "14", AE_Ao: "1.40", Onda_E: "", Onda_A: "0",
  E_A: "1.13", Diastolica_ondas: "fundidas", TDI_ondas: "nao_confirmadas" };
const patient = { id: 901, tutor_id: 902, nome: "QA ECO EXISTENTE", tutor: "QA TUTOR", telefone: "",
  especie: "Gato", sexo: "Macho", raca: "SRD", idade: "12 anos", peso_kg: 4.8 };
let official: Record<string, any>;
const failure = (status: number, detail?: unknown) => ({ response: { status, data: { detail } } });
const pending = <T,>() => { let resolve!: (v: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; };
function input(label: string) {
  const element = screen.getByText(label, { selector: "label" }).parentElement?.querySelector("input");
  expect(element).not.toBeNull(); return element as HTMLInputElement;
}
const lastSnapshot = () => [...qa.records.values()].at(-1)!.snapshot;
const updates = () => qa.put.mock.calls.filter(([url]) => String(url).endsWith("/editor-update"));
const privateWritesOnly = () => [...qa.put.mock.calls, ...qa.post.mock.calls, ...qa.delete.mock.calls]
  .every(([url]) => String(url).startsWith("/laudos/editor-drafts/"));
async function open() {
  const view = render(<EditarLaudoPage />);
  await screen.findByDisplayValue(patient.nome);
  await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
  return view;
}
async function saveDraft() {
  fireEvent.click(screen.getByRole("button", { name: "Salvar rascunho" }));
  await screen.findByText(/Rascunho salvo às/);
}

describe("ecocardiograma existente: cópia privada e atualização explícita", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); qa.records.clear(); qa.id = "905";
    localStorage.setItem("token", "qa-token"); localStorage.setItem("user", JSON.stringify({ id: 7 }));
    window.history.replaceState(null, "", "/laudos/905/editar");
    vi.spyOn(window, "confirm").mockReturnValue(true); vi.spyOn(window, "alert").mockImplementation(() => {});
    official = { id: 905, editor_revision: REV, tipo: "ecocardiograma", paciente_id: 901, paciente: patient,
      titulo: "QA DOCUMENTO OFICIAL", diagnostico: "Conclusão oficial QA.", observacoes: "Observação oficial.", status: "Finalizado",
      data_exame: "2026-10-27", medidas: measures, descricao: montarDescricaoEcocardiograma(measures,
        { valvas: "", camaras: "", funcao: "", pericardio: "", vasos: "", ad_vd: "" }), imagens: [] };
    qa.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/laudos/editor-drafts/")) {
        const record = qa.records.get(url.split("/").at(-1)!);
        if (!record) throw failure(404); return { data: structuredClone(record) };
      }
      if (/^\/laudos\/\d+$/.test(url)) return { data: structuredClone(official) };
      if (url === "/portal/parceiros/veterinarios/opcoes") return { data: { items: [] } };
      if (url.startsWith("/imagens/temp/session/")) return { data: { items: [] } };
      if (url.startsWith("/imagens/")) return { data: new Blob(["qa"]) };
      throw new Error(`Unexpected GET ${url}`);
    });
    qa.put.mockImplementation(async (url: string, body) => {
      if (url.startsWith("/laudos/editor-drafts/")) {
        const id = url.split("/").at(-1)!;
        const record = { draft_id: id, revision: body.expected_revision + 1, context_key: body.context_key,
          snapshot: structuredClone(body.snapshot), updated_at: "2026-11-01T12:00:00Z" };
        qa.records.set(id, record); return { data: record };
      }
      if (url.endsWith("/editor-update")) return { data: { id: 905, request_id: body.request_id, updated: true } };
      throw new Error(`Unexpected PUT ${url}`);
    });
    qa.post.mockImplementation(async (url: string, body) => ({ data: {
      draft_id: url.split("/").at(-2), closed: true, revision: body.expected_revision + 1 } }));
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });

  it("prévia preserva o oficial e compartilha payload, cadastro e imagens com a atualização explícita", async () => {
    vi.stubGlobal("URL", Object.assign(class extends URL {}, {
      createObjectURL: vi.fn(() => "blob:qa-existing-preview"), revokeObjectURL: vi.fn(),
    }));
    const original = qa.post.getMockImplementation()!;
    qa.post.mockImplementation((url, ...args) => String(url).endsWith("/preview")
      ? Promise.resolve({ data: new Blob(["%PDF-1.4\nQA"], { type: "application/pdf" }) }) : original(url, ...args));
    official.imagens = [2, 1].map((id, index) => ({ id, nome: `qa-${id}.png`, ordem: index,
      descricao: `Legenda ${id}`, url: `/imagens/${id}`, tamanho: 10, incluir_no_pdf: id === 2 }));
    const view = await open();
    fireEvent.change(input("Nome do Paciente"), { target: { value: "QA ALTERAÇÃO PRIVADA" } });
    fireEvent.click(screen.getByRole("button", { name: "Conferir e ver PDF" }));
    await screen.findByTitle("Prévia do laudo em PDF — rascunho");
    const preview = qa.post.mock.calls.find(([url]) => String(url).endsWith("/preview"))!;
    expect(preview[1]).toMatchObject({ expected_revision: expect.any(Number), paciente: { nome: "QA ALTERAÇÃO PRIVADA" },
      payload_laudo: { diagnostico: "Conclusão oficial QA.", aplicar_conclusao_estruturada: false,
        aplicar_qualitativa_estruturada: false, clinic_id: null },
      imagens: { persistidas: [{ id: 2, ordem: 0, descricao: "Legenda 2", incluir_no_pdf: true },
        { id: 1, ordem: 1, descricao: "Legenda 1", incluir_no_pdf: false }], temp_config: [], removidas_ids: [] } });
    expect(preview[2]).toMatchObject({ responseType: "blob", headers: { "X-Editor-Owner-Id": 7 } });
    expect(updates()).toEqual([]); expect(privateWritesOnly()).toBe(true);
    expect(official.paciente.nome).toBe(patient.nome);
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await waitFor(() => expect(updates()).toHaveLength(1));
    const body = updates()[0][1];
    expect(body.payload_laudo).toEqual(preview[1].payload_laudo);
    expect(body.paciente).toEqual(preview[1].paciente);
    expect(body.imagens).toEqual(preview[1].imagens);
    view.unmount();
  });

  it("salva e retoma valores literais, status e flags sem modificar o documento oficial", async () => {
    let view = await open();
    fireEvent.change(input("Nome do Paciente"), { target: { value: "QA CÓPIA PRIVADA" } });
    await saveDraft();
    expect(lastSnapshot()).toMatchObject({ editor: "existing-echo", source: { laudo_id: 905, editor_revision: REV },
      conteudo: { status: "Finalizado" }, existing: { qualitativaAplicada: false, conclusaoAplicada: false },
      measurementState: { measurements: { Onda_E: "", Onda_A: "0", E_A: "1.13", Diastolica_ondas: "fundidas" } } });
    expect(privateWritesOnly()).toBe(true);
    view.unmount(); view = render(<EditarLaudoPage />);
    const resume = await screen.findByRole("button", { name: "Retomar rascunho" });
    expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeDisabled();
    fireEvent.click(resume); await screen.findByDisplayValue("QA CÓPIA PRIVADA");
    expect(JSON.parse(screen.getByTestId("measurements").textContent!)).toMatchObject(measures);
    expect(privateWritesOnly()).toBe(true); view.unmount();
  });

  it("recupera a avaliação de HP na cópia privada sem alterar a conclusão e envia a revisão na atualização explícita", async () => {
    const hp = { HP_ativa: "sim", HP_TRV: "adequado", HP_VSVD: "sem_obstrucao", HP_suporte_automatico: "sim",
      HP_ventriculos: "sem_sinais", HP_arteria_pulmonar: "sem_sinais", HP_atrio_cava: "sem_sinais", IT_Vmax: "3.2" };
    const stamp = makePulmonaryReviewStamp(hp, "Canina");
    official.paciente = { ...patient, especie: "Canina" };
    official.medidas = { ...measures, ...hp, HP_revisao: stamp };
    const view = await open();
    fireEvent.click(screen.getByRole("button", { name: "Medidas" }));
    expect(screen.getByText("Probabilidade intermediária de hipertensão pulmonar")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Observações da avaliação de HP (opcional)"), { target: { value: "QA observação HP\nSegunda linha." } });
    await saveDraft();
    expect(lastSnapshot().measurementState.measurements).toMatchObject({ HP_revisao: stamp, HP_observacoes: "QA observação HP\nSegunda linha." });
    expect(lastSnapshot().conteudo.diagnostico).toBe("Conclusão oficial QA.");
    expect(privateWritesOnly()).toBe(true);
    view.unmount(); render(<EditarLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
    expect(JSON.parse(screen.getByTestId("measurements").textContent!)).toMatchObject({ HP_revisao: stamp, HP_observacoes: "QA observação HP\nSegunda linha." });
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await waitFor(() => expect(updates()).toHaveLength(1));
    expect(updates()[0][1].payload_laudo.diagnostico).toBe("Conclusão oficial QA.");
    expect(updates()[0][1].payload_laudo.descricao).toContain('- HP_observacoes: "QA observação HP\\nSegunda linha."');
  });

  it("recupera flags estruturadas e o ditado não transforma Finalizado em Rascunho", async () => {
    const view = await open();
    act(() => qa.apply!({ fields: { funcao_diastolica: "Descrição QA." }, measurements: {}, skipped: [] }));
    await saveDraft();
    expect(lastSnapshot()).toMatchObject({ conteudo: { status: "Finalizado" }, existing: { qualitativaAplicada: true },
      ecocardiogramaEstruturado: { textos: { funcao_diastolica: "Descrição QA." } } });
    view.unmount(); render(<EditarLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await waitFor(() => expect(updates()).toHaveLength(1));
    expect(updates()[0][1].payload_laudo).toMatchObject({ status: "Finalizado", aplicar_qualitativa_estruturada: true });
  });

  it("preserva a cópia de origem obsoleta e bloqueia atualização sem rebase silencioso", async () => {
    const view = await open(); fireEvent.change(input("Nome do Paciente"), { target: { value: "QA NÃO PERDER" } });
    await saveDraft(); view.unmount(); official.editor_revision = "echo-v1:" + "b".repeat(64);
    const recovered = render(<EditarLaudoPage />);
    await screen.findByRole("button", { name: "Retomar rascunho" });
    expect(screen.queryByRole("button", { name: "Continuar com preenchimento atual" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retomar rascunho" }));
    await screen.findByDisplayValue("QA NÃO PERDER");
    expect(screen.getByText(/A versão oficial mudou desde/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeDisabled(); expect(updates()).toHaveLength(0);
    expect(lastSnapshot().source?.editor_revision).toBe(REV);
    fireEvent.click(screen.getByRole("button", { name: "Descartar alterações deste rascunho" }));
    await waitFor(() => expect(qa.router.push).toHaveBeenCalledWith("/laudos/905"));
    expect(qa.post.mock.calls).toHaveLength(1); expect(sessionStorage.length).toBe(0); expect(updates()).toHaveLength(0);
    recovered.unmount(); render(<EditarLaudoPage />); await screen.findByDisplayValue(patient.nome);
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
    expect(screen.queryByRole("button", { name: "Retomar rascunho" })).not.toBeInTheDocument();
  });

  it("configura e remove imagens existentes só no rascunho antes da atualização atômica", async () => {
    official.imagens = [1, 2].map((id) => ({ id, nome: `qa-${id}.png`, ordem: id - 1, descricao: "Original",
      url: `/imagens/${id}`, tamanho: 10, incluir_no_pdf: true }));
    await open(); fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    const caption = screen.getByRole("textbox", { name: "Legenda da imagem 1" });
    fireEvent.change(caption, { target: { value: "Legenda privada QA" } }); fireEvent.blur(caption);
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Incluir no PDF" })[0]);
    fireEvent.click(screen.getAllByTitle("Remover")[1]);
    await saveDraft(); expect(privateWritesOnly()).toBe(true); expect(qa.delete).not.toHaveBeenCalled();
    expect(lastSnapshot().existing).toMatchObject({ imagensRemovidas: [2], imagensPersistidas: [
      { serverId: 1, descricao: "Legenda privada QA", incluirNoPdf: false } ] });
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await waitFor(() => expect(updates()).toHaveLength(1));
    expect(updates()[0][1].imagens).toMatchObject({ removidas_ids: [2], persistidas: [
      { id: 1, ordem: 0, descricao: "Legenda privada QA", incluir_no_pdf: false } ] });
    expect(qa.post).not.toHaveBeenCalled();
  });

  it("envia só campos cadastrais alterados e preserva campos clínicos durante resposta pendente", async () => {
    await open(); fireEvent.change(input("Idade informada"), { target: { value: "13 anos" } });
    const slow = pending<{ data: unknown }>(); const original = qa.put.getMockImplementation()!;
    qa.put.mockImplementation((url, ...args) => url.endsWith("/editor-update") ? slow.promise : original(url, ...args));
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await waitFor(() => expect(updates()).toHaveLength(1));
    const body = updates()[0][1];
    expect(body.paciente).toEqual({ idade_informada: "13 anos", idade_fonte: "idade", idade_referencia: "2026-10-27", data_nascimento: null }); expect(body.tutor).toBeUndefined();
    expect(input("Nome do Paciente")).toBeDisabled();
    act(() => qa.apply!({ fields: { conclusao: "RESPOSTA TARDIA INVÁLIDA" }, measurements: { Onda_A: "9" }, skipped: [] }));
    expect(lastSnapshot().measurementState.measurements.Onda_A).toBe("0");
    expect(body.payload_laudo.diagnostico).toBe("Conclusão oficial QA.");
    await act(async () => slow.resolve({ data: { id: 905, request_id: body.request_id, updated: true } }));
    await waitFor(() => expect(qa.router.push).toHaveBeenCalledWith("/laudos/905"));
  });

  it("resposta incerta bloqueia novo PUT e reload410 confirma resultado sem trocar UUID", async () => {
    const view = await open(); const original = qa.put.getMockImplementation()!;
    qa.put.mockImplementation((url, ...args) => url.endsWith("/editor-update") ? Promise.reject(new Error("timeout")) : original(url, ...args));
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await screen.findByText(/Há uma tentativa de atualização sem resposta confirmada/);
    expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeDisabled();
    const body = updates()[0][1]; const id = body.editor_draft_id;
    view.unmount(); const get = qa.get.getMockImplementation()!;
    qa.get.mockImplementation((url, ...args) => url === `/laudos/editor-drafts/${id}`
      ? Promise.reject(failure(410, { code: "EDITOR_DRAFT_CLOSED", laudo_id: 905,
        apply_result: { id: 905, request_id: body.request_id, updated: true } })) : get(url, ...args));
    const recoveredView = render(<EditarLaudoPage />);
    await screen.findByText(/O servidor confirmou a atualização deste laudo/);
    expect(updates()).toHaveLength(1); expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeDisabled();
    expect([...qa.records.keys()]).toEqual([id]);
    fireEvent.click(screen.getByRole("button", { name: "Conferi o resultado; voltar ao laudo" }));
    await waitFor(() => expect(sessionStorage.length).toBe(0));
    recoveredView.unmount(); official.editor_revision = "echo-v1:" + "d".repeat(64);
    render(<EditarLaudoPage />); await screen.findByDisplayValue(patient.nome);
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
    expect(updates()).toHaveLength(1);
  });

  it("uma resposta tardia da origem não substitui o laudo da rota atual", async () => {
    const slow = pending<{ data: unknown }>(); const original = qa.get.getMockImplementation()!;
    qa.get.mockImplementation((url, ...args) => url === "/laudos/905" ? slow.promise : original(url, ...args));
    const view = render(<EditarLaudoPage />); qa.id = "906"; official = { ...official, id: 906, paciente: { ...patient, nome: "QA ROTA ATUAL" } };
    view.rerender(<EditarLaudoPage />); await screen.findByDisplayValue("QA ROTA ATUAL");
    await act(async () => slow.resolve({ data: { ...official, id: 905, paciente: patient } }));
    expect(screen.queryByDisplayValue(patient.nome)).not.toBeInTheDocument(); expect(privateWritesOnly()).toBe(true);
  });

  it("avisa antes de sair ou recarregar durante a leitura inicial de arquivos ainda sem metadados", async () => {
    await open(); fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    fireEvent.click(screen.getByRole("button", { name: "Iniciar leitura QA" }));
    expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeDisabled();
    const beforeUnload = new Event("beforeunload", { cancelable: true }); fireEvent(window, beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(true);
    vi.mocked(window.confirm).mockReturnValue(false);
    fireEvent.click(screen.getByRole("button", { name: "Voltar para o laudo" }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/imagens não recebidas/)));
    expect(qa.router.push).not.toHaveBeenCalled(); expect(updates()).toHaveLength(0);
  });

  it("rejeita aplicação com imagem temporária expirada, preservando seu metadado para reenvio", async () => {
    const view = await open(); await saveDraft();
    const record = [...qa.records.values()][0];
    record.snapshot.imagens = [{ id: "missing", nome: "qa.png", descricao: "Legenda QA", ordem: 0,
      tamanho: 12, uploaded: true, tempId: 41, incluirNoPdf: false }];
    view.unmount(); render(<EditarLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await screen.findByText(/Há imagens temporárias para reenviar/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await screen.findByText(/Reenvie ou remova as imagens pendentes/);
    expect(updates()).toHaveLength(0);
    expect(JSON.parse(screen.getByTestId("temp-images").textContent!)[0]).toMatchObject({
      uploaded: false, requerReenvio: true, descricao: "Legenda QA", incluirNoPdf: false });
  });

  it("troca do proprietário oculta o editor e impede autosave ou atualização na outra conta", async () => {
    await open(); await saveDraft(); qa.put.mockClear();
    localStorage.setItem("user", JSON.stringify({ id: 8 })); fireEvent(window, new Event("focus"));
    await screen.findByText(/A sessão do usuário mudou/);
    expect(screen.queryByRole("button", { name: "Atualizar laudo" })).not.toBeInTheDocument();
    expect(qa.put).not.toHaveBeenCalled(); expect(qa.post).not.toHaveBeenCalled();
  });

  it("alteração aguarda debounce e só salva workspace, sem ação de atualizar", async () => {
    await open(); fireEvent.change(input("Nome do Paciente"), { target: { value: "QA AUTOSAVE" } });
    await waitFor(() => expect(qa.records.size).toBe(1), { timeout: 2500 });
    expect(lastSnapshot().paciente.nome).toBe("QA AUTOSAVE"); expect(privateWritesOnly()).toBe(true);
  });

  it("sucesso confirmado retira ponteiro sem close extra e permite próxima edição pela origem atual", async () => {
    const view = await open(); fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await waitFor(() => expect(qa.router.push).toHaveBeenCalledWith("/laudos/905"));
    expect(sessionStorage.length).toBe(0); expect(qa.post).not.toHaveBeenCalled();
    view.unmount(); official.editor_revision = "echo-v1:" + "c".repeat(64);
    render(<EditarLaudoPage />); await screen.findByDisplayValue(patient.nome);
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
    expect(screen.queryByRole("button", { name: "Retomar rascunho" })).not.toBeInTheDocument();
    expect(updates()).toHaveLength(1);
  });

  it("ignora imagens, atividade, importação e ditado da rota anterior após abrir outro laudo", async () => {
    const view = await open(); fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    const oldUpload = qa.upload!; const oldApply = qa.apply!; const oldImport = qa.imported!;
    qa.id = "906"; official = { ...official, id: 906, paciente: { ...patient, nome: "QA NOVO CONTEXTO" } };
    view.rerender(<EditarLaudoPage />); await screen.findByDisplayValue("QA NOVO CONTEXTO");
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
    act(() => {
      oldUpload.onImagensChange([{ id: "old", nome: "OUTRO-PACIENTE.png", descricao: "", ordem: 0,
        tamanho: 12, uploaded: true, tempId: 42 }]); oldUpload.onUploadStateChange(true);
      oldApply({ fields: { conclusao: "OUTRO PACIENTE" }, measurements: { Onda_A: "9" }, skipped: [] });
      oldImport({ paciente: { nome: "OUTRO PACIENTE" }, medidas: { Onda_A: "8" } });
    });
    await saveDraft(); const saved = lastSnapshot();
    expect(saved.source?.laudo_id).toBe(906); expect(saved.paciente.nome).toBe("QA NOVO CONTEXTO");
    expect(saved.imagens).toEqual([]); expect(saved.sessionId).not.toBe(oldUpload.sessionId);
    expect(saved.measurementState.measurements.Onda_A).toBe("0");
    expect(saved.conteudo.diagnostico).toBe("Conclusão oficial QA.");
    expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled();
  });

  it("temporárias expiram no apply409 e podem ser removidas antes de uma nova atualização", async () => {
    await open(); fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    act(() => qa.upload!.onImagensChange([{ id: "temp", nome: "qa.png", descricao: "QA", ordem: 0,
      tamanho: 12, uploaded: true, tempId: 42, incluirNoPdf: true }]));
    const original = qa.put.getMockImplementation()!;
    let rejected = false;
    qa.put.mockImplementation((url, ...args) => {
      if (url.endsWith("/editor-update") && !rejected) {
        rejected = true; return Promise.reject(failure(409, { code: "TEMP_IMAGES_UNAVAILABLE", message: "Temporárias expiradas QA." }));
      }
      return original(url, ...args);
    });
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await screen.findByText("Temporárias expiradas QA.");
    expect(screen.queryByText(/A versão oficial mudou desde/)).not.toBeInTheDocument();
    expect(JSON.parse(screen.getByTestId("temp-images").textContent!)[0]).toMatchObject({ uploaded: false, requerReenvio: true });
    act(() => qa.upload!.onImagensChange([]));
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar laudo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await waitFor(() => expect(updates()).toHaveLength(2));
    await waitFor(() => expect(qa.router.push).toHaveBeenCalledWith("/laudos/905"));
    expect(updates()[1][1].imagens.temp_config).toEqual([]);
    expect(updates()[1][1].request_id).not.toBe(updates()[0][1].request_id);
  });

  it("limpeza explícita de clínica e médico corresponde ao snapshot congelado e ao update", async () => {
    official.clinic_id = 3; official.clinica = "CLÍNICA QA"; official.medico_solicitante = "MÉDICO QA";
    await open();
    const clinic = screen.getByText("Clínica", { selector: "label" }).parentElement!.querySelector("select")!;
    expect(clinic).toHaveValue("3"); expect(input("Veterinário Solicitante")).toHaveValue("MÉDICO QA");
    fireEvent.change(clinic, { target: { value: "" } });
    fireEvent.change(input("Veterinário Solicitante"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Atualizar laudo" }));
    await waitFor(() => expect(updates()).toHaveLength(1));
    expect(lastSnapshot()).toMatchObject({ clinicaId: "", conteudo: { medicoSolicitante: "" } });
    expect(updates()[0][1].payload_laudo).toMatchObject({ clinic_id: null, medico_solicitante: "" });
    expect(updates()[0][1].paciente).toBeUndefined(); expect(updates()[0][1].tutor).toBeUndefined();
  });
});
