"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/lib/axios";
import {
  cloneEchoEditorDraftSnapshot, echoDraftFingerprint, echoDraftStorageKey, isEchoDraftUuid,
  parseEchoEditorDraftResponse, pendingEchoDraftImages,
  sameEchoDraftSource,
  type EchoEditorDraftResponse, type EchoEditorDraftSnapshot,
} from "@/lib/echo-editor-draft";

export type EchoDraftStatus = "disabled" | "loading" | "recovery" | "idle" | "pending"
  | "saving" | "saved" | "error" | "conflict" | "paused" | "closed";

export interface UseEchoEditorDraftOptions {
  enabled: boolean;
  contextKey: string;
  userId: number | null;
  snapshot: EchoEditorDraftSnapshot;
  onRestore: (snapshot: EchoEditorDraftSnapshot) => void | EchoEditorDraftSnapshot
    | Promise<void | EchoEditorDraftSnapshot>;
}

interface PendingWrite {
  expected_revision: number;
  request_id: string;
  context_key: string;
  snapshot: EchoEditorDraftSnapshot;
}
interface DraftSession {
  active: boolean;
  ready: boolean;
  draftId: string;
  ownerId: number;
  key: string;
  contextKey: string;
  revision: number;
  baseline: string;
  decisionPending: boolean;
  recovering: boolean;
  restoringTarget: string | null;
  paused: boolean;
  closed: boolean;
  error: boolean;
  conflict: boolean;
  controller: AbortController;
  write: PendingWrite | null;
  saving: Promise<EchoEditorDraftResponse | null> | null;
  closeRequest: { expected_revision: number; request_id: string } | null;
  closing: Promise<void> | null;
  response: EchoEditorDraftResponse | null;
}

const httpStatus = (error: unknown) => (error as { response?: { status?: number } })?.response?.status;
const uuid = () => crypto.randomUUID();
const errorText = (error: unknown, fallback: string) => error instanceof Error && !httpStatus(error)
  ? error.message : fallback;

/** Autosave writes only an isolated editor workspace. Issuing a clinical report
 * remains an explicit page action after pause() has drained the serial queue. */
export function useEchoEditorDraft(options: UseEchoEditorDraftOptions) {
  const { enabled, contextKey, userId } = options;
  const [status, setStatus] = useState<EchoDraftStatus>("disabled");
  const [draftId, setDraftId] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<EchoEditorDraftResponse | null>(null);
  const [closedRecovery, setClosedRecovery] = useState<{
    laudoId: number; result: { id: number; request_id: string; updated: true } | null;
  } | null>(null);
  const [tick, setTick] = useState(0);
  const [, refreshController] = useState(0);
  const session = useRef<DraftSession | null>(null);
  const initialContext = useRef<{ identity: string; baseline: string } | null>(null);
  const restore = useRef(options.onRestore);
  restore.current = options.onRestore;

  let parsed: EchoEditorDraftSnapshot | null = null;
  let serialized = "";
  let invalid = "";
  try {
    parsed = cloneEchoEditorDraftSnapshot(options.snapshot);
    serialized = JSON.stringify(parsed);
  } catch (cause) {
    invalid = errorText(cause, "Não foi possível preparar o rascunho.");
  }
  const latest = useRef<EchoEditorDraftSnapshot | null>(parsed);
  const propSnapshot = useRef(serialized);
  // A flush override (e.g. the ID just created by dictation) survives rerenders
  // until the parent actually supplies a new snapshot.
  if (propSnapshot.current !== serialized) {
    propSnapshot.current = serialized;
    latest.current = parsed;
  }
  const fingerprint = parsed ? echoDraftFingerprint(parsed) : "";
  const alive = (current: DraftSession) => current.active && session.current === current;

  const performSave = useCallback((force = false): Promise<EchoEditorDraftResponse | null> => {
    const current = session.current;
    if (!current || !current.active || !current.ready || current.closed || current.decisionPending
      || current.restoringTarget || current.conflict || current.closeRequest) {
      return Promise.reject(new Error("Conclua a recuperação do rascunho antes de emitir."));
    }
    if (current.saving) return current.saving;
    current.error = false;
    setError(null);
    const operation = (async () => {
      try {
        while (alive(current)) {
          const snapshot = cloneEchoEditorDraftSnapshot(latest.current);
          const content = echoDraftFingerprint(snapshot);
          if (!current.write && content === current.baseline && (current.revision > 0 || !force)) {
            setStatus(current.paused ? "paused" : current.revision ? "saved" : "idle");
            return current.response;
          }
          current.write ??= {
            expected_revision: current.revision,
            request_id: uuid(),
            context_key: current.contextKey,
            snapshot,
          };
          const request = current.write;
          setStatus("saving");
          const result = await api.put(`/laudos/editor-drafts/${current.draftId}`, request,
            { timeout: 15_000, signal: current.controller.signal, headers: { "X-Editor-Owner-Id": current.ownerId } });
          if (!alive(current)) throw new Error("A sessão do rascunho mudou.");
          const response = parseEchoEditorDraftResponse(result.data, current.draftId, current.contextKey);
          if (echoDraftFingerprint(response.snapshot) !== echoDraftFingerprint(request.snapshot)
            || response.revision <= request.expected_revision) {
            throw new Error("O servidor não confirmou o conteúdo do rascunho. Tente novamente.");
          }
          current.revision = response.revision;
          current.baseline = echoDraftFingerprint(request.snapshot);
          current.response = response;
          current.write = null;
          setLastSavedAt(response.updated_at);
          // The next iteration drains edits made during this request. It never
          // acknowledges a newer editor snapshot using an older response.
        }
        throw new Error("A sessão do rascunho mudou.");
      } catch (cause) {
        if (alive(current)) {
          current.error = true;
          if (httpStatus(cause) === 409) {
            current.conflict = true;
            setStatus("conflict");
            setError("Este rascunho mudou em outra sessão. O preenchimento atual foi preservado; reabra o exame para conferir as versões.");
          } else {
            setStatus("error");
            setError(errorText(cause, httpStatus(cause) === 401
              ? "A sessão expirou. Entre novamente para recuperar o rascunho."
              : "Não foi possível salvar o rascunho. O preenchimento atual permanece nesta tela."));
          }
        }
        throw cause;
      }
    })();
    current.saving = operation;
    void operation.finally(() => { if (current.saving === operation) current.saving = null; }).catch(() => {});
    return operation;
  }, []);

  useEffect(() => {
    setRecovery(null);
    setClosedRecovery(null);
    setLastSavedAt(null);
    setError(null);
    setDraftId(null);
    if (!enabled || !userId) {
      setStatus("disabled");
      return;
    }
    if (!latest.current) {
      setStatus("error");
      setError("Não foi possível preparar o rascunho.");
      return;
    }
    let current: DraftSession;
    try {
      const key = echoDraftStorageKey(userId, contextKey);
      if (initialContext.current?.identity !== key) {
        initialContext.current = { identity: key, baseline: echoDraftFingerprint(latest.current) };
      }
      const stored = sessionStorage.getItem(key);
      const id = isEchoDraftUuid(stored) ? stored : uuid();
      if (stored !== id) sessionStorage.setItem(key, id);
      current = {
        active: true, ready: false, draftId: id, ownerId: userId, key, contextKey, revision: 0,
        baseline: initialContext.current.baseline, decisionPending: false, recovering: false, restoringTarget: null,
        paused: false, closed: false, error: false, conflict: false,
        controller: new AbortController(), write: null, saving: null, closeRequest: null,
        closing: null, response: null,
      };
      session.current = current;
      setDraftId(id);
      setStatus("loading");
    } catch {
      setStatus("error");
      setError("Este navegador não permitiu preparar a recuperação do rascunho. Mantenha a página aberta e tente novamente.");
      return;
    }
    const load = async () => {
      try {
        let result;
        try {
          result = await api.get(`/laudos/editor-drafts/${current.draftId}`,
            { timeout: 15_000, signal: current.controller.signal, headers: { "X-Editor-Owner-Id": current.ownerId } });
        } catch (cause) {
          if (httpStatus(cause) !== 410 || !alive(current)) throw cause;
          if (latest.current?.editor === "existing-echo") {
            const detail = (cause as { response?: { data?: { detail?: any } } }).response?.data?.detail;
            if (detail?.code !== "EDITOR_DRAFT_CLOSED" || detail.laudo_id !== latest.current.source?.laudo_id
              || (detail.apply_result !== null && (!detail.apply_result || detail.apply_result.id !== detail.laudo_id
                || detail.apply_result.updated !== true || !isEchoDraftUuid(detail.apply_result.request_id)))) {
              throw new Error("O encerramento da atualização precisa ser conferido no laudo oficial.");
            }
            current.closed = true;
            setClosedRecovery({ laudoId: detail.laudo_id, result: detail.apply_result });
            setStatus("closed");
            return;
          }
          // A completed workspace must never resurrect an issued draft. A new
          // UUID starts a separate workspace without reusing the closed one.
          const id = uuid();
          sessionStorage.setItem(current.key, id);
          current.draftId = id;
          setDraftId(id);
          result = await api.get(`/laudos/editor-drafts/${id}`,
            { timeout: 15_000, signal: current.controller.signal, headers: { "X-Editor-Owner-Id": current.ownerId } });
        }
        if (!alive(current)) return;
        const response = parseEchoEditorDraftResponse(result.data, current.draftId, current.contextKey);
        if (response.snapshot.editor !== latest.current?.editor
          || (response.snapshot.editor === "existing-echo" && response.snapshot.source?.laudo_id !== latest.current?.source?.laudo_id)) {
          throw new Error("O rascunho não corresponde a este laudo.");
        }
        current.response = response;
        current.revision = response.revision;
        current.baseline = echoDraftFingerprint(response.snapshot);
        current.ready = true;
        current.decisionPending = true;
        setRecovery(response);
        setStatus("recovery");
      } catch (cause) {
        if (!alive(current)) return;
        if (httpStatus(cause) === 404) {
          current.ready = true;
          setStatus(latest.current && echoDraftFingerprint(latest.current) !== current.baseline ? "pending" : "idle");
        } else {
          current.error = true;
          setStatus("error");
          setError(errorText(cause, httpStatus(cause) === 401
            ? "A sessão expirou. Entre novamente para recuperar o rascunho."
            : "Não foi possível consultar o rascunho. O preenchimento atual foi preservado."));
        }
      }
    };
    void load();
    return () => {
      current.active = false;
      current.controller.abort();
      if (session.current === current) session.current = null;
    };
  }, [enabled, userId, contextKey, tick]);

  useEffect(() => {
    const current = session.current;
    if (invalid) {
      if (current) current.error = true;
      setStatus("error");
      setError(invalid);
      return;
    }
    if (!current?.ready || current.decisionPending || current.paused || current.closed
      || current.error || current.conflict) return;
    if (current.restoringTarget) {
      if (fingerprint !== current.restoringTarget) return;
      current.restoringTarget = null;
      refreshController((revision) => revision + 1);
    }
    if (!latest.current || echoDraftFingerprint(latest.current) === current.baseline) {
      if (status === "pending" || status === "loading") setStatus(current.revision ? "saved" : "idle");
      return;
    }
    if (!current.saving) setStatus("pending");
    const timer = setTimeout(() => { void performSave().catch(() => {}); }, 1500);
    return () => clearTimeout(timer);
  }, [fingerprint, invalid, status, draftId, performSave]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      const current = session.current;
      if (!current?.active || current.closed) return;
      if (current.saving || current.write || (latest.current && (echoDraftFingerprint(latest.current) !== current.baseline
        || pendingEchoDraftImages(latest.current) > 0))) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  const flush = useCallback((override?: EchoEditorDraftSnapshot) => {
    if (override) latest.current = cloneEchoEditorDraftSnapshot(override);
    return performSave(true);
  }, [performSave]);

  const resumeRecovered = useCallback(async () => {
    const current = session.current;
    if (!current?.response || !current.active || !current.decisionPending || current.recovering) return;
    current.recovering = true;
    setStatus("loading");
    try {
      const recovered = cloneEchoEditorDraftSnapshot(current.response.snapshot);
      const result = await restore.current(recovered);
      if (!alive(current)) return;
      const applied = cloneEchoEditorDraftSnapshot(result ?? recovered);
      current.restoringTarget = echoDraftFingerprint(applied);
      current.decisionPending = false;
      current.recovering = false;
      current.error = false;
      setRecovery(null);
      setLastSavedAt(current.response.updated_at);
      setStatus("pending");
    } catch (cause) {
      if (!alive(current)) return;
      current.recovering = false;
      setStatus("recovery");
      setError(errorText(cause, "Não foi possível recuperar este rascunho. O preenchimento atual foi preservado."));
    }
  }, []);

  const continueFresh = useCallback(() => {
    const current = session.current;
    if (!current?.active || !current.decisionPending || current.recovering) return;
    if (current.response?.snapshot.submission) {
      setError("Há uma tentativa de salvamento registrada. Retome o rascunho para conferir o resultado antes de continuar.");
      return;
    }
    if (current.response && latest.current && !sameEchoDraftSource(current.response.snapshot, latest.current)) {
      setError("A versão oficial mudou. Retome a cópia para conferência; ela não será substituída pela versão atual.");
      return;
    }
    if (latest.current?.editor === "existing-echo") {
      try {
        if (sessionStorage.getItem(current.key) === current.draftId) sessionStorage.removeItem(current.key);
        current.active = false;
        setTick((value) => value + 1);
      } catch { setError("Não foi possível iniciar uma nova cópia. O rascunho salvo foi preservado."); }
      return;
    }
    current.decisionPending = false;
    setRecovery(null);
    setError(null);
    setStatus("pending");
  }, []);

  const pause = useCallback(async () => {
    const current = session.current;
    if (!current?.active) throw new Error("O rascunho ainda não está disponível.");
    current.paused = true;
    try {
      await flush();
      if (!alive(current)) throw new Error("A sessão do rascunho mudou.");
      setStatus("paused");
    } catch (cause) {
      current.paused = false;
      throw cause;
    }
  }, [flush]);

  const resume = useCallback(() => {
    const current = session.current;
    if (!current?.active || current.closed || current.closeRequest) return;
    current.paused = false;
    if (!current.error && !current.conflict) setStatus("pending");
  }, []);

  const close = useCallback((): Promise<void> => {
    const current = session.current;
    if (!current?.active || (!current.closeRequest && (!current.paused || current.saving || current.write || !current.revision
      || !latest.current || echoDraftFingerprint(latest.current) !== current.baseline))) {
      return Promise.reject(new Error("O rascunho precisa estar salvo antes de encerrar a emissão."));
    }
    if (current.closing) return current.closing;
    current.closeRequest ??= { expected_revision: current.revision, request_id: uuid() };
    const operation = (async () => {
      try {
        const result = await api.post(`/laudos/editor-drafts/${current.draftId}/close`, current.closeRequest,
          { timeout: 15_000, signal: current.controller.signal, headers: { "X-Editor-Owner-Id": current.ownerId } });
        if (!alive(current)) return;
        const confirmation = result.data as { draft_id?: string; closed?: boolean; revision?: number } | null;
        if (!confirmation || confirmation.draft_id !== current.draftId || confirmation.closed !== true
          || !Number.isSafeInteger(confirmation.revision) || Number(confirmation.revision) <= current.closeRequest!.expected_revision) {
          throw new Error("O servidor não confirmou o encerramento deste rascunho.");
        }
        current.revision = confirmation.revision!;
        current.closed = true;
        if (sessionStorage.getItem(current.key) === current.draftId) sessionStorage.removeItem(current.key);
        setStatus("closed");
        setError(null);
      } catch (cause) {
        if (alive(current)) {
          current.error = true;
          setStatus(httpStatus(cause) === 409 ? "conflict" : "error");
          setError(latest.current?.editor === "existing-echo"
            ? "O encerramento do rascunho privado não foi confirmado. Confira a cópia antes de continuar."
            : "O laudo foi emitido, mas o encerramento do rascunho não foi confirmado. Tente concluir o encerramento; não emita novamente.");
        }
        throw cause;
      }
    })();
    current.closing = operation;
    void operation.finally(() => { if (current.closing === operation) current.closing = null; }).catch(() => {});
    return operation;
  }, []);

  const retry = useCallback(async () => {
    const current = session.current;
    if (current?.closeRequest) return close();
    if (!current?.ready) { setTick((value) => value + 1); return; }
    await flush();
  }, [close, flush]);

  const acknowledgeClosed = useCallback(() => {
    const current = session.current;
    if (!current?.active || !current.closed || !closedRecovery || latest.current?.editor !== "existing-echo") {
      throw new Error("Confira o resultado deste rascunho antes de continuar.");
    }
    if (sessionStorage.getItem(current.key) === current.draftId) sessionStorage.removeItem(current.key);
  }, [closedRecovery]);

  const acknowledgeApplied = useCallback((result: { id: number; request_id: string; updated: boolean }, requestId: string) => {
    const current = session.current;
    if (!current?.active || !current.paused || current.closed || latest.current?.editor !== "existing-echo"
      || latest.current.submission?.status !== "pending" || result.id !== latest.current.source?.laudo_id
      || result.updated !== true || !isEchoDraftUuid(requestId) || result.request_id !== requestId) {
      throw new Error("O servidor não confirmou a atualização deste laudo.");
    }
    current.closed = true;
    if (sessionStorage.getItem(current.key) === current.draftId) sessionStorage.removeItem(current.key);
    setStatus("closed");
  }, []);

  const discardExisting = useCallback(async () => {
    const current = session.current;
    if (!current?.active || !current.ready || !current.revision || current.saving
      || latest.current?.editor !== "existing-echo" || latest.current.submission
      || (current.decisionPending && current.response?.snapshot.submission)) {
      throw new Error("Uma tentativa de atualização precisa ser conferida antes de descartar o rascunho.");
    }
    current.paused = true;
    current.closeRequest ??= { expected_revision: current.revision, request_id: uuid() };
    await close();
  }, [close]);

  const blocked = !enabled || !userId || ["disabled", "loading", "recovery", "error", "conflict", "closed"].includes(status)
    || Boolean(session.current?.restoringTarget) || Boolean(session.current?.closeRequest)
    || Boolean(invalid) || Boolean(parsed?.submission)
    || Boolean(session.current?.paused && fingerprint !== session.current.baseline);
  return {
    status, draftId, lastSavedAt, error, recovery, closedRecovery, blocked, canEmit: !blocked,
    pendingImages: parsed ? pendingEchoDraftImages(parsed) : 0,
    resumeRecovered, continueFresh, flush, pause, resume, close, retry, acknowledgeClosed, acknowledgeApplied, discardExisting,
  };
}

export type EchoEditorDraftController = ReturnType<typeof useEchoEditorDraft>;
