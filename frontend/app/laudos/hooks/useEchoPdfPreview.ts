"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type EchoPdfPreviewOptions = {
  snapshotKey: string;
  scopeKey: string;
  enabled?: boolean;
  requestPreview: (signal: AbortSignal) => Promise<Blob>;
  timeoutMs?: number;
};
type State = {
  visible: boolean;
  status: "idle" | "loading" | "ready" | "error" | "stale";
  url: string | null;
  blob: Blob | null;
  error: string | null;
  scopeKey: string;
  snapshotKey: string;
};
const ERROR = "Não foi possível gerar a prévia. Seu rascunho continua preservado. Tente novamente.";
const TIMEOUT = "A prévia demorou mais que o esperado. Seu rascunho continua preservado. Tente novamente.";

async function validatePdf(blob: Blob) {
  if (!(blob instanceof Blob) || blob.size < 5 || blob.type.split(";")[0].toLowerCase() !== "application/pdf") throw new Error("Invalid PDF");
  const head = blob.slice(0, 5);
  const signature = typeof head.text === "function" ? await head.text() : await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Unreadable PDF"));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(head);
  });
  if (signature !== "%PDF-") throw new Error("Invalid PDF signature");
}

/** The payload remains in the caller. No clinical snapshot or PDF URL is stored
 * in browser persistence. A late response cannot cross a patient/user/revision. */
export function useEchoPdfPreview(options: EchoPdfPreviewOptions) {
  const { snapshotKey, scopeKey, enabled = true } = options;
  const latest = useRef({ ...options, enabled });
  latest.current = { ...options, enabled };
  const mounted = useRef(true);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const objectUrl = useRef<string | null>(null);
  const activeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const observed = useRef({ scopeKey, snapshotKey, enabled });
  const [state, setState] = useState<State>({ visible: false, status: "idle", url: null, blob: null, error: null, scopeKey, snapshotKey });

  const release = useCallback(() => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
  }, []);
  const cancel = useCallback(() => {
    generation.current += 1;
    if (activeTimer.current !== null) clearTimeout(activeTimer.current);
    activeTimer.current = null;
    controller.current?.abort();
    controller.current = null;
    release();
  }, [release]);
  const close = useCallback(() => {
    cancel();
    const current = latest.current;
    setState({ visible: false, status: "idle", url: null, blob: null, error: null, scopeKey: current.scopeKey, snapshotKey: current.snapshotKey });
  }, [cancel]);

  useEffect(() => {
    const previous = observed.current;
    observed.current = { scopeKey, snapshotKey, enabled };
    if (previous.scopeKey === scopeKey && previous.snapshotKey === snapshotKey && previous.enabled === enabled) return;
    cancel();
    setState((value) => ({ visible: enabled && previous.scopeKey === scopeKey && value.visible,
      status: enabled && previous.scopeKey === scopeKey && value.visible ? "stale" : "idle",
      url: null, blob: null, error: null, scopeKey, snapshotKey }));
  }, [scopeKey, snapshotKey, enabled, cancel]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; cancel(); };
  }, [cancel]);

  const generate = useCallback(async () => {
    const captured = latest.current;
    if (!captured.enabled) return;
    cancel();
    const requestGeneration = generation.current;
    const abort = new AbortController();
    controller.current = abort;
    const current = () => mounted.current && generation.current === requestGeneration
      && latest.current.enabled && latest.current.scopeKey === captured.scopeKey && latest.current.snapshotKey === captured.snapshotKey;
    setState({ visible: true, status: "loading", url: null, blob: null, error: null, scopeKey: captured.scopeKey, snapshotKey: captured.snapshotKey });
    const timer = setTimeout(() => {
      if (!current()) return;
      generation.current += 1;
      activeTimer.current = null;
      abort.abort();
      if (controller.current === abort) controller.current = null;
      setState({ visible: true, status: "error", url: null, blob: null, error: TIMEOUT, scopeKey: captured.scopeKey, snapshotKey: captured.snapshotKey });
    }, captured.timeoutMs ?? 30_000);
    activeTimer.current = timer;
    try {
      const blob = await captured.requestPreview(abort.signal);
      if (!current() || abort.signal.aborted) return;
      await validatePdf(blob);
      if (!current() || abort.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      objectUrl.current = url;
      setState({ visible: true, status: "ready", url, blob, error: null, scopeKey: captured.scopeKey, snapshotKey: captured.snapshotKey });
    } catch {
      if (!current() || abort.signal.aborted) return;
      setState({ visible: true, status: "error", url: null, blob: null, error: ERROR, scopeKey: captured.scopeKey, snapshotKey: captured.snapshotKey });
    } finally {
      clearTimeout(timer);
      if (activeTimer.current === timer) activeTimer.current = null;
      if (controller.current === abort) controller.current = null;
    }
  }, [cancel]);

  // Hide old content synchronously, before effects run after a new render.
  const sameScope = enabled && state.scopeKey === scopeKey;
  const sameSnapshot = sameScope && state.snapshotKey === snapshotKey;
  return { generate, close, visible: sameScope && state.visible,
    status: sameSnapshot ? state.status : sameScope && state.visible ? "stale" as const : "idle" as const,
    url: sameSnapshot ? state.url : null, blob: sameSnapshot ? state.blob : null, error: sameSnapshot ? state.error : null };
}
