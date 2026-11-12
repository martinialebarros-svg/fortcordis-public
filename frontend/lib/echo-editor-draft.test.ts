import { describe, expect, it } from "vitest";
import { criarEcocardiogramaEstruturadoInicial } from "./ecocardiograma-estruturado";
import { cloneEchoEditorDraftSnapshot, echoDraftFingerprint, echoDraftStorageKey, parseEchoEditorDraftResponse,
  pendingEchoDraftImages, serializeDraftImages, type EchoEditorDraftSnapshot } from "./echo-editor-draft";

const snapshot = (): EchoEditorDraftSnapshot => ({
  schema_version: 1, editor: "new-echo", paciente: { id: 901, nome: "QA", peso: "0", especie: "Cat" },
  measurementState: { measurements: { Onda_E: "", MV_E: "1.8", Onda_A: "0", Diastolica_ondas: "fundidas",
    TDI_ondas: "nao_confirmadas", TDI_metodo: "", AE_Ao: "1,40", Aorta: "10", Atrio_esquerdo: "14.6" }, aeAoDerived: false },
  qualitativa: { funcao: "Texto\ncom quebras" }, conteudo: { conclusao: "", observacoes: "0" },
  ecocardiogramaCabecalho: { fc: "", estado: "", ritmo: "" },
  ecocardiogramaEstruturado: criarEcocardiogramaEstruturadoInicial(), pressaoArterial: { pas_1: "0", salvar_como_laudo_pressao: false },
  clinicaId: "", clinicaNome: "", veterinario: "", agendamentoVinculadoId: 77,
  sessionId: "temp-session", draftLaudoId: null, imagens: [], aba: "paciente",
});

describe("snapshot literal do editor eco", () => {
  it("mantém origem, flags e imagens existentes sem valores clínicos derivados na recuperação", () => {
    const source = { ...snapshot(), editor: "existing-echo" as const,
      source: { laudo_id: 901, editor_revision: "echo-v1:" + "a".repeat(64) },
      existing: { qualitativaAplicada: true, conclusaoAplicada: false, imagensRemovidas: [10],
        imagensPersistidas: serializeDraftImages([{ id: "11", serverId: 11, nome: "qa.png", ordem: 0,
          descricao: "Legenda", tamanho: 12, uploaded: true, persisted: true, incluirNoPdf: false }]) } };
    expect(cloneEchoEditorDraftSnapshot(source)).toEqual(source);
    expect(() => cloneEchoEditorDraftSnapshot({ ...source, source: { ...source.source, editor_revision: "invalid" } })).toThrow();
    expect(() => cloneEchoEditorDraftSnapshot({ ...source, editor: "new-echo" })).toThrow();
    expect(echoDraftFingerprint({ ...source, existing: { ...source.existing, conclusaoAplicada: true } }))
      .not.toBe(echoDraftFingerprint(source));
  });
  it("preserva vazios, zeros, aliases, confirmação retirada e razão independente, sem mutação", () => {
    const source = snapshot();
    const before = JSON.stringify(source);
    const clone = cloneEchoEditorDraftSnapshot(source);
    expect(clone).toEqual(source);
    expect(clone.measurementState).toEqual(source.measurementState);
    clone.measurementState.measurements.Onda_E = "2";
    expect(JSON.stringify(source)).toBe(before);
  });

  it("serializa somente metadados de imagem e informa arquivos pendentes", () => {
    const source = [{ id: "pending", nome: "qa.png", descricao: "", ordem: 0, tamanho: 12,
      uploaded: false, file: new File(["x"], "qa.png"), dataUrl: "data:image/png;base64,private" },
    { id: "sent", nome: "sent.png", descricao: "AE", ordem: 1, tamanho: 10, uploaded: true, tempId: 42, incluirNoPdf: false },
    { id: "expired", nome: "expired.png", descricao: "", ordem: 2, tamanho: 10, uploaded: true, tempId: 43, requerReenvio: true }];
    const images = serializeDraftImages(source);
    expect(JSON.stringify(images)).not.toMatch(/private|dataUrl|file/);
    expect(images[1]).toMatchObject({ tempId: 42, incluirNoPdf: false, uploaded: true });
    expect(pendingEchoDraftImages({ ...snapshot(), imagens: images })).toBe(2);
    expect(cloneEchoEditorDraftSnapshot({ ...snapshot(), imagens: images }).imagens).toEqual(images);
  });

  it.each([
    (s: EchoEditorDraftSnapshot) => ({ ...s, editor: "edit-echo" }),
    (s: EchoEditorDraftSnapshot) => ({ ...s, unexpected: "x" }),
    (s: EchoEditorDraftSnapshot) => ({ ...s, measurementState: { ...s.measurementState, token: "x" } }),
    (s: EchoEditorDraftSnapshot) => ({ ...s, imagens: [{ ...serializeDraftImages([{ uploaded: true }])[0], dataUrl: "private" }] }),
    (s: EchoEditorDraftSnapshot) => ({ ...s, paciente: { ...s.paciente, file: new File(["x"], "qa.png") } }),
  ])("recusa forma inesperada ou binário em vez de removê-lo silenciosamente", (change) => {
    expect(() => cloneEchoEditorDraftSnapshot(change(snapshot()))).toThrow();
  });

  it("fingerprint ignora só a aba e a ordem das chaves", () => {
    const source = snapshot();
    expect(echoDraftFingerprint({ ...source, aba: "imagens" })).toBe(echoDraftFingerprint(source));
    expect(echoDraftFingerprint({ ...source, paciente: { especie: "Cat", peso: "0", nome: "QA", id: 901 } })).toBe(echoDraftFingerprint(source));
    expect(echoDraftFingerprint({ ...source, conteudo: { ...source.conteudo, conclusao: "Revisão" } })).not.toBe(echoDraftFingerprint(source));
  });

  it("isola ponteiros por usuário e contexto sem incluir o conteúdo clínico", () => {
    expect(echoDraftStorageKey(1, "agendamento:77")).not.toBe(echoDraftStorageKey(2, "agendamento:77"));
    expect(echoDraftStorageKey(1, "agendamento:77")).not.toBe(echoDraftStorageKey(1, "agendamento:78"));
    expect(echoDraftStorageKey(1, "novo")).not.toContain("QA");
    expect(() => echoDraftStorageKey(0, "novo")).toThrow();
    expect(() => echoDraftStorageKey(1, "x".repeat(201))).toThrow();
  });

  it("resposta de outro ID/contexto ou revisão inválida não pode substituir o editor", () => {
    const good = { draft_id: "uuid", context_key: "ctx", revision: 2, snapshot: snapshot(), updated_at: "2026-11-01T12:00:00Z" };
    expect(parseEchoEditorDraftResponse(good, "uuid", "ctx").snapshot).toEqual(snapshot());
    expect(() => parseEchoEditorDraftResponse(good, "other", "ctx")).toThrow();
    expect(() => parseEchoEditorDraftResponse(good, "uuid", "other")).toThrow();
    expect(() => parseEchoEditorDraftResponse({ ...good, revision: 0 }, "uuid", "ctx")).toThrow();
  });

  it("preserva prova de emissão pendente/confirmada e inclui no fingerprint", () => {
    const source = snapshot();
    const pending = { ...source, submission: { status: "pending" as const, laudoId: null } };
    expect(cloneEchoEditorDraftSnapshot(pending)).toEqual(pending);
    expect(echoDraftFingerprint(pending)).not.toBe(echoDraftFingerprint(source));
    expect(cloneEchoEditorDraftSnapshot({ ...source, submission: { status: "confirmed", laudoId: 8 } }).submission?.laudoId).toBe(8);
    expect(() => cloneEchoEditorDraftSnapshot({ ...source, submission: { status: "confirmed", laudoId: null } })).toThrow();
  });
});
