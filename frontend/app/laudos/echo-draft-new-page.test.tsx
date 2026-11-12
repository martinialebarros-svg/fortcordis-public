import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NovoLaudoPage from "./novo/page";
import type { EchoEditorDraftResponse, EchoEditorDraftSnapshot } from "@/lib/echo-editor-draft";

const mocks = vi.hoisted(() => ({
  get: vi.fn(), put: vi.fn(), post: vi.fn(), router: { push: vi.fn() },
  records: new Map<string, EchoEditorDraftResponse>(), imported: {} as Record<string, string>,
}));
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));
vi.mock("@/app/layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("@/lib/axios", () => ({ default: mocks }));
vi.mock("@/lib/clinicas", () => ({ listarTodasClinicas: vi.fn(async () => []) }));
vi.mock("@/app/laudos/components/EchoVoiceAssistant", () => ({ default: ({ resolveLaudoId }: { resolveLaudoId: () => Promise<number> }) =>
  <button onClick={() => { void resolveLaudoId().catch(() => {}); }}>Preparar ditado sintético</button> }));
vi.mock("@/app/laudos/components/EcoStudyImportUploader", () => ({ default: ({ onDadosImportados }: { onDadosImportados: (v: unknown) => void }) =>
  <button onClick={() => onDadosImportados({ paciente: {}, medidas: mocks.imported })}>Importar estudo sintético</button> }));
vi.mock("@/app/laudos/components/XmlUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageHeaderUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageUploader", () => ({ default: ({ imagensIniciais }: { imagensIniciais: unknown[] }) =>
  <output data-testid="draft-images">{JSON.stringify(imagensIniciais)}</output> }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoEditor", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoBiblioteca", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoNarrativeConsistencyNotice", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoUnitReview", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ReferenciaComparison", () => ({ ReferenciaComparison: ({ medidas }: { medidas: unknown }) =>
  <output data-testid="draft-measurements">{JSON.stringify(medidas)}</output> }));

const patient = { id: 901, nome: "QA RASCUNHO", tutor: "QA", especie: "Felina", sexo: "Macho", peso_kg: 4.8, raca: "SRD", idade: "12 anos" };
const failure = (status: number) => ({ response: { status } });
const deferred = <T,>() => { let resolve!: (v: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; };
function input(label: string) {
  const field = screen.getByText(label, { selector: "label" }).parentElement?.querySelector("input");
  expect(field).not.toBeNull(); return field as HTMLInputElement;
}
const lastSnapshot = () => [...mocks.records.values()].at(-1)!.snapshot;
const draftWrites = () => mocks.put.mock.calls.filter(([url]) => String(url).startsWith("/laudos/editor-drafts/"));
const clinicalWrites = () => [...mocks.put.mock.calls, ...mocks.post.mock.calls]
  .filter(([url]) => /^\/laudos(?:\/\d+)?$|^\/(pacientes|tutores)\//.test(String(url)));
async function open() {
  const view = render(<NovoLaudoPage />);
  await screen.findByDisplayValue(patient.nome);
  await waitFor(() => expect(screen.getByRole("button", { name: "Salvar rascunho" })).toBeEnabled());
  return view;
}
async function saveDraft() {
  fireEvent.click(screen.getByRole("button", { name: "Salvar rascunho" }));
  await screen.findByText(/Rascunho salvo às/);
}

describe("novo ecocardiograma: recuperação e emissão explícita", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); mocks.records.clear(); mocks.imported = {};
    localStorage.setItem("token", "qa-token"); localStorage.setItem("user", JSON.stringify({ id: 7 }));
    window.history.replaceState(null, "", "/laudos/novo?paciente_id=901");
    vi.spyOn(window, "confirm").mockReturnValue(true); vi.spyOn(window, "alert").mockImplementation(() => {});
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/pacientes/901") return { data: patient };
      if (url.startsWith("/laudos/editor-drafts/")) {
        const record = mocks.records.get(url.split("/").at(-1)!);
        if (record) return { data: structuredClone(record) };
        throw failure(404);
      }
      if (url.startsWith("/imagens/temp/session/")) return { data: { items: [] } };
      throw new Error(`Unexpected GET ${url}`);
    });
    mocks.put.mockImplementation(async (url: string, body) => {
      if (url.startsWith("/laudos/editor-drafts/")) {
        const id = url.split("/").at(-1)!;
        const response = { draft_id: id, revision: body.expected_revision + 1, context_key: body.context_key,
          snapshot: structuredClone(body.snapshot), updated_at: "2026-11-01T12:00:00Z" };
        mocks.records.set(id, response); return { data: response };
      }
      return { data: { id: 905 } };
    });
    mocks.post.mockImplementation(async (url: string, body) => {
      if (url.endsWith("/close")) return { data: { draft_id: url.split("/").at(-2), closed: true, revision: body.expected_revision + 1 } };
      return { data: { id: 905 } };
    });
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); window.history.replaceState(null, "", "/"); });

  it("prévia usa o mesmo payload da emissão, salva só a cópia privada e não emite ao conferir", async () => {
    vi.stubGlobal("URL", Object.assign(class extends URL {}, {
      createObjectURL: vi.fn(() => "blob:qa-preview"), revokeObjectURL: vi.fn(),
    }));
    const original = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url, ...args) => String(url).endsWith("/preview")
      ? Promise.resolve({ data: new Blob(["%PDF-1.4\nQA"], { type: "application/pdf" }) }) : original(url, ...args));
    const view = await open();
    mocks.imported = { DIVEd: "25", DIVES: "12", Onda_E: "0.9", Onda_A: "0.7" };
    fireEvent.click(screen.getByRole("button", { name: "Importar estudo sintético" }));
    fireEvent.click(screen.getByRole("button", { name: "Conferir e ver PDF" }));
    await screen.findByTitle("Prévia do laudo em PDF — rascunho");
    const preview = mocks.post.mock.calls.find(([url]) => String(url).endsWith("/preview"))!;
    expect(preview[1]).toMatchObject({ expected_revision: expect.any(Number),
      payload_laudo: { paciente: { nome: patient.nome }, medidas: { DIVEd: "25", Onda_E: "0.9" } },
      imagens: { persistidas: [], temp_config: [], temp_session_id: lastSnapshot().sessionId } });
    expect(preview[2]).toMatchObject({ responseType: "blob", headers: { "X-Editor-Owner-Id": 7 } });
    expect(clinicalWrites()).toEqual([]);
    expect(mocks.router.push).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Emitir laudo" }));
    await waitFor(() => expect(mocks.post.mock.calls.some(([url]) => url === "/laudos")).toBe(true));
    expect(mocks.post.mock.calls.find(([url]) => url === "/laudos")![1]).toEqual(preview[1].payload_laudo);
    view.unmount();
  });

  it("edição invalida uma prévia pronta e a navegação abre a seção correspondente", async () => {
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(class extends URL {}, {
      createObjectURL: vi.fn(() => "blob:qa-preview"), revokeObjectURL: revoke,
    }));
    mocks.post.mockResolvedValue({ data: new Blob(["%PDF-1.4\nQA"], { type: "application/pdf" }) });
    const view = await open();
    fireEvent.click(screen.getByRole("button", { name: "Conferir e ver PDF" }));
    await screen.findByTitle("Prévia do laudo em PDF — rascunho");
    fireEvent.change(input("Nome do Paciente"), { target: { value: "QA NOME REVISTO" } });
    await screen.findByText(/O conteúdo mudou/);
    expect(screen.queryByTitle("Prévia do laudo em PDF — rascunho")).not.toBeInTheDocument();
    expect(revoke).toHaveBeenCalledWith("blob:qa-preview");
    fireEvent.click(screen.getByText(/ponto\(s\) para conferir/));
    fireEvent.click(screen.getByRole("button", { name: "Revisar PDF sem imagens selecionadas" }));
    await screen.findByTestId("draft-images");
    expect(document.querySelector('[data-echo-review-target="images"]')).toBeInTheDocument();
    expect(clinicalWrites()).toEqual([]);
    view.unmount();
  });

  it("aviso diastólico abre a aba Medidas e leva o foco ao seletor de ondas", async () => {
    const view = await open();
    mocks.imported = { Onda_E: "0.9", Onda_A: "0.7" };
    fireEvent.click(screen.getByRole("button", { name: "Importar estudo sintético" }));
    fireEvent.click(screen.getByText(/ponto\(s\) para conferir/));
    fireEvent.click(screen.getByRole("button", { name: "Revisar Ondas transmitrais E/A" }));
    const wave = await screen.findByLabelText("Ondas transmitrais E/A");
    await waitFor(() => expect(wave).toHaveFocus());
    expect(clinicalWrites()).toEqual([]);
    view.unmount();
  });

  it("salva só workspace e recupera literalmente medidas importadas sem criar laudo ou cadastro", async () => {
    let view = await open();
    mocks.imported = { Aorta: "10", Atrio_esquerdo: "14", AE_Ao: "1.46", AE_Ao_metodo: "",
      Onda_E: "", MV_E: "1.8", Onda_A: "0", Diastolica_ondas: "fundidas", TDI_ondas: "nao_confirmadas", TDI_metodo: "" };
    fireEvent.click(screen.getByRole("button", { name: "Importar estudo sintético" }));
    fireEvent.click(screen.getByRole("button", { name: "Medidas" }));
    fireEvent.change(input("Onda E (m/s)"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Ondas transmitrais E/A"), { target: { value: "fundidas" } });
    await saveDraft(); const snapshot = structuredClone(lastSnapshot());
    expect(snapshot.measurementState.measurements).toMatchObject({ AE_Ao: "1.46", Onda_E: "", Onda_A: "0", Diastolica_ondas: "fundidas" });
    expect(snapshot.measurementState.aeAoDerived).toBe(false);
    expect(clinicalWrites()).toEqual([]);
    view.unmount(); view = render(<NovoLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Referências" }));
    expect(JSON.parse(screen.getByTestId("draft-measurements").textContent!)).toMatchObject(snapshot.measurementState.measurements);
    expect(clinicalWrites()).toEqual([]);
    view.unmount();
  });

  it("espera a origem carregar antes de oferecer recuperação e impede resposta tardia de apagar a cópia", async () => {
    const first = await open(); fireEvent.change(input("Nome do Paciente"), { target: { value: "QA RESTAURADO" } });
    await saveDraft(); first.unmount();
    const slow = deferred<{ data: typeof patient }>(); const original = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url, ...args) => url === "/pacientes/901" ? slow.promise : original(url, ...args));
    render(<NovoLaudoPage />);
    expect(screen.queryByRole("button", { name: "Retomar rascunho" })).not.toBeInTheDocument();
    expect(input("Nome do Paciente")).toBeDisabled();
    await act(async () => slow.resolve({ data: patient }));
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await screen.findByDisplayValue("QA RESTAURADO");
    expect(clinicalWrites()).toEqual([]);
  });

  it("falha do autosave preserva edição e permite corrigir campos sem tocar documento oficial", async () => {
    await open(); mocks.put.mockRejectedValueOnce(failure(503));
    fireEvent.change(input("Nome do Paciente"), { target: { value: "QA ALTERADO" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar rascunho" }));
    await screen.findByText("O rascunho precisa de atenção.");
    expect(input("Nome do Paciente")).toBeEnabled();
    fireEvent.change(input("Nome do Paciente"), { target: { value: "QA CORRIGIDO" } });
    expect(input("Nome do Paciente")).toHaveValue("QA CORRIGIDO");
    expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeDisabled();
    expect(clinicalWrites()).toEqual([]);
  });

  it("marca imagens expiradas para reenvio e não as anuncia como recebidas", async () => {
    const view = await open(); await saveDraft();
    const record = [...mocks.records.values()][0];
    record.snapshot.imagens = [{ id: "lost", nome: "qa.jpg", uploaded: true, tempId: 42, tamanho: 12, ordem: 0, descricao: "AE", incluirNoPdf: false }];
    view.unmount(); render(<NovoLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await screen.findByText(/1 imagem\(ns\) não puderam ser recuperadas/);
    fireEvent.click(screen.getByRole("button", { name: "Imagens" }));
    expect(JSON.parse(screen.getByTestId("draft-images").textContent!)[0]).toMatchObject({ uploaded: false, requerReenvio: true, descricao: "AE", incluirNoPdf: false });
    fireEvent.click(screen.getByRole("button", { name: "Emitir laudo" }));
    await screen.findByText(/Há imagens com envio pendente/);
    expect(clinicalWrites()).toEqual([]);
  });

  it("não aplica recuperação de imagem após a sessão do proprietário mudar", async () => {
    const view = await open(); await saveDraft();
    const record = [...mocks.records.values()][0];
    record.snapshot.paciente.nome = "QA OUTRO CONTEXTO";
    record.snapshot.imagens = [{ id: "late", nome: "qa.jpg", uploaded: true, tempId: 42, tamanho: 12, ordem: 0, descricao: "", incluirNoPdf: true }];
    const slow = deferred<{ data: Blob }>(); const original = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url, ...args) => url.startsWith("/imagens/temp/session/") ? Promise.resolve({ data: { items: [{ id: 42 }] } })
      : url === "/imagens/temp/42" ? slow.promise : original(url, ...args));
    view.unmount(); render(<NovoLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await waitFor(() => expect(mocks.get.mock.calls.some(([url]) => url === "/imagens/temp/42")).toBe(true));
    localStorage.setItem("user", JSON.stringify({ id: 8 }));
    await act(async () => slow.resolve({ data: new Blob(["qa"]) }));
    await screen.findByText(/A sessão mudou durante a recuperação/);
    expect(screen.queryByDisplayValue("QA OUTRO CONTEXTO")).not.toBeInTheDocument();
    expect(clinicalWrites()).toEqual([]);
  });

  it("emite somente por ação explícita depois de confirmar snapshot e encerra cópia", async () => {
    await open(); await saveDraft(); expect(clinicalWrites()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Emitir laudo" }));
    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/laudos"));
    expect(mocks.post.mock.calls.filter(([url]) => url === "/laudos")).toHaveLength(1);
    expect(mocks.post.mock.calls.find(([url]) => url === "/laudos")![1].status).toBe("Finalizado");
    expect(draftWrites().some(([, body]) => body.snapshot.submission?.status === "pending")).toBe(true);
    expect(mocks.post.mock.calls.some(([url]) => url.endsWith("/close"))).toBe(true);
  });

  it("resposta incerta da emissão mantém guarda recuperável e não repete POST clínico", async () => {
    const view = await open(); const original = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url, ...args) => url === "/laudos" ? Promise.reject(new Error("timeout")) : original(url, ...args));
    fireEvent.click(screen.getByRole("button", { name: "Emitir laudo" }));
    await screen.findByText(/Há uma tentativa de salvamento sem resposta confirmada/);
    expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeDisabled();
    expect(lastSnapshot().submission?.status).toBe("pending");
    view.unmount(); render(<NovoLaudoPage />);
    await screen.findByRole("button", { name: "Retomar rascunho" });
    expect(screen.queryByRole("button", { name: "Continuar com preenchimento atual" })).not.toBeInTheDocument();
    expect(mocks.post.mock.calls.filter(([url]) => url === "/laudos")).toHaveLength(1);
  });

  it.each(["alterado", "ausente"])("bloqueia a tela se o proprietário original ficar %s", async (scenario) => {
    await open(); await saveDraft(); vi.clearAllMocks();
    if (scenario === "alterado") localStorage.setItem("user", JSON.stringify({ id: 8 }));
    else localStorage.removeItem("user");
    fireEvent(window, new Event("focus"));
    await screen.findByText("A sessão do usuário mudou.");
    expect(screen.queryByDisplayValue(patient.nome)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Emitir laudo" })).not.toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled(); expect(mocks.put).not.toHaveBeenCalled(); expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each([null, "{broken"])("não emite nem prepara ditado quando falta um proprietário válido (%s)", async (value) => {
    if (value === null) localStorage.removeItem("user"); else localStorage.setItem("user", value);
    render(<NovoLaudoPage />); await screen.findByDisplayValue(patient.nome);
    await screen.findByText(/Não foi possível identificar o usuário do rascunho/);
    expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Preparar ditado sintético" }));
    expect(clinicalWrites()).toEqual([]); expect(draftWrites()).toEqual([]);
  });

  it("conclui o flush antes de sair pelo botão Voltar, mesmo antes do debounce", async () => {
    await open(); const slow = deferred<void>(); const original = mocks.put.getMockImplementation()!;
    mocks.put.mockImplementation(async (...args) => { await slow.promise; return original(...args); });
    fireEvent.change(input("Nome do Paciente"), { target: { value: "QA SAIDA IMEDIATA" } });
    fireEvent.click(screen.getByRole("button", { name: "Voltar para laudos" }));
    await waitFor(() => expect(draftWrites()).toHaveLength(1));
    expect(mocks.router.push).not.toHaveBeenCalled();
    await act(async () => slow.resolve());
    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/laudos"));
    expect(lastSnapshot().paciente.nome).toBe("QA SAIDA IMEDIATA"); expect(clinicalWrites()).toEqual([]);
  });

  it("salva antes de seguir um link interno fora da página e permanece na tela se falhar", async () => {
    await open(); const link = document.createElement("a"); link.href = "/dashboard"; link.textContent = "Menu sintético";
    document.body.append(link);
    try {
      mocks.put.mockRejectedValueOnce(failure(503));
      fireEvent.change(input("Nome do Paciente"), { target: { value: "QA SAIDA BLOQUEADA" } });
      fireEvent.click(link);
      await screen.findByText(/Não foi possível confirmar o rascunho antes de sair/);
      expect(mocks.router.push).not.toHaveBeenCalled(); expect(input("Nome do Paciente")).toBeEnabled();
      fireEvent.click(link);
      await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/dashboard"));
      expect(lastSnapshot().paciente.nome).toBe("QA SAIDA BLOQUEADA"); expect(clinicalWrites()).toEqual([]);
    } finally { link.remove(); }
  });

  it("retoma o ID preparado pelo ditado e emite por PUT sem criar segundo laudo", async () => {
    const view = await open();
    fireEvent.click(screen.getByRole("button", { name: "Preparar ditado sintético" }));
    await waitFor(() => expect(lastSnapshot().draftLaudoId).toBe(905));
    await waitFor(() => expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeEnabled());
    expect(mocks.post.mock.calls.filter(([url]) => url === "/laudos")).toHaveLength(1);
    expect(mocks.post.mock.calls.find(([url]) => url === "/laudos")![1].status).toBe("Rascunho");
    fireEvent.change(input("Nome do Paciente"), { target: { value: "QA DEPOIS DO DITADO" } });
    await saveDraft(); view.unmount(); render(<NovoLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await screen.findByDisplayValue("QA DEPOIS DO DITADO");
    await waitFor(() => expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Emitir laudo" }));
    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/laudos"));
    expect(mocks.put.mock.calls.find(([url]) => url === "/laudos/905")![1]).toMatchObject({ status: "Finalizado", paciente: { nome: "QA DEPOIS DO DITADO" } });
    expect(mocks.post.mock.calls.filter(([url]) => url === "/laudos")).toHaveLength(1);
  });

  it("não repete a criação do ditado após timeout nem após recuperar a página", async () => {
    const view = await open(); const original = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url, ...args) => url === "/laudos" ? Promise.reject(new Error("timeout")) : original(url, ...args));
    fireEvent.click(screen.getByRole("button", { name: "Preparar ditado sintético" }));
    await waitFor(() => expect(mocks.post.mock.calls.filter(([url]) => url === "/laudos")).toHaveLength(1));
    await screen.findByText(/Há uma tentativa de salvamento sem resposta confirmada/);
    fireEvent.click(screen.getByRole("button", { name: "Preparar ditado sintético" }));
    view.unmount(); render(<NovoLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await screen.findByText(/Há uma tentativa de salvamento sem resposta confirmada/);
    fireEvent.click(screen.getByRole("button", { name: "Preparar ditado sintético" }));
    expect(mocks.post.mock.calls.filter(([url]) => url === "/laudos")).toHaveLength(1);
  });

  it("reconfere imagem que expira entre a retomada e a emissão", async () => {
    const view = await open(); await saveDraft(); const record = [...mocks.records.values()][0];
    record.snapshot.imagens = [{ id: "late", nome: "qa.jpg", uploaded: true, tempId: 42, tamanho: 12, ordem: 0, descricao: "QA", incluirNoPdf: true }];
    const original = mocks.get.getMockImplementation()!; let checks = 0;
    mocks.get.mockImplementation((url, ...args) => url.startsWith("/imagens/temp/session/")
      ? Promise.resolve({ data: { items: ++checks === 1 ? [{ id: 42 }] : [] } })
      : url === "/imagens/temp/42" ? Promise.resolve({ data: new Blob(["qa"]) }) : original(url, ...args));
    view.unmount(); render(<NovoLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Emitir laudo" }));
    await screen.findByText(/Algumas imagens temporárias expiraram/);
    expect(clinicalWrites()).toEqual([]); expect(checks).toBe(2);
    expect(JSON.parse(screen.getByTestId("draft-images").textContent!)[0]).toMatchObject({ uploaded: false, requerReenvio: true });
  });

  it("não encerra o workspace quando associação retorna 200 sem imagens persistidas", async () => {
    const view = await open(); await saveDraft(); const record = [...mocks.records.values()][0];
    record.snapshot.imagens = [{ id: "late", nome: "qa.jpg", uploaded: true, tempId: 42, tamanho: 12, ordem: 0, descricao: "QA", incluirNoPdf: true }];
    const original = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url, ...args) => url.startsWith("/imagens/temp/session/") || url === "/imagens/laudo/905"
      ? Promise.resolve({ data: { items: url === "/imagens/laudo/905" ? [] : [{ id: 42 }] } })
      : url === "/imagens/temp/42" ? Promise.resolve({ data: new Blob(["qa"]) }) : original(url, ...args));
    view.unmount(); render(<NovoLaudoPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar rascunho" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Emitir laudo" }));
    await screen.findByText(/a associação das imagens não foi confirmada/);
    expect(screen.getByRole("button", { name: "Emitir laudo" })).toBeDisabled();
    expect(mocks.post.mock.calls.some(([url]) => url.endsWith("/close"))).toBe(false);
    expect(lastSnapshot().submission).toEqual({ status: "confirmed", laudoId: 905 });
    expect(mocks.router.push).not.toHaveBeenCalled();
  });

  it("PA dedicada permanece independente de workspace eco", async () => {
    window.history.replaceState(null, "", "/laudos/novo?tipo=pressao_arterial&paciente_id=901");
    render(<NovoLaudoPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Salvar Laudo de PA" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Paciente" }));
    await screen.findByDisplayValue(patient.nome);
    expect(input("Nome do Paciente")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Salvar Laudo de PA" })).toBeEnabled();
    expect(mocks.get.mock.calls.some(([url]) => url.startsWith("/laudos/editor-drafts/"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Pressao" }));
    fireEvent.change(input("1a afericao PAS (mmHg)"), { target: { value: "120" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar Laudo de PA" }));
    await waitFor(() => expect(mocks.post.mock.calls.some(([url]) => url === "/laudos")).toBe(true));
    expect(mocks.post.mock.calls.find(([url]) => url === "/laudos")![1].tipo_laudo).toBe("pressao_arterial");
    expect(draftWrites()).toEqual([]);
  });
});
