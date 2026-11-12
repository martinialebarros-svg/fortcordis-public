import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { criarEcocardiogramaEstruturadoInicial } from "@/lib/ecocardiograma-estruturado";
import { echoDraftStorageKey, type EchoEditorDraftSnapshot } from "@/lib/echo-editor-draft";
import { useEchoEditorDraft, type UseEchoEditorDraftOptions } from "./useEchoEditorDraft";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: mocks }));
const ID = "11111111-1111-4111-8111-111111111111";
const snapshot = (text = ""): EchoEditorDraftSnapshot => ({
  schema_version: 1, editor: "new-echo", paciente: { id: 901, nome: "QA", especie: "Felina" },
  measurementState: { measurements: { Diastolica_ondas: "fundidas", TDI_metodo: "", AE_Ao: "1.4" }, aeAoDerived: false },
  qualitativa: {}, conteudo: { conclusao: text }, ecocardiogramaCabecalho: { ritmo: "", estado: "", fc: "" },
  ecocardiogramaEstruturado: criarEcocardiogramaEstruturadoInicial(), pressaoArterial: {},
  clinicaId: "", clinicaNome: "", veterinario: "", agendamentoVinculadoId: 77,
  sessionId: "session-qa", draftLaudoId: null, imagens: [],
});
const options = (value = snapshot()): UseEchoEditorDraftOptions => ({
  enabled: true, userId: 1, contextKey: "agendamento:77", snapshot: value, onRestore: vi.fn(),
});
const failure = (status: number) => ({ response: { status } });
const deferred = <T,>() => { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const response = (value = snapshot("recuperado"), revision = 3, context = "agendamento:77", id = ID) => ({
  data: { draft_id: id, context_key: context, revision, snapshot: value, updated_at: "2026-11-01T12:00:00Z" },
});
const savedResponse = (url: string, request: { expected_revision: number; context_key: string; snapshot: EchoEditorDraftSnapshot }) =>
  response(request.snapshot, request.expected_revision + 1, request.context_key, url.split("/").at(-1));
const settle = async () => { await act(async () => {}); };
const advance = async (ms = 1500) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };

describe("workspace de rascunho eco", () => {
  const existing = (): EchoEditorDraftSnapshot => ({ ...snapshot(), editor: "existing-echo",
    source: { laudo_id: 901, editor_revision: "echo-v1:" + "a".repeat(64) },
    existing: { qualitativaAplicada: false, conclusaoAplicada: false, imagensPersistidas: [], imagensRemovidas: [] } });
  beforeEach(() => {
    vi.useFakeTimers(); vi.clearAllMocks(); sessionStorage.clear();
    mocks.get.mockRejectedValue(failure(404));
    mocks.put.mockImplementation(async (url, request) => savedResponse(url, request));
    mocks.post.mockImplementation(async (url, request) => ({ data: {
      draft_id: url.split("/").at(-2), closed: true, revision: request.expected_revision + 1,
    } }));
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); sessionStorage.clear(); });

  it.each([true, false])("workspace existente encerrado segura resultado conhecido=%s sem criar outro UUID", async (known) => {
    sessionStorage.setItem(echoDraftStorageKey(1, "edit:laudo:901"), ID);
    const result = known ? { id: 901, request_id: ID, updated: true as const } : null;
    mocks.get.mockRejectedValue({ response: { status: 410, data: { detail: {
      code: "EDITOR_DRAFT_CLOSED", laudo_id: 901, apply_result: result } } } });
    const hook = renderHook(() => useEchoEditorDraft({ ...options(existing()), contextKey: "edit:laudo:901" }));
    await settle(); await advance(5000);
    expect(hook.result.current.status).toBe("closed"); expect(hook.result.current.blocked).toBe(true);
    expect(hook.result.current.closedRecovery).toEqual({ laudoId: 901, result });
    expect(mocks.get).toHaveBeenCalledOnce(); expect(mocks.put).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(echoDraftStorageKey(1, "edit:laudo:901"))).toBe(ID);
    act(() => hook.result.current.acknowledgeClosed());
    expect(sessionStorage.getItem(echoDraftStorageKey(1, "edit:laudo:901"))).toBeNull();
    expect(mocks.get).toHaveBeenCalledOnce(); expect(mocks.put).not.toHaveBeenCalled();
  });

  it("não substitui silenciosamente a origem do rascunho existente ao continuar sem retomar", async () => {
    const recovered = existing(); const current = { ...existing(), source: { laudo_id: 901, editor_revision: "echo-v1:" + "b".repeat(64) } };
    sessionStorage.setItem(echoDraftStorageKey(1, "edit:laudo:901"), ID);
    mocks.get.mockResolvedValue(response(recovered, 3, "edit:laudo:901"));
    const hook = renderHook(() => useEchoEditorDraft({ ...options(current), contextKey: "edit:laudo:901" }));
    await settle(); act(() => hook.result.current.continueFresh()); await advance();
    expect(hook.result.current.status).toBe("recovery"); expect(mocks.put).not.toHaveBeenCalled();
    expect(hook.result.current.error).toMatch(/versão oficial mudou/i);
  });

  it("não encerra nem descarta prova de atualização pendente ao oferecer recuperação", async () => {
    const saved = { ...existing(), submission: { status: "pending" as const, laudoId: 901 } };
    sessionStorage.setItem(echoDraftStorageKey(1, "edit:laudo:901"), ID);
    mocks.get.mockResolvedValue(response(saved, 3, "edit:laudo:901"));
    const hook = renderHook(() => useEchoEditorDraft({ ...options(existing()), contextKey: "edit:laudo:901" }));
    await settle();
    await expect(hook.result.current.discardExisting()).rejects.toThrow(/tentativa de atualização/);
    expect(mocks.post).not.toHaveBeenCalled(); expect(mocks.put).not.toHaveBeenCalled();
  });

  it("consulta antes de salvar, não cria cópia vazia e aplica debounce só após alteração", async () => {
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle();
    expect(mocks.get).toHaveBeenCalledOnce();
    expect(mocks.get.mock.calls[0][1].headers).toEqual({ "X-Editor-Owner-Id": 1 });
    expect(hook.result.current.status).toBe("idle");
    await advance(5000); expect(mocks.put).not.toHaveBeenCalled();
    hook.rerender({ ...initial, snapshot: snapshot("primeiro") });
    await advance(1499); expect(mocks.put).not.toHaveBeenCalled();
    await advance(1);
    expect(mocks.put).toHaveBeenCalledOnce();
    expect(mocks.put.mock.calls[0][1]).toMatchObject({ expected_revision: 0, snapshot: snapshot("primeiro") });
    expect(mocks.put.mock.calls[0][2].headers).toEqual({ "X-Editor-Owner-Id": 1 });
    expect(hook.result.current.status).toBe("saved");
    expect([...Array(sessionStorage.length)].map((_, i) => sessionStorage.getItem(sessionStorage.key(i)!)))
      .toEqual([hook.result.current.draftId]);
    expect(JSON.stringify(sessionStorage)).not.toMatch(/primeiro|Felina|session-qa/);
  });

  it("serializa uma requisição lenta e drena apenas o último estado sem reconhecer edição nova com resposta antiga", async () => {
    const slow = deferred<ReturnType<typeof response>>();
    mocks.put.mockImplementationOnce(() => slow.promise);
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle(); hook.rerender({ ...initial, snapshot: snapshot("A") }); await advance();
    expect(hook.result.current.status).toBe("saving");
    hook.rerender({ ...initial, snapshot: snapshot("B") }); await advance(2000);
    hook.rerender({ ...initial, snapshot: snapshot("C") });
    expect(mocks.put).toHaveBeenCalledOnce();
    const first = mocks.put.mock.calls[0];
    await act(async () => slow.resolve(savedResponse(first[0], first[1])));
    expect(mocks.put).toHaveBeenCalledTimes(2);
    expect(mocks.put.mock.calls[1][1]).toMatchObject({ expected_revision: 1, snapshot: snapshot("C") });
    expect(hook.result.current.status).toBe("saved");
  });

  it("falha de resultado desconhecido repete request_id/payload exatos antes de salvar edições posteriores", async () => {
    mocks.put.mockRejectedValueOnce(new Error("Sem conexão"));
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle(); hook.rerender({ ...initial, snapshot: snapshot("A") }); await advance();
    const first = structuredClone(mocks.put.mock.calls[0][1]);
    expect(hook.result.current.status).toBe("error");
    hook.rerender({ ...initial, snapshot: snapshot("B") }); await advance(4000);
    expect(mocks.put).toHaveBeenCalledOnce();
    await act(async () => { await hook.result.current.retry(); });
    expect(mocks.put.mock.calls[1][1]).toEqual(first);
    expect(mocks.put.mock.calls[2][1]).toMatchObject({ expected_revision: 1, snapshot: snapshot("B") });
    expect(hook.result.current.status).toBe("saved");
  });

  it("recuperação exige escolha e preserva conteúdo literal sem PUT após retomar", async () => {
    sessionStorage.setItem(echoDraftStorageKey(1, "agendamento:77"), ID);
    const previous = snapshot("texto recuperável");
    mocks.get.mockResolvedValue(response(previous));
    let apply!: (value: EchoEditorDraftSnapshot) => void;
    const initial = { ...options(), onRestore: vi.fn(async (value: EchoEditorDraftSnapshot) => { apply(value); return value; }) };
    const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    apply = (value) => hook.rerender({ ...initial, snapshot: value });
    await settle(); expect(hook.result.current.status).toBe("recovery");
    expect(hook.result.current.canEmit).toBe(false);
    await advance(5000); expect(mocks.put).not.toHaveBeenCalled();
    await expect(hook.result.current.flush()).rejects.toThrow();
    await act(async () => { await hook.result.current.resumeRecovered(); });
    expect(initial.onRestore).toHaveBeenCalledWith(previous);
    await advance(3000); expect(mocks.put).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe("saved");
    expect(hook.result.current.canEmit).toBe(true);
    hook.rerender({ ...initial, snapshot: snapshot("alteração depois de recuperar") }); await advance();
    expect(mocks.put.mock.calls[0][1].expected_revision).toBe(3);
  });

  it("continuar preenchimento atual usa a revisão lida e não apaga até a escolha explícita", async () => {
    sessionStorage.setItem(echoDraftStorageKey(1, "agendamento:77"), ID);
    mocks.get.mockResolvedValue(response());
    const hook = renderHook(() => useEchoEditorDraft(options(snapshot("atual"))));
    await settle(); await advance(3000); expect(mocks.put).not.toHaveBeenCalled();
    act(() => hook.result.current.continueFresh()); await advance();
    expect(mocks.put.mock.calls[0][1]).toMatchObject({ expected_revision: 3, snapshot: snapshot("atual") });
  });

  it.each(["pending", "confirmed"] as const)("não descarta prova de emissão %s usando continuar preenchimento atual", async (status) => {
    sessionStorage.setItem(echoDraftStorageKey(1, "agendamento:77"), ID);
    const previous = { ...snapshot("anterior"), submission: { status, laudoId: status === "confirmed" ? 99 : null } };
    mocks.get.mockResolvedValue(response(previous));
    const hook = renderHook(() => useEchoEditorDraft(options(snapshot("atual")))); await settle();
    act(() => hook.result.current.continueFresh()); await advance(5000);
    expect(hook.result.current.status).toBe("recovery"); expect(hook.result.current.canEmit).toBe(false);
    expect(hook.result.current.recovery?.snapshot.submission).toEqual(previous.submission);
    expect(mocks.put).not.toHaveBeenCalled(); await expect(hook.result.current.flush()).rejects.toThrow();
  });

  it("409 bloqueia emissão e não tenta sobrescrever outra revisão", async () => {
    mocks.put.mockRejectedValue(failure(409));
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle(); hook.rerender({ ...initial, snapshot: snapshot("A") }); await advance();
    expect(hook.result.current.status).toBe("conflict"); expect(hook.result.current.blocked).toBe(true);
    hook.rerender({ ...initial, snapshot: snapshot("B") }); await advance(5000);
    await expect(hook.result.current.flush()).rejects.toThrow(); expect(mocks.put).toHaveBeenCalledOnce();
  });

  it.each([401, 403, 500])("GET %s não cria workspace nem libera emissão", async (status) => {
    mocks.get.mockRejectedValue(failure(status));
    const hook = renderHook(() => useEchoEditorDraft(options())); await settle(); await advance(3000);
    expect(hook.result.current.status).toBe("error"); expect(hook.result.current.canEmit).toBe(false);
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("retry de GET mantém edições feitas durante a indisponibilidade e salva após 404", async () => {
    mocks.get.mockRejectedValueOnce(failure(500));
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle(); hook.rerender({ ...initial, snapshot: snapshot("editado durante a falha") });
    await act(async () => { await hook.result.current.retry(); }); await settle(); await advance();
    expect(mocks.put).toHaveBeenCalledOnce();
    expect(mocks.put.mock.calls[0][1].snapshot.conteudo.conclusao).toBe("editado durante a falha");
  });

  it("sessão/usuário trocado e GET tardio não aplicam dados nem salvam o contexto anterior", async () => {
    const old = deferred<ReturnType<typeof response>>(); mocks.get.mockImplementationOnce(() => old.promise);
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    const oldId = hook.result.current.draftId;
    hook.rerender({ ...initial, userId: 2, contextKey: "agendamento:78", snapshot: snapshot("outro") });
    await settle(); const newId = hook.result.current.draftId; expect(newId).not.toBe(oldId);
    expect(mocks.get.mock.calls[0][1].headers).toEqual({ "X-Editor-Owner-Id": 1 });
    expect(mocks.get.mock.calls[1][1].headers).toEqual({ "X-Editor-Owner-Id": 2 });
    await act(async () => old.resolve(response(snapshot("segredo do anterior"), 2, "agendamento:77", oldId!)));
    expect(hook.result.current.status).toBe("idle"); expect(hook.result.current.recovery).toBeNull();
    expect(initial.onRestore).not.toHaveBeenCalled(); await advance(2000); expect(mocks.put).not.toHaveBeenCalled();
    hook.unmount();
  });

  it("GET tardio 404 não transforma texto digitado durante a consulta em baseline limpa", async () => {
    const loading = deferred<ReturnType<typeof response>>(); mocks.get.mockImplementationOnce(() => loading.promise);
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    hook.rerender({ ...initial, snapshot: snapshot("digitado enquanto consulta") });
    await act(async () => loading.reject(failure(404))); await advance();
    expect(mocks.put.mock.calls[0][1].snapshot.conteudo.conclusao).toBe("digitado enquanto consulta");
  });

  it("GET de outro contexto não restaura nem sobrescreve", async () => {
    sessionStorage.setItem(echoDraftStorageKey(1, "agendamento:77"), ID);
    mocks.get.mockResolvedValue(response(snapshot("outro"), 2, "agendamento:78"));
    const hook = renderHook(() => useEchoEditorDraft(options())); await settle(); await advance();
    expect(hook.result.current.status).toBe("error"); expect(hook.result.current.recovery).toBeNull();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("GET concluído depois de desmontar não dispara PUT", async () => {
    const old = deferred<ReturnType<typeof response>>(); mocks.get.mockImplementationOnce(() => old.promise);
    const hook = renderHook(() => useEchoEditorDraft(options())); const id = hook.result.current.draftId!;
    hook.unmount(); await act(async () => old.resolve(response(snapshot(), 1, "agendamento:77", id)));
    await advance(); expect(mocks.put).not.toHaveBeenCalled();
  });

  it("storage indisponível é erro explícito sem prometer recuperação", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Unavailable"); });
    const hook = renderHook(() => useEchoEditorDraft(options())); await settle();
    expect(hook.result.current.status).toBe("error"); expect(hook.result.current.error).toContain("navegador");
    expect(hook.result.current.canEmit).toBe(false); expect(mocks.get).not.toHaveBeenCalled();
  });

  it("pausa drena flush explícito inclusive primeira cópia e congela autosave; resume retoma alterações", async () => {
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle(); await act(async () => { await hook.result.current.pause(); });
    expect(mocks.put).toHaveBeenCalledOnce(); expect(hook.result.current.status).toBe("paused");
    hook.rerender({ ...initial, snapshot: snapshot("depois da pausa") }); await advance(4000);
    expect(mocks.put).toHaveBeenCalledOnce();
    act(() => hook.result.current.resume()); await advance();
    expect(mocks.put).toHaveBeenCalledTimes(2);
  });

  it("flush override conserva ID criado antes de o render do pai chegar", async () => {
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle(); await act(async () => { await hook.result.current.flush({ ...snapshot(), draftLaudoId: 777 }); });
    expect(mocks.put.mock.calls[0][1].snapshot.draftLaudoId).toBe(777);
    await advance(3000); expect(mocks.put).toHaveBeenCalledOnce();
  });

  it("flush durante pausa registra evidência de emissão e não libera nova emissão", async () => {
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial }); await settle();
    await act(async () => { await hook.result.current.pause(); });
    const pending = { ...snapshot(), submission: { status: "pending" as const, laudoId: null } };
    await act(async () => { await hook.result.current.flush(pending); });
    hook.rerender({ ...initial, snapshot: pending });
    expect(hook.result.current.canEmit).toBe(false);
    const confirmed = { ...pending, submission: { status: "confirmed" as const, laudoId: 77 } };
    await act(async () => { await hook.result.current.flush(confirmed); });
    expect(mocks.put.mock.calls[2][1]).toMatchObject({ expected_revision: 2, snapshot: confirmed });
    await act(async () => { await hook.result.current.close(); }); expect(hook.result.current.status).toBe("closed");
  });

  it("não encerra workspace se houve mudança do editor depois da pausa", async () => {
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial }); await settle();
    await act(async () => { await hook.result.current.pause(); });
    hook.rerender({ ...initial, snapshot: snapshot("mudou depois") });
    await expect(hook.result.current.close()).rejects.toThrow(); expect(mocks.post).not.toHaveBeenCalled();
  });

  it("encerramento só após pausa; retry usa mesma chave e não reemite laudo", async () => {
    mocks.post.mockRejectedValueOnce(new Error("Sem resposta do encerramento"));
    const hook = renderHook(() => useEchoEditorDraft(options())); await settle();
    await expect(hook.result.current.close()).rejects.toThrow();
    await act(async () => { await hook.result.current.pause(); });
    await act(async () => { await expect(hook.result.current.close()).rejects.toThrow(); });
    const first = structuredClone(mocks.post.mock.calls[0][1]);
    expect(hook.result.current.error).toContain("não emita novamente");
    await act(async () => { await hook.result.current.retry(); });
    expect(mocks.post.mock.calls[1][1]).toEqual(first);
    expect(mocks.post.mock.calls[0][2].headers).toEqual({ "X-Editor-Owner-Id": 1 });
    expect(mocks.post.mock.calls[1][2].headers).toEqual({ "X-Editor-Owner-Id": 1 });
    expect(hook.result.current.status).toBe("closed"); expect(sessionStorage.length).toBe(0);
    expect(mocks.post.mock.calls.every(([url]) => url.endsWith("/close"))).toBe(true);
  });

  it("ponteiro de workspace encerrado recebe UUID novo sem recuperar o emitido", async () => {
    sessionStorage.setItem(echoDraftStorageKey(1, "agendamento:77"), ID);
    mocks.get.mockRejectedValueOnce(failure(410));
    const hook = renderHook(() => useEchoEditorDraft(options())); await settle();
    expect(mocks.get).toHaveBeenCalledTimes(2); expect(hook.result.current.draftId).not.toBe(ID);
    expect(mocks.get.mock.calls.map(([, config]) => config.headers)).toEqual([
      { "X-Editor-Owner-Id": 1 }, { "X-Editor-Owner-Id": 1 },
    ]);
    expect(hook.result.current.status).toBe("idle"); expect(mocks.put).not.toHaveBeenCalled();
  });

  it.each([
    { draft_id: "wrong", closed: true, revision: 2 },
    { draft_id: ID, closed: false, revision: 2 },
    { draft_id: ID, closed: true, revision: 1 },
    { closed: true },
  ])("não encerra nem remove ponteiro com confirmação malformada (%j)", async (confirmation) => {
    sessionStorage.setItem(echoDraftStorageKey(1, "agendamento:77"), ID);
    mocks.post.mockResolvedValueOnce({ data: confirmation });
    const hook = renderHook(() => useEchoEditorDraft(options())); await settle();
    await act(async () => { await hook.result.current.pause(); });
    await act(async () => { await expect(hook.result.current.close()).rejects.toThrow(); });
    expect(hook.result.current.status).toBe("error");
    expect(sessionStorage.getItem(echoDraftStorageKey(1, "agendamento:77"))).toBe(ID);
    expect(hook.result.current.canEmit).toBe(false);
  });

  it("beforeunload avisa mudança ainda não confirmada, sem transmitir dados clínicos pelo storage", async () => {
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle(); hook.rerender({ ...initial, snapshot: snapshot("não salvo") });
    const pending = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(pending);
    expect(pending.defaultPrevented).toBe(true);
    await advance(); const saved = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(saved);
    expect(saved.defaultPrevented).toBe(false);
  });

  it("beforeunload conserva aviso de imagem não enviada mesmo após salvar os metadados", async () => {
    const value = { ...snapshot(), imagens: [{ id: "qa", nome: "qa.png", descricao: "", ordem: 0, tamanho: 10, uploaded: false }] };
    const hook = renderHook(() => useEchoEditorDraft(options(value))); await settle();
    await act(async () => { await hook.result.current.flush(); });
    expect(hook.result.current.status).toBe("saved"); expect(hook.result.current.pendingImages).toBe(1);
    const event = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("cookie de outra conta com cache local antigo recebe 403 e não adapta o proprietário silenciosamente", async () => {
    mocks.get.mockImplementation(async (_url, config) => {
      expect(config.headers).toEqual({ "X-Editor-Owner-Id": 1 });
      // The server authenticates account 2 from its HttpOnly cookie, but this
      // editor remains bound to the account that owns its current form.
      throw failure(403);
    });
    const initial = options(); const hook = renderHook((props) => useEchoEditorDraft(props), { initialProps: initial });
    await settle(); hook.rerender({ ...initial, snapshot: snapshot("texto ainda da conta 1") }); await advance(4000);
    expect(hook.result.current.status).toBe("error"); expect(hook.result.current.canEmit).toBe(false);
    expect(mocks.put).not.toHaveBeenCalled(); expect(mocks.post).not.toHaveBeenCalled();
  });
});
