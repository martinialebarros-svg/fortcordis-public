import type { EchoMeasurementState } from "./echo-ae-ao-derivation";
import type { EcocardiogramaEstruturadoPersistido } from "./ecocardiograma-estruturado";

export type EchoDraftFields = Record<string, string | number | boolean | null | undefined>;

export interface EchoDraftImage {
  id: string;
  nome: string;
  descricao: string;
  ordem: number;
  tamanho: number;
  tempId?: number;
  serverId?: number;
  uploaded: boolean;
  persisted?: boolean;
  incluirNoPdf?: boolean;
  requerReenvio?: boolean;
}

/** Editor state, deliberately separate from the clinical report payload. */
export interface EchoEditorDraftSnapshot {
  schema_version: 1;
  editor: "new-echo" | "existing-echo";
  source?: { laudo_id: number; editor_revision: string };
  existing?: {
    qualitativaAplicada: boolean;
    conclusaoAplicada: boolean;
    imagensPersistidas: EchoDraftImage[];
    imagensRemovidas: number[];
  };
  paciente: EchoDraftFields;
  measurementState: EchoMeasurementState;
  qualitativa: Record<string, string>;
  conteudo: Record<string, string>;
  ecocardiogramaCabecalho: { ritmo: string; estado: string; fc: string };
  ecocardiogramaEstruturado: EcocardiogramaEstruturadoPersistido;
  pressaoArterial: EchoDraftFields;
  clinicaId: string;
  clinicaNome: string;
  veterinario: string;
  agendamentoVinculadoId: number | null;
  sessionId: string;
  draftLaudoId: number | null;
  imagens: EchoDraftImage[];
  aba?: string;
  submission?: { status: "pending" | "confirmed"; laudoId: number | null };
}

export interface EchoEditorDraftResponse {
  draft_id: string;
  revision: number;
  context_key: string;
  snapshot: EchoEditorDraftSnapshot;
  updated_at: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TOP_KEYS = new Set([
  "schema_version", "editor", "paciente", "measurementState", "qualitativa", "conteudo",
  "ecocardiogramaCabecalho", "ecocardiogramaEstruturado", "pressaoArterial", "clinicaId",
  "clinicaNome", "veterinario", "agendamentoVinculadoId", "sessionId", "draftLaudoId", "imagens", "aba", "submission", "source", "existing",
]);
const IMAGE_KEYS = new Set([
  "id", "nome", "descricao", "ordem", "tamanho", "tempId", "serverId", "uploaded", "persisted",
  "incluirNoPdf", "requerReenvio",
]);
const STRUCTURED_KEYS = new Set([
  "versao", "modo", "usar_no_laudo", "preset_id", "preset_label", "preset_textos", "updated_at", "textos",
]);
const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value)
  && typeof value === "object" && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value));
const scalar = (value: unknown) => value === null || value === undefined
  || typeof value === "string" || typeof value === "boolean"
  || (typeof value === "number" && Number.isFinite(value));
const fields = (value: unknown, stringsOnly = false): boolean => isRecord(value)
  && Object.keys(value).length <= 512
  && Object.entries(value).every(([key, item]) => key.length <= 200
    && (stringsOnly ? typeof item === "string" : scalar(item)));
const optionalPositiveId = (value: unknown) => value === undefined
  || (typeof value === "number" && Number.isSafeInteger(value) && value > 0);
const nullableId = (value: unknown) => value === null || optionalPositiveId(value);
const validImages = (value: unknown): value is EchoDraftImage[] => Array.isArray(value) && value.length <= 200
  && value.every((image) => isRecord(image)
    && Object.keys(image).every((key) => IMAGE_KEYS.has(key))
    && ["id", "nome", "descricao"].every((key) => typeof image[key] === "string")
    && typeof image.uploaded === "boolean"
    && ["ordem", "tamanho"].every((key) => typeof image[key] === "number" && Number.isFinite(image[key]) && Number(image[key]) >= 0)
    && optionalPositiveId(image.tempId) && optionalPositiveId(image.serverId)
    && ["persisted", "incluirNoPdf", "requerReenvio"].every((key) => image[key] === undefined || typeof image[key] === "boolean"));

export function sameEchoDraftSource(left: EchoEditorDraftSnapshot, right: EchoEditorDraftSnapshot): boolean {
  return left.editor === right.editor && (left.editor !== "existing-echo"
    || (left.source?.laudo_id === right.source?.laudo_id && left.source?.editor_revision === right.source?.editor_revision));
}

export function isEchoDraftUuid(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}

/** Only this UUID pointer is persisted in sessionStorage; no report or token. */
export function echoDraftStorageKey(userId: number, contextKey: string): string {
  if (!Number.isSafeInteger(userId) || userId <= 0 || !contextKey || contextKey.length > 200) {
    throw new Error("Não foi possível identificar a sessão do rascunho.");
  }
  return `fortcordis:echo-editor-draft:v1:${userId}:${encodeURIComponent(contextKey)}`;
}

export function serializeDraftImages(images: readonly unknown[]): EchoDraftImage[] {
  return images.map((raw, index) => {
    if (!isRecord(raw)) throw new Error("A identificação de uma imagem é inválida.");
    return {
      id: String(raw.id ?? raw.tempId ?? raw.serverId ?? index),
      nome: typeof raw.nome === "string" ? raw.nome : "Imagem",
      descricao: typeof raw.descricao === "string" ? raw.descricao : "",
      ordem: typeof raw.ordem === "number" && Number.isFinite(raw.ordem) ? raw.ordem : index,
      tamanho: typeof raw.tamanho === "number" && Number.isFinite(raw.tamanho) ? raw.tamanho : 0,
      ...(optionalPositiveId(raw.tempId) && raw.tempId !== undefined ? { tempId: raw.tempId as number } : {}),
      ...(optionalPositiveId(raw.serverId) && raw.serverId !== undefined ? { serverId: raw.serverId as number } : {}),
      uploaded: raw.uploaded === true,
      ...(typeof raw.persisted === "boolean" ? { persisted: raw.persisted } : {}),
      ...(typeof raw.incluirNoPdf === "boolean" ? { incluirNoPdf: raw.incluirNoPdf } : {}),
      ...(raw.requerReenvio === true ? { requerReenvio: true } : {}),
    };
  });
}

/** Validate without deriving, normalizing, merging aliases or inventing values. */
export function cloneEchoEditorDraftSnapshot(value: unknown): EchoEditorDraftSnapshot {
  if (!isRecord(value) || value.schema_version !== 1 || !["new-echo", "existing-echo"].includes(String(value.editor))
    || (value.editor === "new-echo" && (value.source !== undefined || value.existing !== undefined))
    || (value.editor === "existing-echo" && (!isRecord(value.source)
      || Object.keys(value.source).some((key) => !["laudo_id", "editor_revision"].includes(key))
      || !optionalPositiveId(value.source.laudo_id) || value.source.laudo_id === undefined
      || typeof value.source.editor_revision !== "string" || !/^echo-v1:[a-f0-9]{64}$/.test(value.source.editor_revision)
      || !isRecord(value.existing)
      || Object.keys(value.existing).some((key) => !["qualitativaAplicada", "conclusaoAplicada", "imagensPersistidas", "imagensRemovidas"].includes(key))
      || typeof value.existing.qualitativaAplicada !== "boolean" || typeof value.existing.conclusaoAplicada !== "boolean"
      || !validImages(value.existing.imagensPersistidas)
      || !value.existing.imagensPersistidas.every((image) => image.serverId !== undefined && image.uploaded && image.persisted)
      || !Array.isArray(value.existing.imagensRemovidas) || value.existing.imagensRemovidas.length > 200
      || !value.existing.imagensRemovidas.every((id) => Number.isSafeInteger(id) && id > 0)))
    || Object.keys(value).some((key) => !TOP_KEYS.has(key))
    || !fields(value.paciente) || !fields(value.qualitativa, true) || !fields(value.conteudo, true)
    || !fields(value.ecocardiogramaCabecalho, true) || !fields(value.pressaoArterial)
    || !isRecord(value.measurementState) || !fields(value.measurementState.measurements)
    || typeof value.measurementState.aeAoDerived !== "boolean"
    || Object.keys(value.measurementState).some((key) => !["measurements", "aeAoDerived"].includes(key))
    || !isRecord(value.ecocardiogramaEstruturado)
    || Object.keys(value.ecocardiogramaEstruturado).some((key) => !STRUCTURED_KEYS.has(key))
    || !fields(value.ecocardiogramaEstruturado.textos, true)
    || !fields(value.ecocardiogramaEstruturado.preset_textos, true)
    || !Object.entries(value.ecocardiogramaEstruturado).every(([key, item]) =>
      ["textos", "preset_textos"].includes(key) || scalar(item))
    || !["clinicaId", "clinicaNome", "veterinario", "sessionId"].every((key) => typeof value[key] === "string")
    || !nullableId(value.agendamentoVinculadoId) || !nullableId(value.draftLaudoId)
    || (value.aba !== undefined && typeof value.aba !== "string")
    || (value.submission !== undefined && (!isRecord(value.submission)
      || !["pending", "confirmed"].includes(String(value.submission.status))
      || Object.keys(value.submission).some((key) => !["status", "laudoId"].includes(key))
      || !Object.hasOwn(value.submission, "laudoId")
      || !nullableId(value.submission.laudoId)
      || (value.submission.status === "confirmed" && !value.submission.laudoId)))
    || !validImages(value.imagens)) {
    throw new Error("O rascunho tem dados incompatíveis. O preenchimento atual foi preservado.");
  }
  const serialized = JSON.stringify(value);
  if (serialized.length > 1_000_000) throw new Error("O rascunho excedeu o limite de recuperação.");
  return JSON.parse(serialized) as EchoEditorDraftSnapshot;
}

const canonical = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(canonical);
  if (isRecord(value)) return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  return value;
};

export function echoDraftFingerprint(snapshot: EchoEditorDraftSnapshot): string {
  const { aba: _aba, ...content } = cloneEchoEditorDraftSnapshot(snapshot);
  void _aba;
  return JSON.stringify(canonical(content));
}

export function parseEchoEditorDraftResponse(value: unknown, draftId: string, contextKey: string): EchoEditorDraftResponse {
  if (!isRecord(value) || value.draft_id !== draftId || value.context_key !== contextKey
    || typeof value.revision !== "number" || !Number.isSafeInteger(value.revision) || value.revision < 1
    || typeof value.updated_at !== "string" || !Number.isFinite(Date.parse(value.updated_at))) {
    throw new Error("A resposta do rascunho não corresponde a este exame.");
  }
  return { draft_id: draftId, context_key: contextKey, revision: value.revision,
    updated_at: value.updated_at, snapshot: cloneEchoEditorDraftSnapshot(value.snapshot) };
}

export function pendingEchoDraftImages(snapshot: EchoEditorDraftSnapshot): number {
  return snapshot.imagens.filter((image) => !image.uploaded || image.requerReenvio
    || (!image.tempId && !image.serverId)).length;
}
