"use client";

import { CheckCircle2, ChevronLeft, ChevronRight, ListChecks, Stethoscope } from "lucide-react";
import ClinicalFieldCard from "./ClinicalFieldCard";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoConsultaEditorSectionProps = LooseAtendimentoComponentProps;

export default function AtendimentoConsultaEditorSection(props: AtendimentoConsultaEditorSectionProps) {
  const {
    autosaveLabel,
    clinicalSummary,
    consultaCampoAtivoConfig,
    consultaCampoAtivoIndex,
    consultaEditorCamposVisiveis,
    consultaEditorEtapa,
    consultaEditorEtapas,
    consultaEditorGruposConsolidados,
    consultaEtapasCompletas,
    consultaVerTodosCampos,
    dadosClinicosOrigem,
    form,
    formatDate,
    getClinicalFieldValue,
    goToConsultaCampoAnterior,
    goToConsultaCampoProximo,
    handleConsultaTextareaKeyDown,
    injectClinicalSnippet,
    PROGNOSTICO,
    registerClinicalTextarea,
    salvarFraseRapida,
    savingQuickPhrase,
    setClinicalFieldValue,
    setConsultaCampoAtivo,
    setConsultaEditorEtapa,
    setConsultaVerTodosCampos,
    setField,
  } = props;

  return (
    <section className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl bg-teal-50 p-3">
              <Stethoscope className="h-5 w-5 text-teal-600" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Editor clinico guiado</p>
              <h3 className="text-lg font-semibold text-slate-900">Consulta medica</h3>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-[20px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">Estado da edicao</p>
              <p className="mt-1 font-medium text-slate-900">{autosaveLabel}</p>
            </div>
            <label className="flex items-center gap-2 rounded-[20px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.consulta_concluida === 1}
                onChange={(e) => setField("consulta_concluida", e.target.checked ? 1 : 0)}
                className="h-4 w-4"
              />
              Consulta concluida
            </label>
            {consultaEtapasCompletas ? (
              <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700">
                Etapas clinicas 100% preenchidas
              </span>
            ) : null}
          </div>
        </div>

        {dadosClinicosOrigem ? (
          <div className="rounded-[22px] border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">
            Queixa, anamnese, exame fisico e dados clinicos foram copiados do atendimento #
            {dadosClinicosOrigem.atendimento_id}, de {formatDate(dadosClinicosOrigem.data_atendimento)}.
            Diagnostico, plano terapeutico e triagem NAO foram copiados - revise e preencha antes de salvar.
          </div>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-12">
          <div className="xl:col-span-8 rounded-[24px] border border-slate-200 bg-gradient-to-br from-slate-50 to-white px-5 py-4">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Resumo automatico do caso</p>
            <p className="mt-3 text-sm leading-6 text-slate-700">{clinicalSummary.headline}</p>
            {clinicalSummary.highlights.length > 0 ? (
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {clinicalSummary.highlights.slice(0, 4).map((item: any) => (
                  <div key={item.label} className="rounded-[20px] border border-slate-200 bg-white px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">{item.label}</p>
                    <p className="mt-2 text-sm text-slate-700">{item.text}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          <div className="xl:col-span-4 rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-4">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Fechamento clinico</p>
            <div className="mt-4 space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-[0.2em] text-slate-500">Prognostico</label>
                <select
                  value={form.diagnostico.prognostico}
                  onChange={(e) => setField("diagnostico", { ...form.diagnostico, prognostico: e.target.value })}
                  className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
                >
                  <option value="">Selecione</option>
                  {PROGNOSTICO.map((item: string) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-[20px] border border-slate-200 bg-white px-4 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Pronto para concluir</p>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">{clinicalSummary.coberturaMinima.percentual}%</p>
                  <p className="mt-1 text-xs text-slate-600">minimo exigido para concluir o atendimento</p>
                </div>
                <div className="rounded-[20px] border border-slate-200 bg-white px-4 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Detalhamento</p>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">{clinicalSummary.completeness}%</p>
                  <p className="mt-1 text-xs text-slate-600">do editor clinico preenchido</p>
                </div>
              </div>

              {clinicalSummary.pending.length > 0 ? (
                <div className="rounded-[20px] border border-amber-200 bg-amber-50 px-4 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-amber-700">Pendencias</p>
                  <div className="mt-3 space-y-2 text-sm text-amber-900">
                    {clinicalSummary.pending.map((item: string) => (
                      <p key={item}>{item}</p>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="rounded-[20px] border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  Consulta bem estruturada. O prontuario ja tem base suficiente para historico e retorno.
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Etapas do editor clinico</p>
              <p className="mt-1 text-sm text-slate-700">Mostrando um bloco por vez para reduzir rolagem.</p>
            </div>
            <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
              {consultaEditorEtapas.find((etapa: any) => etapa.key === consultaEditorEtapa)?.titulo || "Anamnese e exame"}
            </span>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            {consultaEditorEtapas.map((etapa: any) => {
              const ativa = consultaEditorEtapa === etapa.key;
              const restante = Math.max(etapa.total - etapa.preenchidos, 0);
              return (
                <button
                  key={etapa.key}
                  type="button"
                  onClick={() => setConsultaEditorEtapa(etapa.key)}
                  className={`rounded-2xl border px-3 py-3 text-left transition ${
                    etapa.concluidaAuto
                      ? ativa
                        ? "border-emerald-400 bg-emerald-100/80"
                        : "border-emerald-200 bg-emerald-50 hover:bg-emerald-100/70"
                      : ativa
                        ? "border-teal-300 bg-teal-50"
                        : "border-slate-200 bg-white hover:bg-slate-100"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-900">{etapa.titulo}</p>
                    <span
                      className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                        etapa.concluidaAuto
                          ? "bg-emerald-600 text-white"
                          : ativa
                            ? "bg-teal-600 text-white"
                            : "bg-slate-200 text-slate-700"
                      }`}
                    >
                      {etapa.percentual}%
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{etapa.descricao}</p>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/70">
                    <div
                      className={`h-full rounded-full transition-all ${etapa.concluidaAuto ? "bg-emerald-500" : "bg-teal-500"}`}
                      style={{ width: `${etapa.percentual}%` }}
                    />
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <p className="text-[11px] font-medium text-slate-600">
                      {etapa.preenchidos}/{etapa.total} campos
                    </p>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.15em] ${
                        etapa.concluidaAuto ? "bg-emerald-200 text-emerald-800" : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {etapa.concluidaAuto ? "Concluida" : `${restante} pendente(s)`}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.25em] text-slate-500">
                {consultaVerTodosCampos ? "Revisao consolidada" : "Campos da etapa"}
              </p>
              <p className="mt-1 text-sm text-slate-700">
                {consultaVerTodosCampos
                  ? "Todos os 11 campos clinicos abertos para revisao antes de salvar ou concluir."
                  : consultaCampoAtivoConfig?.title || "Selecione um campo"}
              </p>
              {!consultaVerTodosCampos ? (
                <>
                  <p className="mt-1 text-xs text-slate-500">
                    Atalhos: Alt + Shift + esquerda/direita para navegar e Ctrl/Cmd + Enter para avancar. Campo com texto
                    = concluido automaticamente.
                  </p>
                  <p className="sr-only" aria-live="polite">
                    {consultaCampoAtivoConfig ? `Campo ativo: ${consultaCampoAtivoConfig.title}` : ""}
                  </p>
                </>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              {!consultaVerTodosCampos ? (
                <>
                  <button
                    type="button"
                    onClick={goToConsultaCampoAnterior}
                    disabled={consultaCampoAtivoIndex <= 0}
                    className="rounded-xl border border-slate-200 bg-white p-2 text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label="Campo anterior"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                    {Math.max(consultaCampoAtivoIndex + 1, 1)}/{Math.max(consultaEditorCamposVisiveis.length, 1)}
                  </span>
                  <button
                    type="button"
                    onClick={goToConsultaCampoProximo}
                    disabled={consultaCampoAtivoIndex >= consultaEditorCamposVisiveis.length - 1}
                    className="rounded-xl border border-slate-200 bg-white p-2 text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label="Proximo campo"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </>
              ) : null}
              <button
                type="button"
                onClick={() => setConsultaVerTodosCampos(!consultaVerTodosCampos)}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
              >
                <ListChecks className="h-3.5 w-3.5" />
                {consultaVerTodosCampos ? "Ver um por vez" : "Ver todos os campos"}
              </button>
            </div>
          </div>

          {!consultaVerTodosCampos ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {consultaEditorCamposVisiveis.map((config: any) => {
                const value = getClinicalFieldValue(config.key);
                const linhas = value.trim() ? value.split("\n").length : 0;
                const concluido = linhas > 0;
                const ativo = consultaCampoAtivoConfig?.key === config.key;
                return (
                  <button
                    key={config.key}
                    type="button"
                    onClick={() => setConsultaCampoAtivo(config.key)}
                    className={`rounded-xl border px-3 py-2 text-left transition ${
                      ativo
                        ? concluido
                          ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                          : "border-teal-300 bg-teal-50 text-teal-900"
                        : concluido
                          ? "border-emerald-200 bg-emerald-50/70 text-emerald-800 hover:bg-emerald-100/70"
                          : "border-slate-200 bg-white text-slate-700 hover:bg-slate-100"
                    }`}
                  >
                    <span className="flex items-center gap-2 text-sm font-medium">
                      {concluido ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : null}
                      {config.title}
                    </span>
                    <span
                      className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        concluido
                          ? "bg-emerald-200 text-emerald-800"
                          : ativo
                            ? "bg-teal-200 text-teal-800"
                            : "bg-slate-200 text-slate-600"
                      }`}
                    >
                      {concluido ? `Concluido · ${linhas} linha(s)` : "Em aberto"}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>

        {consultaVerTodosCampos ? (
          <div className="space-y-5">
            {consultaEditorGruposConsolidados.map((grupo: any) => (
              <div key={grupo.key} className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">{grupo.titulo}</p>
                <div className="space-y-4">
                  {grupo.configs.map((config: any) => (
                    <ClinicalFieldCard
                      key={config.key}
                      config={config}
                      value={getClinicalFieldValue(config.key)}
                      onChange={(value) => setClinicalFieldValue(config.key, value)}
                      onInsertPhrase={(text) => injectClinicalSnippet(config.key, text)}
                      onInsertScaffold={(text) => injectClinicalSnippet(config.key, text)}
                      onClear={() => setClinicalFieldValue(config.key, "")}
                      textareaRef={registerClinicalTextarea(config.key)}
                      className="w-full"
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : consultaCampoAtivoConfig ? (
          <ClinicalFieldCard
            key={consultaCampoAtivoConfig.key}
            config={consultaCampoAtivoConfig}
            value={getClinicalFieldValue(consultaCampoAtivoConfig.key)}
            onChange={(value) => setClinicalFieldValue(consultaCampoAtivoConfig.key, value)}
            onInsertPhrase={(text) => injectClinicalSnippet(consultaCampoAtivoConfig.key, text)}
            onInsertScaffold={(text) => injectClinicalSnippet(consultaCampoAtivoConfig.key, text)}
            onClear={() => setClinicalFieldValue(consultaCampoAtivoConfig.key, "")}
            onSaveAsPhrase={(titulo, texto) => salvarFraseRapida(consultaCampoAtivoConfig.key, titulo, texto)}
            savingPhrase={savingQuickPhrase}
            textareaRef={registerClinicalTextarea(consultaCampoAtivoConfig.key)}
            onTextareaKeyDown={handleConsultaTextareaKeyDown}
            className="w-full"
          />
        ) : (
          <div className="rounded-[22px] border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-600">
            Nenhum campo clinico disponivel para a etapa selecionada.
          </div>
        )}
      </div>
    </section>
  );
}
