"use client";

import { AlertTriangle, ArrowRight, Copy, FileText } from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoClinicalRadarAsideProps = LooseAtendimentoComponentProps;

export default function AtendimentoClinicalRadarAside(props: AtendimentoClinicalRadarAsideProps) {
  const {
    alertasAtivos,
    autosaveLabel,
    autosaveState,
    clinicalSummary,
    formatDate,
    form,
    getBadgeStatusClass,
    getGravidadeClass,
    herdarAtendimentoAnterior,
    historicoPaciente,
    pacienteNomeExibicao,
    preenchimentoConsultaLabel,
    selecionado,
  } = props;

  return (
    <>
      <section className="rounded-[26px] border border-slate-200 bg-gradient-to-br from-white to-slate-50 p-5 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-teal-50 p-3">
            <FileText className="h-5 w-5 text-teal-600" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Radar do caso</p>
            <h2 className="text-lg font-semibold text-slate-900">Status rapido</h2>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <div className="rounded-[20px] border border-slate-200 bg-white px-4 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Preenchimento</p>
            <p className="mt-3 text-3xl font-semibold text-slate-900">{clinicalSummary.completeness}%</p>
            <p className="mt-1 text-sm text-slate-600">{preenchimentoConsultaLabel}</p>
          </div>
          <div className="rounded-[20px] border border-slate-200 bg-white px-4 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Sincronizacao</p>
            <p className="mt-3 text-sm font-semibold text-slate-900">{autosaveLabel}</p>
            <p className="mt-1 text-sm text-slate-600">
              {autosaveState === "error"
                ? "Ha alteracoes nao sincronizadas. Use Salvar atendimento para tentar novamente."
                : autosaveState === "dirty" || autosaveState === "saving"
                  ? "As alteracoes ainda estao sendo sincronizadas."
                  : selecionado ? "Atendimento salvo em edicao continua." : "Rascunho local ate o primeiro salvamento."}
            </p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-[20px] border border-slate-200 bg-white px-4 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Fluxo clinico</p>
            <div className="mt-3 space-y-2 text-sm text-slate-700">
              <p>Queixa e anamnese: {form.queixa_principal.trim() || form.anamnese.trim() ? "em andamento" : "pendente"}</p>
              <p>Plano e retorno: {form.plano_terapeutico.trim() || form.retorno_recomendado.trim() ? "em andamento" : "pendente"}</p>
              <p>Exames solicitados: {form.exames.filter((item: any) => (item.tipo_exame || "").trim()).length}</p>
              <p>Itens prescritos: {form.prescricao_itens.filter((item: any) => item.medicamento_id || item.medicamento_nome.trim()).length}</p>
            </div>
          </div>
          <div className="rounded-[20px] border border-slate-200 bg-white px-4 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Fechamento</p>
            <div className="mt-3 space-y-2 text-sm text-slate-700">
              <p>Status: {form.status || "Triagem"}</p>
              <p>Prognostico: {form.diagnostico.prognostico || "Nao definido"}</p>
              <p>Paciente: {pacienteNomeExibicao || "Nao selecionado"}</p>
              <p>Alertas ativos: {alertasAtivos.length}</p>
            </div>
          </div>
        </div>

        {clinicalSummary.pending.length > 0 ? (
          <div className="mt-5 rounded-[22px] border border-amber-200 bg-amber-50 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.25em] text-amber-700">Pendencias mais proximas</p>
            <div className="mt-3 space-y-2 text-sm text-amber-900">
              {clinicalSummary.pending.slice(0, 3).map((item: string) => (
                <p key={item}>{item}</p>
              ))}
            </div>
          </div>
        ) : (
          <div className="mt-5 rounded-[22px] border border-emerald-200 bg-emerald-50 px-4 py-4 text-sm text-emerald-800">
            O caso ja tem base suficiente para seguir para exames, prescricao e fechamento.
          </div>
        )}
      </section>

      <section className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-amber-50 p-3">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Leitura rapida</p>
            <h2 className="text-lg font-semibold text-slate-900">Alertas e historico</h2>
          </div>
        </div>

        <div className="mt-5 space-y-3">
          {alertasAtivos.length > 0 ? (
            alertasAtivos.map((alerta: any) => (
              <div key={alerta.id} className={`rounded-[20px] border px-4 py-3 ${getGravidadeClass(alerta.gravidade)}`}>
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold">{alerta.titulo}</p>
                  <span className="rounded-full bg-white/70 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.2em]">
                    {alerta.gravidade}
                  </span>
                </div>
                <p className="mt-2 text-sm">{alerta.descricao}</p>
              </div>
            ))
          ) : (
            <div className="rounded-[20px] border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
              Nenhum alerta ativo para o paciente selecionado.
            </div>
          )}
        </div>

        <div className="mt-6 border-t border-slate-200 pt-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Ultimos contatos</p>
              <h3 className="mt-1 text-sm font-semibold text-slate-900">Historico recente</h3>
            </div>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
              {historicoPaciente?.atendimentos.length || 0} registros
            </span>
          </div>

          {Number(form.paciente_id) > 0 && (
            <a href={`/pacientes/mesclagens?paciente=${Number(form.paciente_id)}`} target="_blank" rel="noopener noreferrer"
              className="mt-3 inline-block text-sm font-semibold text-blue-800 underline">
              Revisar duplicidade do paciente
              <span className="sr-only"> (abre em nova aba)</span>
            </a>
          )}

          <div className="mt-4 space-y-3">
            {historicoPaciente?.atendimentos.slice(0, 4).map((atendimento: any) => (
              <div key={atendimento.id} className="rounded-[20px] border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-slate-900">#{atendimento.id}</p>
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${getBadgeStatusClass(atendimento.status)}`}>
                    {atendimento.status}
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-500">{formatDate(atendimento.data_atendimento)}</p>
                <p className="mt-2 text-sm text-slate-700">
                  {atendimento.diagnostico_principal || atendimento.queixa_principal || "Sem resumo clinico"}
                </p>
                <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
                  <ArrowRight className="h-3.5 w-3.5" />
                  <span>{atendimento.veterinario || "Veterinario nao informado"}</span>
                </div>
                {atendimento.id !== selecionado ? (
                  <button
                    type="button"
                    onClick={() => void herdarAtendimentoAnterior(atendimento.id)}
                    className="mt-3 inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Herdar para novo atendimento
                  </button>
                ) : null}
              </div>
            ))}
            {!historicoPaciente?.atendimentos.length ? (
              <div className="rounded-[20px] border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
                O historico do paciente aparecera aqui conforme novos atendimentos forem salvos.
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </>
  );
}
