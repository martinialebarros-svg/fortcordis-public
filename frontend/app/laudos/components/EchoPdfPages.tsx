"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy, RenderTask } from "pdfjs-dist";

type Props = { blob: Blob };
const TITLE = "Prévia do laudo em PDF — rascunho";

/** Render the actual PDF bytes without depending on a native PDF plug-in.
 * Only the selected page is rendered. No document is sent to another service. */
export default function EchoPdfPages({ blob }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const source = useRef({ blob, generation: 0 });
  if (source.current.blob !== blob) source.current = { blob, generation: source.current.generation + 1 };
  const sourceGeneration = source.current.generation;
  const [document, setDocument] = useState<{ blob: Blob; retry: number; pdf: PDFDocumentProxy } | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [width, setWidth] = useState(800);
  const [retry, setRetry] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [renderError, setRenderError] = useState("");
  const [readyPage, setReadyPage] = useState("");
  const activeDocument = document?.blob === blob && document.retry === retry ? document.pdf : null;
  const pageKey = `${sourceGeneration}|${retry}|${pageNumber}|${width}`;
  const pageReady = Boolean(activeDocument && readyPage === pageKey);

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const measure = () => setWidth(Math.max(1, Math.min(900, node.clientWidth || 800)));
    measure();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(measure);
      observer.observe(node);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let task: PDFDocumentLoadingTask | null = null;
    setLoadError(""); setRenderError(""); setReadyPage(""); setPageNumber(1); setDocument(null);
    const load = async () => {
      try {
        // Both library and worker are bundled locally and loaded only on demand.
        const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
        if (cancelled || source.current.blob !== blob) return;
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/legacy/build/pdf.worker.min.mjs", import.meta.url,
        ).toString();
        // Blob URLs use PDF.js' XMLHttpRequest network path, which can fail
        // with status 0 under the actual Next/WebKit CSP. Read the validated
        // Blob directly instead. Every load/retry owns a fresh ArrayBuffer;
        // PDF.js may transfer it to the worker without detaching our source.
        const data = new Uint8Array(await blob.arrayBuffer());
        if (cancelled || source.current.blob !== blob) return;
        task = pdfjs.getDocument({ data, useWorkerFetch: false, isEvalSupported: false });
        const pdf = await task.promise;
        if (cancelled || source.current.blob !== blob) return;
        if (!Number.isSafeInteger(pdf.numPages) || pdf.numPages < 1) throw new Error("Empty PDF");
        setDocument({ blob, retry, pdf });
      } catch {
        if (!cancelled && source.current.blob === blob) setLoadError("Não foi possível visualizar o PDF. Tente novamente ou abra a prévia em outra aba.");
      }
    };
    void load();
    return () => {
      cancelled = true;
      // PDFDocumentLoadingTask.destroy also destroys its document transport and
      // worker, including a document that finished loading before this cleanup.
      if (task) void task.destroy().catch(() => {});
    };
  }, [blob, retry]);

  useEffect(() => {
    if (!activeDocument || !canvas.current) return;
    let cancelled = false;
    let page: PDFPageProxy | null = null;
    let task: RenderTask | null = null;
    const target = canvas.current;
    setRenderError(""); setReadyPage("");
    const render = async () => {
      try {
        page = await activeDocument.getPage(pageNumber);
        if (cancelled || source.current.blob !== blob) { page.cleanup(); return; }
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: width / base.width });
        const outputScale = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
        target.width = Math.max(1, Math.floor(viewport.width * outputScale));
        target.height = Math.max(1, Math.floor(viewport.height * outputScale));
        target.style.width = `${Math.floor(viewport.width)}px`;
        target.style.height = "auto";
        task = page.render({ canvas: target, viewport,
          transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0] });
        await task.promise;
        if (!cancelled && source.current.blob === blob) setReadyPage(pageKey);
      } catch {
        if (!cancelled && source.current.blob === blob) setRenderError("Não foi possível visualizar esta página. Tente novamente ou abra a prévia em outra aba.");
      }
    };
    void render();
    return () => {
      cancelled = true;
      task?.cancel();
      if (task) void task.promise.catch(() => {}).then(() => page?.cleanup()).catch(() => {});
      else page?.cleanup();
    };
  }, [activeDocument, pageNumber, width, pageKey, blob]);

  const error = loadError || renderError;
  return <section title={TITLE} aria-label={TITLE} className="mt-3 min-w-0 rounded-lg border border-slate-300 bg-slate-100 p-2 sm:p-3">
    {activeDocument && <nav aria-label="Páginas da prévia" className="mb-3 flex flex-wrap items-center justify-center gap-3 text-sm">
      <button type="button" disabled={pageNumber <= 1} onClick={() => setPageNumber((number) => number - 1)}
        className="rounded border border-slate-300 bg-white px-3 py-2 font-semibold disabled:opacity-40">Página anterior</button>
      <p aria-live="polite" className="text-slate-700">Página {pageNumber} de {activeDocument.numPages}</p>
      <button type="button" disabled={pageNumber >= activeDocument.numPages} onClick={() => setPageNumber((number) => number + 1)}
        className="rounded border border-slate-300 bg-white px-3 py-2 font-semibold disabled:opacity-40">Próxima página</button>
    </nav>}
    {!error && !pageReady && <p role="status" className="mb-2 text-center text-sm text-teal-800">Carregando página do PDF…</p>}
    {error && <div role="alert" className="mb-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
      <p>{error}</p><button type="button" onClick={() => setRetry((value) => value + 1)} className="mt-2 rounded border border-amber-400 px-3 py-1.5 font-semibold">Tentar visualizar novamente</button>
    </div>}
    <div ref={container} className="flex min-w-0 justify-center overflow-hidden">
      <canvas key={pageKey} ref={canvas} role="img" aria-label={`Página ${pageNumber} do PDF de rascunho`}
        className={`block h-auto max-w-full bg-white shadow-sm ${pageReady && !error ? "" : "invisible"}`}>
        Página {pageNumber} da prévia. Use o link de abertura do PDF para visualizar o documento em outra aba.
      </canvas>
    </div>
  </section>;
}
