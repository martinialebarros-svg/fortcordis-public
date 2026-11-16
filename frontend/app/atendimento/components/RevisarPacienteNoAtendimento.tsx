"use client";

import dynamic from "next/dynamic";
import { useEffect, useId, useRef, useState } from "react";

const RevisaoPacientes = dynamic(() => import("../../pacientes/mesclagens/RevisaoPacientes"), {
  loading: () => <p role="status">Carregando revisão…</p>,
});

export default function RevisarPacienteNoAtendimento({ pacienteId, nome }: { pacienteId: string; nome: string }) {
  const [aberto, setAberto] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const titulo = useId();

  useEffect(() => {
    const elemento = dialog.current;
    if (aberto && elemento && !elemento.open) elemento.showModal();
  }, [aberto]);

  return <>
    <button type="button" onClick={() => setAberto(true)}
      className="mt-2 rounded-lg border border-white/30 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-white/10">
      Revisar duplicidade
    </button>
    {aberto && <dialog ref={dialog} aria-labelledby={titulo} onClose={() => setAberto(false)}
      data-fortcordis-overlay-safe="1"
      className="mx-auto my-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-5xl overflow-y-auto rounded-2xl bg-slate-50 p-0 text-slate-900 shadow-xl backdrop:bg-slate-950/60">
      <div className="space-y-4 p-4 sm:p-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id={titulo} className="text-lg font-bold">Revisar duplicidade do paciente</h2>
            <p className="text-sm text-slate-600">Compare os cadastros e guarde a revisão para depois da consulta.</p>
          </div>
          <button type="button" className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold"
            onClick={() => dialog.current?.close()}>Voltar ao atendimento</button>
        </header>
        <RevisaoPacientes principalInicial={pacienteId} buscaInicial={nome} emAtendimento />
      </div>
    </dialog>}
  </>;
}
