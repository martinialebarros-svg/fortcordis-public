"use client";

import { useState } from "react";
import { HistoryValue, fieldLabel } from "./AtendimentoHistoricoEdicoes";

type Difference = { campo: string; salvo: unknown; local: unknown };
type Props = { differences: Difference[]; onRecover: () => void; canRecover: boolean };

export default function AtendimentoBackupRecovery({ differences, onRecover, canRecover }: Props) {
  const [comparando, setComparando] = useState(false);
  const [mantida, setMantida] = useState(false);
  return <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4" aria-label="Copia local preservada">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="text-sm font-semibold text-amber-950">Copia local preservada para revisao</p>
        <p className="mt-1 text-sm text-amber-900">{mantida ? "Voce continua com o conteudo salvo. A copia local segue disponivel para comparacao." : "O conteudo salvo foi mantido. Esta copia local pode ser antiga ou conter alteracoes ainda nao sincronizadas."}</p>
      </div>
      <button type="button" onClick={() => setComparando(!comparando)} className="rounded-xl border border-amber-300 bg-white px-3 py-2 text-sm font-medium text-amber-900">{comparando ? "Fechar comparacao" : "Comparar copia local"}</button>
    </div>
    {comparando ? <div className="mt-4 space-y-3">
      {differences.map(({ campo, salvo, local }) => <article key={campo} className="rounded-xl border border-amber-200 bg-white p-3">
        <p className="text-sm font-semibold text-slate-800">{fieldLabel(campo)}</p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="min-w-0"><p className="mb-1 text-xs font-semibold text-teal-700">Conteudo atual no editor</p><div className="max-h-60 overflow-auto whitespace-pre-wrap break-words text-sm"><HistoryValue value={salvo} /></div></div>
          <div className="min-w-0"><p className="mb-1 text-xs font-semibold text-amber-700">Copia local</p><div className="max-h-60 overflow-auto whitespace-pre-wrap break-words text-sm"><HistoryValue value={local} /></div></div>
        </div>
      </article>)}
      {!canRecover ? <p className="text-sm text-amber-900">Esta copia pertence a outro contexto de paciente ou receita. O conteudo foi preservado e nao sera aplicado neste atendimento.</p> : <p className="text-xs text-amber-900">Recuperar substitui os campos mostrados no editor. O salvamento automatico registrara essas alteracoes no historico.</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => { setMantida(true); setComparando(false); }} className="rounded-xl border border-amber-300 bg-white px-3 py-2 text-sm font-medium text-amber-900">Manter conteudo salvo</button>
        <button type="button" disabled={!canRecover || differences.length === 0} onClick={onRecover} className="rounded-xl bg-amber-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">Recuperar copia no editor</button>
      </div>
    </div> : null}
  </section>;
}
