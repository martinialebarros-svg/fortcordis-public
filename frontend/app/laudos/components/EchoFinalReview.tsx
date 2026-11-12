"use client";

import type { EchoFinalReviewIssue, EchoReviewTarget } from "@/lib/echo-final-review";
import { useEchoPdfPreview } from "../hooks/useEchoPdfPreview";
import EchoPdfPages from "./EchoPdfPages";

type Props = {
  snapshotKey: string;
  scopeKey: string;
  disabled?: boolean;
  issues: EchoFinalReviewIssue[];
  imageCount: number;
  requestPreview: (signal: AbortSignal) => Promise<Blob>;
  onNavigate: (target: EchoReviewTarget) => void;
};

export default function EchoFinalReview({ snapshotKey, scopeKey, disabled = false, issues, imageCount, requestPreview, onNavigate }: Props) {
  const preview = useEchoPdfPreview({ snapshotKey, scopeKey, enabled: !disabled, requestPreview });
  const attention = issues.filter((item) => item.kind === "attention").length;
  return <section aria-label="Conferência final e prévia do PDF" className="my-4 min-w-0 rounded-xl border border-teal-200 bg-white p-4 shadow-sm">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-teal-950">Conferência final</h2>
        <p className="mt-1 text-xs text-slate-600">Confira identificação, medidas, textos e {imageCount} imagem(ns) selecionada(s) na prévia.</p>
      </div>
      <button type="button" disabled={disabled || preview.status === "loading"} onClick={() => { void preview.generate(); }}
        className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:opacity-50">
        {preview.status === "loading" ? "Gerando prévia…" : preview.url ? "Atualizar prévia do PDF" : "Conferir e ver PDF"}
      </button>
    </div>
    <details className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium text-slate-800">{attention ? `${attention} ponto(s) para conferir` : "Nenhuma pendência detectada pelos avisos automáticos"}{issues.length > attention ? ` · ${issues.length - attention} observação(ões)` : ""}</summary>
      <p className="mt-2 text-xs text-slate-600">Os avisos auxiliam a conferência; a interpretação permanece sob sua decisão.</p>
      {issues.length > 0 && <ul className="mt-2 space-y-2">
        {issues.map((item) => <li key={item.key} className={`min-w-0 rounded border p-3 ${item.kind === "attention" ? "border-amber-200 bg-amber-50" : "border-blue-100 bg-blue-50"}`}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1 break-words"><strong>{item.title}</strong><p className="mt-1 text-xs leading-relaxed">{item.message}</p></div>
            <button type="button" disabled={disabled} aria-label={`Revisar ${item.title}`} onClick={() => { preview.close(); onNavigate(item.target); }}
              className="rounded border border-current px-2 py-1 text-xs font-semibold disabled:opacity-50">Revisar</button>
          </div>
        </li>)}
      </ul>}
    </details>
    {preview.visible && <div className="mt-4 min-w-0 border-t border-slate-200 pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h3 className="text-sm font-semibold text-teal-950">Prévia do PDF · rascunho</h3>
          <p className="mt-1 text-xs text-slate-600">Gerada com o conteúdo atual. A prévia não emite nem substitui o documento oficial.</p></div>
        <button type="button" onClick={preview.close} className="rounded border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700">
          {preview.status === "loading" ? "Cancelar prévia" : "Fechar prévia"}
        </button>
      </div>
      {preview.status === "loading" && <p role="status" className="mt-3 text-sm text-teal-800">Preparando o PDF com as medidas, textos e imagens selecionados…</p>}
      {preview.status === "stale" && <p role="status" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">O conteúdo mudou. Gere uma nova prévia para conferir a versão atual.</p>}
      {preview.error && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">{preview.error}</p>}
      {preview.url && <>
        <a href={preview.url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-sm font-semibold text-teal-800 underline">Abrir prévia em outra aba</a>
        {preview.blob && <EchoPdfPages blob={preview.blob} />}
      </>}
    </div>}
  </section>;
}
