"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import api from "@/lib/axios";
import { buildEchoPreviousExamRows, echoComparisonMethodLabel, isEchoPreviousExamResponse, type EchoPreviousExamResponse } from "@/lib/echo-previous-exam-comparison";

const REQUEST_TIMEOUT_MS = 8_000;
type Result = { key: string; data?: EchoPreviousExamResponse; error?: boolean };
const dateLabel = (day: string | null) => day ? day.split("-").reverse().join("/") : "Data não registrada";

export default function EchoPreviousExamComparison({ laudoId, pacienteId }: { laudoId: number; pacienteId: number }) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<{ scope: string; id: number | null }>({ scope: "", id: null });
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const scope = `${laudoId}:${pacienteId}`;
  const selectedId = choice.scope === scope ? choice.id : null;
  const requestKey = `${scope}:${selectedId ?? "automatico"}:${attempt}`;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let active = true;
    setResult(null);
    void api.get(`/laudos/${laudoId}/comparacao-anterior`, {
      params: selectedId === null ? undefined : { anterior_id: selectedId },
      timeout: REQUEST_TIMEOUT_MS, signal: controller.signal,
    }).then(({ data }) => {
      if (!active) return;
      if (!isEchoPreviousExamResponse(data, laudoId, pacienteId, selectedId)) throw new Error("Invalid comparison identity or chronology");
      setResult({ key: requestKey, data });
    }).catch(() => {
      if (active && !controller.signal.aborted) setResult({ key: requestKey, error: true });
    });
    return () => { active = false; controller.abort(); };
  }, [open, laudoId, pacienteId, selectedId, requestKey]);
  const currentResult = result?.key === requestKey ? result : null;
  const data = currentResult?.data;
  const rows = data?.anterior ? buildEchoPreviousExamRows(data.atual, data.anterior) : [];

  return <details className="mb-6 min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-4" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer font-semibold text-slate-900">Comparar com exame anterior</summary>
    <p className="mt-2 text-sm text-slate-600">Consulte as medidas registradas em ecocardiogramas anteriores deste paciente.</p>
    {open && <div className="mt-4 space-y-3">
      {!currentResult && <p role="status" className="text-sm text-slate-600">Consultando exames anteriores…</p>}
      {currentResult?.error && <div role="status" className="text-sm text-slate-700">
        <p>Não foi possível carregar a comparação. O laudo atual continua disponível.</p>
        <button type="button" className="mt-2 rounded border border-slate-300 bg-white px-3 py-2 font-medium" onClick={() => setAttempt((value) => value + 1)}>Tentar novamente</button>
        {selectedId !== null && <button type="button" className="ml-2 mt-2 rounded border border-slate-300 bg-white px-3 py-2 font-medium" onClick={() => setChoice({ scope, id: null })}>Voltar à seleção automática</button>}
      </div>}
      {data && <>
        {data.estado === "sem_anterior" && <p className="text-sm text-slate-600">Nenhum ecocardiograma finalizado em data anterior foi encontrado para este paciente.</p>}
        {data.estado === "data_atual_ausente" && <p className="text-sm text-slate-600">Confirme a data do exame atual antes de comparar. Datas ausentes ou futuras não permitem a seleção automática.</p>}
        {data.estado === "tipo_nao_suportado" && <p className="text-sm text-slate-600">Comparação disponível para ecocardiogramas.</p>}
        {data.estado === "data_anterior_ambigua" && <p className="text-sm text-slate-700">Há mais de um laudo na data anterior mais recente. Selecione o exame para comparar.</p>}
        {data.opcoes.length > 0 && <label className="block text-sm font-medium text-slate-700">
          Exame anterior
          <select className="mt-1 block w-full max-w-md rounded border border-slate-300 bg-white p-2" value={data.anterior?.id ?? ""}
            onChange={(event) => setChoice({ scope, id: event.target.value ? Number(event.target.value) : null })}>
            <option value="" disabled>Selecione um exame</option>
            {data.opcoes.map((option) => <option key={option.id} value={option.id}>{dateLabel(option.data_exame)} · laudo #{option.id}</option>)}
          </select>
        </label>}
        {data.anterior && <>
          <div className="grid gap-3 text-sm md:grid-cols-2">
            <div><strong>Anterior · {dateLabel(data.anterior.data_exame)}</strong>
              <p className="mt-1 text-xs text-slate-600">{echoComparisonMethodLabel(data.anterior.medidas)}</p>
              <Link className="mt-1 inline-block underline underline-offset-2" href={`/laudos/${data.anterior.id}`} target="_blank" rel="noopener noreferrer">Abrir laudo #{data.anterior.id}</Link>
            </div>
            <div><strong>Atual · {dateLabel(data.atual.data_exame)}</strong>
              <p className="mt-1 text-xs text-slate-600">{echoComparisonMethodLabel(data.atual.medidas)}</p>
            </div>
          </div>
          {rows.length ? <div className="overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Medidas registradas no exame anterior e atual</caption>
              <thead className="bg-slate-100"><tr>{["Parâmetro", "Anterior", "Atual", "Diferença (atual − anterior)"].map((title) => <th key={title} scope="col" className="px-3 py-2 font-medium">{title}</th>)}</tr></thead>
              <tbody>{rows.map((row) => <tr key={row.key} className="border-t border-slate-100 align-top">
                <th scope="row" className="px-3 py-2 font-medium">{row.label}</th>
                <td className="px-3 py-2">{row.previous}</td><td className="px-3 py-2">{row.current}</td>
                <td className="px-3 py-2">{row.delta}{row.reason && <p className="mt-1 text-xs text-slate-500">{row.reason}</p>}</td>
              </tr>)}</tbody>
            </table>
          </div> : <p className="text-sm text-slate-600">Os exames não contêm dimensões do VE ou AE/Ao para esta comparação.</p>}
          <p className="text-xs leading-relaxed text-slate-600">Diferenças aritméticas entre valores registrados; não indicam evolução clínica por si só. Considere idade, peso, condições do exame e variabilidade de medida. Índices dependentes do peso histórico e parâmetros diastólicos não integram esta comparação. A consulta não altera o laudo nem o PDF.</p>
        </>}
      </>}
    </div>}
  </details>;
}
