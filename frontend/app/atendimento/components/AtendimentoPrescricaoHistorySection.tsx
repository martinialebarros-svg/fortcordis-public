"use client";

import { ArrowUpRight, Copy, History, Loader2, Pill } from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoPrescricaoHistorySectionProps = LooseAtendimentoComponentProps;

export default function AtendimentoPrescricaoHistorySection(props: AtendimentoPrescricaoHistorySectionProps) {
  const {
    abrindoAtendimentoId,
    abrirAtendimento,
    formatDate,
    herdarAtendimentoAnterior,
    historicoPaciente,
    prescricaoOrigem,
    selecionado,
  } = props;

  const receitasAnteriores = (historicoPaciente?.atendimentos || [])
    .filter((atendimento: any) => atendimento.id !== selecionado && atendimento.prescricao?.total_itens > 0)
    .slice(0, 4);

  if (!historicoPaciente?.paciente?.id) return null;

  return (
    <section className="rounded-[30px] border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-violet-50 p-3 text-violet-700">
            <History className="h-5 w-5" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-violet-700">Prontuario longitudinal</p>
            <h3 className="mt-1 text-lg font-semibold text-slate-950">Historico terapeutico preservado</h3>
            <p className="mt-1 text-sm text-slate-600">
              Consulte receitas anteriores ou copie uma delas como ponto de partida para um novo atendimento.
            </p>
          </div>
        </div>
        <span className="w-fit rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600">
          {receitasAnteriores.length} receita(s) recente(s)
        </span>
      </div>

      {prescricaoOrigem ? (
        <div className="mt-4 rounded-[22px] border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-900">
          Esta receita foi copiada do atendimento #{prescricaoOrigem.atendimento_id}, de {formatDate(prescricaoOrigem.data_atendimento)}.
          Revise doses e orientacoes antes de salvar; o documento original nao sera alterado.
        </div>
      ) : null}

      {receitasAnteriores.length > 0 ? (
        <div className="mt-5 grid gap-3 xl:grid-cols-2">
          {receitasAnteriores.map((atendimento: any) => (
            <article key={atendimento.id} className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-950">Atendimento #{atendimento.id}</p>
                  <p className="mt-1 text-xs text-slate-500">{formatDate(atendimento.data_atendimento)}</p>
                </div>
                <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600">
                  {atendimento.prescricao.total_itens} item(ns)
                </span>
              </div>

              <div className="mt-3 space-y-2">
                {atendimento.prescricao.itens.slice(0, 3).map((item: any, index: number) => (
                  <div key={`${item.id || index}-${item.medicamento_nome}`} className="flex items-start gap-2 text-sm text-slate-700">
                    <Pill className="mt-0.5 h-4 w-4 shrink-0 text-teal-600" />
                    <p>
                      <span className="font-medium text-slate-900">{item.medicamento_nome}</span>
                      {item.dose ? ` · ${item.dose}` : ""}
                      {item.frequencia ? ` · ${item.frequencia}` : ""}
                    </p>
                  </div>
                ))}
                {atendimento.prescricao.total_itens > 3 ? (
                  <p className="text-xs text-slate-500">+ {atendimento.prescricao.total_itens - 3} item(ns) na receita completa</p>
                ) : null}
              </div>

              {atendimento.prescricao.orientacoes_gerais ? (
                <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500">
                  {atendimento.prescricao.orientacoes_gerais}
                </p>
              ) : null}

              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void herdarAtendimentoAnterior(atendimento.id)}
                  className="inline-flex items-center gap-2 rounded-2xl bg-violet-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-violet-700"
                >
                  <Copy className="h-3.5 w-3.5" />
                  Usar em novo atendimento
                </button>
                <button
                  type="button"
                  onClick={() => void abrirAtendimento(atendimento.id)}
                  disabled={abrindoAtendimentoId !== null}
                  className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {abrindoAtendimentoId === atendimento.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  )}
                  Abrir original
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="mt-5 rounded-[24px] border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
          Nenhuma receita anterior para este paciente. A receita deste atendimento sera preservada aqui depois de salva.
        </div>
      )}
    </section>
  );
}
