// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createContext, runInContext } from "node:vm";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";
import { mergeAutoSavedFormState } from "../../lib/atendimento-form-merge";

// Executa os callbacks reais da pagina com rede controlada. O harness isola
// somente React/browser: nao reimplementa a decisao de aceitar respostas e
// nao acessa prontuarios, armazenamento ou provedores reais.
const pageSource = ts.createSourceFile(
  "page.tsx",
  readFileSync(fileURLToPath(new URL("./page.tsx", import.meta.url)), "utf8"),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX
);

function callbackSource(name: string): string {
  let result = "";
  const visit = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && node.name.getText(pageSource) === name && node.initializer) {
      result = node.initializer.getText(pageSource);
    }
    ts.forEachChild(node, visit);
  };
  visit(pageSource);
  if (!result) throw new Error(`Callback nao encontrado: ${name}`);
  return result;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const form = (id: number) => ({
  id, paciente_id: String(id), status: "Triagem", anamnese: `Texto ${id}`,
  exames: [], prescricao_itens: [],
});

function harness() {
  const initial = form(99);
  const state = { selected: 99 as number | null, form: initial, error: "", autosave: "saved" };
  const context: Record<string, any> = {
    Promise, Number, Array, JSON, String, Date, Set,
    selecionado: 99, selecionadoRef: { current: 99 }, formRef: { current: initial },
    abrirAtendimentoRequestIdRef: { current: 0 },
    atendimentoContextoAplicadoRef: { current: 0 },
    historicoPacienteRequestIdRef: { current: 0 }, cadastroComplementarRequestIdRef: { current: 0 },
    confirmarSaidaAssistente: vi.fn(async () => true),
    hasEncounterContent: () => false, confirmarAcao: async () => true,
    api: { get: vi.fn(async (url: string) => ({ data: form(Number(url.split("/").pop())) })), put: vi.fn() },
    hydrateFormFromDetail: (value: unknown) => value,
    carregarHistoricoPaciente: vi.fn(async () => {}),
    carregarCadastroComplementar: vi.fn(), clearDraftStorage: vi.fn(), clearExamUploadDrafts: vi.fn(),
    gravarBackupLocalAtendimento: vi.fn(),
    serializeAtendimentoSnapshot: JSON.stringify, emptyDocumentoAtendimentoForm: () => ({}),
    extractApiErrorMessageSync: String, draftRestoreRef: { current: false }, hydratingFormRef: { current: false },
    lastPersistedSnapshotRef: { current: JSON.stringify(initial) }, backupLocalEscritoRef: { current: {} },
    criandoAtendimentoAutomaticoRef: { current: false },
    salvamentoAtendimentoEmVooRef: { current: null },
    autosaveStateRef: { current: "saved" }, autosaveTimerRef: { current: null },
    validarItensPrescricao: () => ({ errors: {}, total: 0 }), buildAtendimentoPayload: (value: unknown) => value,
    limparBackupConfirmado: vi.fn(), paginaLista: 1, carregarLista: vi.fn(async () => {}),
    emptyForm: () => ({ ...form(0), id: undefined, paciente_id: "" }), aplicarCadastroComplementar: vi.fn(),
    cadastroComplementar: { paciente: { nome: "Paciente ficticio", especie: "Canina" } }, pacienteBusca: "",
    emptyPrescriptionItem: () => ({}), cloneHistoricalPrescriptionItem: (value: unknown) => value,
  };
  const names = ["preservarBackupAntesDeTrocar", "abrirAtendimento", "novoAtendimento", "executarSaveAtendimento", "saveAtendimento", "finalizarAtendimento", "iniciarNovoAtendimentoPaciente", "herdarAtendimentoAnterior"];
  for (const name of names) {
    for (const match of callbackSource(name).matchAll(/\b(set[A-Z]\w+)\(/g)) context[match[1]] = vi.fn();
  }
  context.setSelecionado = (id: number | null) => {
    state.selected = id;
    context.selecionadoRef.current = id;
    context.selecionado = id;
  };
  context.setForm = (value: any) => {
    state.form = typeof value === "function" ? value(state.form) : value;
    context.formRef.current = state.form;
  };
  context.setErro = (value: string) => { state.error = value; };
  context.setAutosaveState = (value: string) => {
    state.autosave = value;
    context.autosaveStateRef.current = value;
  };
  context.mesclarFormularioAposSalvar = (persisted: any) => context.setForm(
    mergeAutoSavedFormState(state.form as never, persisted)
  );
  createContext(context);
  for (const name of names) {
    const code = ts.transpileModule(`globalThis.${name} = ${callbackSource(name)};`, {
      compilerOptions: { target: ts.ScriptTarget.ES2022 },
    }).outputText;
    runInContext(code, context);
  }
  return { state, context };
}

const tick = () => new Promise<void>((resolve) => setImmediate(resolve));

describe("isolamento do contexto do Atendimento durante a rede", () => {
  it("mantem a identidade anterior ate o detalhe e historico estarem prontos", async () => {
    const { state, context } = harness();
    const history = deferred<void>();
    context.carregarHistoricoPaciente.mockReturnValue(history.promise);
    const opening = context.abrirAtendimento(101);
    await tick();
    expect(state.selected).toBe(99);
    expect(state.form.id).toBe(99);
    history.resolve();
    await opening;
    expect(state.selected).toBe(101);
    expect(state.form.id).toBe(101);
  });

  it("ignora a abertura antiga quando os historicos respondem fora de ordem", async () => {
    const { state, context } = harness();
    const firstHistory = deferred<void>(), secondHistory = deferred<void>();
    context.carregarHistoricoPaciente.mockImplementation((id: string) => id === "101" ? firstHistory.promise : secondHistory.promise);
    const first = context.abrirAtendimento(101);
    await tick();
    const second = context.abrirAtendimento(202);
    await tick();
    secondHistory.resolve();
    await second;
    firstHistory.resolve();
    await first;
    expect(state.selected).toBe(202);
    expect(state.form.id).toBe(202);
    expect(state.form.paciente_id).toBe("202");
  });

  it("nao reabre o registro antigo depois de iniciar outro atendimento", async () => {
    const { state, context } = harness();
    const history = deferred<void>();
    context.carregarHistoricoPaciente.mockReturnValue(history.promise);
    const opening = context.abrirAtendimento(101);
    await tick();
    await context.novoAtendimento();
    history.resolve();
    await opening;
    expect(state.selected).toBeNull();
    expect(state.form.paciente_id).toBe("");
    expect(context.clearDraftStorage).not.toHaveBeenCalledWith(99);
  });

  it.each(["manual", "autosave"])("ignora resposta de save %s do registro anterior", async (mode) => {
    const { state, context } = harness();
    const request = deferred<{ data: ReturnType<typeof form> }>();
    context.api.put.mockReturnValue(request.promise);
    const saving = context.executarSaveAtendimento(mode);
    await tick();
    context.setSelecionado(202);
    context.setForm(form(202));
    const snapshot = context.lastPersistedSnapshotRef.current;
    request.resolve({ data: form(99) });
    expect(await saving).toBeNull();
    expect(state.selected).toBe(202);
    expect(state.form).toEqual(form(202));
    expect(context.lastPersistedSnapshotRef.current).toBe(snapshot);
  });

  it("erro de save antigo nao altera erros nem exclusoes do novo registro", async () => {
    const { state, context } = harness();
    const request = deferred<{ data: ReturnType<typeof form> }>();
    context.api.put.mockReturnValue(request.promise);
    const saving = context.executarSaveAtendimento("autosave");
    await tick();
    context.setSelecionado(202);
    context.setForm({ ...form(202), exames: [{ id: 23, _destroy: true }] });
    request.reject(new Error("Falha ficticia da requisicao anterior"));
    await saving;
    expect(state.error).toBe("");
    expect(state.form.exames).toEqual([{ id: 23, _destroy: true }]);
  });

  it("mantem novas edicoes no mesmo registro quando o save termina", async () => {
    const { state, context } = harness();
    const request = deferred<{ data: ReturnType<typeof form> }>();
    context.api.put.mockReturnValue(request.promise);
    const saving = context.executarSaveAtendimento("manual");
    await tick();
    context.setForm({ ...form(99), anamnese: "Edicao durante a rede" });
    request.resolve({ data: form(99) });
    expect(await saving).toBe(99);
    expect(state.selected).toBe(99);
    expect(state.form.anamnese).toBe("Edicao durante a rede");
  });

  it("cancela save enfileirado quando outro contexto foi aberto durante a espera", async () => {
    const { context } = harness();
    const previous = deferred<number>();
    context.salvamentoAtendimentoEmVooRef.current = previous.promise;
    const waiting = context.saveAtendimento("manual");
    await tick();
    ++context.abrirAtendimentoRequestIdRef.current;
    context.setSelecionado(202);
    context.setForm(form(202));
    previous.resolve(99);
    expect(await waiting).toBeNull();
    expect(context.api.put).not.toHaveBeenCalled();
  });

  it("resposta de finalizacao antiga nao hidrata outro atendimento", async () => {
    const { state, context } = harness();
    const finalization = deferred<{ data: { atendimento: ReturnType<typeof form> } }>();
    context.saveAtendimento = vi.fn(async () => 99);
    context.tipoHorarioFinalizacao = "Comercial";
    context.api.post = vi.fn(() => finalization.promise);
    const finishing = context.finalizarAtendimento();
    await tick();
    ++context.abrirAtendimentoRequestIdRef.current;
    context.setSelecionado(202);
    context.setForm(form(202));
    finalization.resolve({ data: { atendimento: { ...form(99), status: "Concluido" } } });
    await finishing;
    expect(state.selected).toBe(202);
    expect(state.form).toEqual(form(202));
    expect(context.carregarHistoricoPaciente).not.toHaveBeenCalled();
  });

  it("nao copia historico tardio de A para o novo contexto B", async () => {
    const { state, context } = harness();
    const history = deferred<{ data: ReturnType<typeof form> }>();
    context.api.get.mockReturnValue(history.promise);
    const copying = context.herdarAtendimentoAnterior(88);
    await tick();
    ++context.abrirAtendimentoRequestIdRef.current;
    context.setSelecionado(202);
    context.setForm(form(202));
    history.resolve({ data: { ...form(88), paciente_id: "99" } });
    await copying;
    expect(state.selected).toBe(202);
    expect(state.form).toEqual(form(202));
  });

  it("recusa heranca de um registro que pertence a outro paciente", async () => {
    const { state, context } = harness();
    await context.herdarAtendimentoAnterior(202);
    expect(state.selected).toBe(99);
    expect(state.form).toEqual(form(99));
    expect(state.error).toContain("outro paciente");
  });

  it("nao inicia novo registro com contexto antigo apos aguardar um save", async () => {
    const { state, context } = harness();
    const save = deferred<number>();
    context.autosaveStateRef.current = "dirty";
    context.saveAtendimento = vi.fn(() => save.promise);
    const starting = context.iniciarNovoAtendimentoPaciente();
    await tick();
    ++context.abrirAtendimentoRequestIdRef.current;
    context.setSelecionado(202);
    context.setForm(form(202));
    save.resolve(99);
    await starting;
    expect(state.selected).toBe(202);
    expect(state.form).toEqual(form(202));
  });

  it("tenta salvar estado com erro antes de iniciar novo atendimento do paciente", async () => {
    const { state, context } = harness();
    context.autosaveStateRef.current = "error";
    context.saveAtendimento = vi.fn(async () => null);
    await context.iniciarNovoAtendimentoPaciente();
    expect(context.saveAtendimento).toHaveBeenCalledWith("manual");
    expect(state.selected).toBe(99);
    expect(state.form).toEqual(form(99));
    expect(context.clearDraftStorage).not.toHaveBeenCalled();
  });

  it("cria o id do primeiro autosave sem interpretar isso como troca de contexto", async () => {
    const { state, context } = harness();
    context.setSelecionado(null);
    context.setForm({ ...form(99), id: undefined });
    context.api.post = vi.fn(async () => ({ data: form(99) }));
    expect(await context.executarSaveAtendimento("autosave")).toBe(99);
    expect(state.selected).toBe(99);
    expect(state.form.id).toBe(99);
  });

  it("encerra autosave de A quando a tentativa de abrir B falhou", async () => {
    const { state, context } = harness();
    const request = deferred<{ data: ReturnType<typeof form> }>();
    context.api.put.mockReturnValue(request.promise);
    const saving = context.executarSaveAtendimento("autosave");
    expect(state.autosave).toBe("saving");
    context.api.get.mockRejectedValue(new Error("Falha ficticia ao abrir B"));
    await context.abrirAtendimento(202);
    context.setForm({ ...form(99), anamnese: "Edicao feita enquanto B nao abriu" });
    request.resolve({ data: form(99) });
    expect(await saving).toBeNull(); // nao retoma uma acao encadeada cancelada
    expect(state.autosave).not.toBe("saving");
    expect(state.selected).toBe(99);
    expect(state.form.anamnese).toBe("Edicao feita enquanto B nao abriu");
    expect(state.error).toContain("Falha ficticia ao abrir B");
  });

  it("adota id do primeiro POST se B nao abriu e o rascunho A continua na tela", async () => {
    const { state, context } = harness();
    const request = deferred<{ data: ReturnType<typeof form> }>();
    context.setSelecionado(null);
    context.setForm({ ...form(99), id: undefined });
    context.api.post = vi.fn(() => request.promise);
    const saving = context.executarSaveAtendimento("autosave");
    context.api.get.mockRejectedValue(new Error("Falha ficticia ao abrir B"));
    await context.abrirAtendimento(202);
    const persisted = { ...form(777), paciente_id: "99" };
    request.resolve({ data: persisted });
    expect(await saving).toBeNull();
    expect(state.autosave).not.toBe("saving");
    expect(state.selected).toBe(777);
    expect(state.form.id).toBe(777);
    expect(state.form.paciente_id).toBe("99");
    context.api.put.mockResolvedValue({ data: persisted });
    await context.executarSaveAtendimento("autosave");
    expect(context.api.post).toHaveBeenCalledTimes(1);
    expect(context.api.put).toHaveBeenCalledWith("/atendimentos/777", expect.anything());
  });

  it("ignora resposta velha de A mesmo depois de abrir B e voltar ao mesmo A", async () => {
    const { state, context } = harness();
    const request = deferred<{ data: ReturnType<typeof form> }>();
    context.api.put.mockReturnValue(request.promise);
    const saving = context.executarSaveAtendimento("autosave");
    await context.abrirAtendimento(202);
    await context.abrirAtendimento(99);
    const snapshot = context.lastPersistedSnapshotRef.current;
    context.limparBackupConfirmado.mockClear();
    request.resolve({ data: { ...form(99), anamnese: "Resposta antiga" } });
    expect(await saving).toBeNull();
    expect(state.selected).toBe(99);
    expect(state.form).toEqual(form(99));
    expect(context.lastPersistedSnapshotRef.current).toBe(snapshot);
    expect(context.limparBackupConfirmado).not.toHaveBeenCalled();
    expect(state.autosave).toBe("saved");
  });

  it("save manual de A nao recarrega seu historico enquanto B esta abrindo", async () => {
    const { state, context } = harness();
    const save = deferred<{ data: ReturnType<typeof form> }>();
    const history = deferred<void>();
    context.api.put.mockReturnValue(save.promise);
    context.carregarHistoricoPaciente.mockReturnValue(history.promise);
    const saving = context.executarSaveAtendimento("manual");
    const opening = context.abrirAtendimento(202);
    await tick();
    save.resolve({ data: form(99) });
    expect(await saving).toBeNull();
    expect(state.autosave).not.toBe("saving");
    expect(context.carregarHistoricoPaciente.mock.calls).toEqual([["202"]]);
    expect(context.carregarLista).not.toHaveBeenCalled();
    history.resolve();
    await opening;
    expect(state.selected).toBe(202);
    expect(state.form).toEqual(form(202));
  });

  it.each(["abrirAtendimento", "novoAtendimento", "iniciarNovoAtendimentoPaciente"])(
    "avisa e preserva o registro quando o backup falha antes de %s",
    async (action) => {
      const { state, context } = harness();
      context.gravarBackupLocalAtendimento.mockImplementation(() => { throw new Error("QuotaExceededError"); });
      await context[action](...(action === "abrirAtendimento" ? [202] : []));
      expect(state.selected).toBe(99);
      expect(state.form).toEqual(form(99));
      expect(state.error).toContain("Nao foi possivel guardar a copia local");
      expect(context.clearDraftStorage).not.toHaveBeenCalled();
      expect(context.api.get).not.toHaveBeenCalled();
    }
  );
});
