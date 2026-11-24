"use client";

import { useEffect, useId, useState } from "react";
import { listarTodasClinicas } from "@/lib/clinicas";

export interface TutorIdentificacao {
  identificacao_pendente: boolean;
  origem_cadastro: string;
  identificacao_observacoes: string;
}

export default function TutorIdentificacaoFields({ value, onChange }: {
  value: TutorIdentificacao;
  onChange: (value: TutorIdentificacao) => void;
}) {
  const clinicasListId = useId();
  const [consultarClinicas, setConsultarClinicas] = useState(false);
  const [tentativa, setTentativa] = useState(0);
  const [clinicas, setClinicas] = useState<{ id: number; nome: string }[]>([]);
  const [estadoClinicas, setEstadoClinicas] = useState<"idle" | "loading" | "ready" | "error">("idle");

  useEffect(() => {
    if (!consultarClinicas) return;
    let active = true;
    setEstadoClinicas("loading");
    listarTodasClinicas<{ id: number; nome: string }>().then(
      (items) => {
        if (!active) return;
        setClinicas(items);
        setEstadoClinicas("ready");
      },
      () => {
        if (active) setEstadoClinicas("error");
      },
    );
    return () => { active = false; };
  }, [consultarClinicas, tentativa]);

  return (
    <fieldset className="col-span-full rounded-xl border border-slate-200 bg-slate-50 p-3">
      <legend className="px-1 text-sm font-medium text-slate-800">Identificação do tutor</legend>
      <p className="text-sm text-slate-700">{value.identificacao_pendente ? "Identificação pendente" : "Identificação confirmada pela equipe"}</p>
      <p className="mt-1 text-sm text-slate-600">Pode continuar com o primeiro nome. Os demais dados podem ser completados no atendimento.</p>
      <details className="mt-2 space-y-3" onToggle={(event) => {
        if (event.currentTarget.open) setConsultarClinicas(true);
      }}>
      <summary className="cursor-pointer text-sm font-medium text-blue-700">Origem e observações (opcional)</summary>
      <label className="block text-sm">Origem do cadastro / clínica informante
        <input className="mt-1 w-full rounded-lg border bg-white p-2" value={value.origem_cadastro}
          list={clinicasListId} autoComplete="off" onFocus={() => setConsultarClinicas(true)}
          onChange={(event) => onChange({ ...value, origem_cadastro: event.target.value })}
          placeholder="Busque uma clínica ou informe outra origem" />
      </label>
      <datalist id={clinicasListId}>
        {clinicas.map((clinica) => <option key={clinica.id} value={clinica.nome} />)}
      </datalist>
      <p className="text-sm text-slate-600">Selecione uma clínica cadastrada ou informe outra origem.</p>
      {estadoClinicas === "loading" && <p role="status" className="text-sm text-slate-600">Carregando clínicas...</p>}
      {estadoClinicas === "error" && <div className="text-sm text-slate-600">
        <p role="status">Não foi possível carregar as clínicas. Você pode informar a origem manualmente.</p>
        <button type="button" className="font-medium text-blue-700 underline" onClick={() => setTentativa((prev) => prev + 1)}>
          Tentar carregar clínicas novamente
        </button>
      </div>}
      <label className="block text-sm">O que falta confirmar / observações da identificação
        <textarea className="mt-1 w-full rounded-lg border bg-white p-2" value={value.identificacao_observacoes}
          onChange={(event) => onChange({ ...value, identificacao_observacoes: event.target.value })}
          placeholder="Ex.: confirmar sobrenome e contato com a clínica" rows={2} />
      </label>
      </details>
    </fieldset>
  );
}
