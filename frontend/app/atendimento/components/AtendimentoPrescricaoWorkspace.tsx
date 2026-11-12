"use client";

import {
  AlertTriangle,
  ClipboardPlus,
  Eye,
  FileText,
  Pill,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoPrescricaoWorkspaceProps = LooseAtendimentoComponentProps;

export default function AtendimentoPrescricaoWorkspace(props: AtendimentoPrescricaoWorkspaceProps) {
  const {
    abrirMedicamentoBuscaRapida,
    adicionarItemPrescricaoEmBranco,
    aplicarPresetPrescricao,
    aplicarProtocoloSelecionado,
    autosaveBadgeClass,
    autosaveLabel,
    classificarAlertaPrescricao,
    descartarProtocoloSelecionado,
    editarPresetPrescricao,
    especieRacaExibicao,
    form,
    formatDate,
    gerarPreviewPdf,
    getAlertaPrescricaoClass,
    itensPrescricaoAtivos,
    medicamentosCardiologicos,
    mostrarResultadosBuscaPrescricao,
    nomeNovoPresetPrescricao,
    pacienteNomeExibicao,
    presetPrescricaoEmEdicaoId,
    prescricaoBuscaRapida,
    prescricaoBuscaResultados,
    prescricaoEntradaModo,
    prescricaoErrosCount,
    prescricaoModoFoco,
    prescricaoPreviewAtivo,
    prescricaoPreviewPdf,
    prescricaoSupport,
    prescricaoTemRascunhoInicial,
    prescriptionPresets,
    PROTOCOLOS_PRESCRICAO,
    protocoloPrescricaoRecomendado,
    protocoloPrescricaoSelecionado,
    protocoloPrescricaoSelecionadoDetalhe,
    protocoloPrescricaoSelecionadoGatilho,
    protocoloPrescricaoSelecionadoItensPreview,
    removerPresetPrescricao,
    renderPrescricaoItemCard,
    salvarPresetPrescricaoAtual,
    selecionarMedicamentoBuscaRapida,
    selecionarProtocoloPrescricao,
    setField,
    setNomeNovoPresetPrescricao,
    setPrescricaoBuscaRapida,
    setPrescricaoEntradaModo,
    setPrescricaoModoFoco,
    setPrescricaoPreviewAtivo,
    setPrescricaoPreviewErro,
    setPrescricaoPreviewPdf,
    cancelarEdicaoPresetPrescricao,
  } = props;

  return (
    <section className="space-y-6">
      <section className="overflow-hidden rounded-[30px] border border-teal-100 bg-gradient-to-br from-white via-teal-50/60 to-sky-50 p-6 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-700">Prescricao FortCordis</p>
            <h3 className="mt-2 text-2xl font-semibold text-slate-950">Monte a receita em um fluxo unico e mais legivel</h3>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              Inspirado no fluxo de prontuario da Vetsmart: escolha o tipo do item, busque o medicamento, ajuste a
              apresentacao e revise a dose sem depender de um painel lateral carregado.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-3 py-1.5 text-xs font-medium ${autosaveBadgeClass}`}>
              {autosaveLabel}
            </span>
            <button
              type="button"
              onClick={() => {
                const willHide = prescricaoPreviewAtivo;
                setPrescricaoPreviewAtivo((prev: boolean) => !prev);
                if (willHide) {
                  if (prescricaoPreviewPdf && prescricaoPreviewPdf.startsWith("blob:")) {
                    URL.revokeObjectURL(prescricaoPreviewPdf);
                  }
                  setPrescricaoPreviewPdf(null);
                  setPrescricaoPreviewErro(null);
                } else {
                  setTimeout(() => gerarPreviewPdf(), 100);
                }
              }}
              className={`inline-flex items-center gap-2 rounded-2xl border px-3 py-2 text-sm font-medium transition ${
                prescricaoPreviewAtivo
                  ? "border-teal-300 bg-teal-50 text-teal-700 hover:bg-teal-100"
                  : "border-slate-200 bg-white text-slate-700 hover:bg-slate-100"
              }`}
            >
              <FileText className="h-4 w-4" />
              {prescricaoPreviewAtivo ? "Ocultar preview" : "Preview PDF"}
            </button>
            <button
              type="button"
              onClick={() => setPrescricaoModoFoco((prev: boolean) => !prev)}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
            >
              {prescricaoModoFoco ? "Lateral compacta" : "Expandir editor"}
            </button>
          </div>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-[24px] border border-white/80 bg-white/80 px-4 py-4 shadow-sm backdrop-blur">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Paciente</p>
            <p className="mt-2 text-lg font-semibold text-slate-950">{pacienteNomeExibicao || "Sem paciente"}</p>
            <p className="mt-1 text-sm text-slate-500">
              {pacienteNomeExibicao ? (
                especieRacaExibicao ? (
                  especieRacaExibicao
                ) : (
                  <span className="text-amber-600">Espécie não informada</span>
                )
              ) : (
                "Selecione um paciente"
              )}
            </p>
          </div>
          <div className="rounded-[24px] border border-white/80 bg-white/80 px-4 py-4 shadow-sm backdrop-blur">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Itens ativos</p>
            <p className="mt-2 text-lg font-semibold text-slate-950">{itensPrescricaoAtivos.length}</p>
            <p className="mt-1 text-sm text-slate-500">{medicamentosCardiologicos} item(ns) cardiologicos na biblioteca</p>
          </div>
          <div className="rounded-[24px] border border-white/80 bg-white/80 px-4 py-4 shadow-sm backdrop-blur">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Validacao</p>
            <p className={`mt-2 text-lg font-semibold ${prescricaoErrosCount > 0 ? "text-rose-700" : "text-emerald-700"}`}>
              {prescricaoErrosCount > 0 ? `${prescricaoErrosCount} pendencia(s)` : "Sem pendencias"}
            </p>
            <p className="mt-1 text-sm text-slate-500">Campos obrigatorios: medicamento, dose, frequencia e via.</p>
          </div>
          <div className="rounded-[24px] border border-white/80 bg-white/80 px-4 py-4 shadow-sm backdrop-blur">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Peso de referencia</p>
            <p className="mt-2 text-lg font-semibold text-slate-950">{form.triagem.peso ? `${form.triagem.peso} kg` : "Nao informado"}</p>
            <p className="mt-1 text-sm text-slate-500">Base para calculo automatico e sugestao de apresentacao.</p>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <button
          type="button"
          onClick={() => setPrescricaoEntradaModo("manipulado")}
          className="group rounded-[28px] border border-amber-200 bg-gradient-to-br from-white to-amber-50 p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Entrada rapida</p>
              <h3 className="mt-2 text-xl font-semibold text-slate-950">Adicionar formula manipulada</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                Crie um item livre ou use um medicamento da biblioteca como base, com possibilidade de salvar a
                formula depois.
              </p>
            </div>
            <span className="rounded-2xl bg-amber-100 p-3 text-amber-700 transition group-hover:bg-amber-200">
              <Pill className="h-5 w-5" />
            </span>
          </div>
        </button>

        <button
          type="button"
          onClick={() => setPrescricaoEntradaModo("industrializado")}
          className="group rounded-[28px] border border-teal-200 bg-gradient-to-br from-white to-teal-50 p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-700">Entrada rapida</p>
              <h3 className="mt-2 text-xl font-semibold text-slate-950">Adicionar produto industrializado</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                Busque na biblioteca, escolha a apresentacao e leve a recomendacao de dose direto para o item da
                receita.
              </p>
            </div>
            <span className="rounded-2xl bg-teal-100 p-3 text-teal-700 transition group-hover:bg-teal-200">
              <Search className="h-5 w-5" />
            </span>
          </div>
        </button>
      </section>

      <section className="rounded-[30px] border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Busca guiada</p>
            <h3 className="mt-1 text-lg font-semibold text-slate-950">
              {prescricaoEntradaModo === "manipulado"
                ? "Selecionar base para formula manipulada"
                : prescricaoEntradaModo === "industrializado"
                  ? "Selecionar produto industrializado"
                  : "Buscar medicamento ou iniciar um item manual"}
            </h3>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => adicionarItemPrescricaoEmBranco()}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
            >
              <Plus className="h-4 w-4" />
              Item manual
            </button>
            <button
              type="button"
              onClick={() => setPrescricaoEntradaModo(null)}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100"
            >
              <X className="h-4 w-4" />
              Fechar busca
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr),280px]">
          <div>
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={prescricaoBuscaRapida}
                onChange={(e) => setPrescricaoBuscaRapida(e.target.value)}
                placeholder="Buscar medicamento, principio ativo, classe ou categoria..."
                className="w-full rounded-[22px] border border-slate-200 bg-slate-50 py-3 pl-11 pr-4 text-sm text-slate-900 placeholder:text-slate-400 transition focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-4 focus:ring-teal-100"
              />
            </div>

            <div className="mt-4 max-h-[420px] space-y-3 overflow-auto pr-1">
              {mostrarResultadosBuscaPrescricao ? (
                prescricaoBuscaResultados.length > 0 ? (
                  prescricaoBuscaResultados.map((med: any) => (
                    <div key={med.id} className="rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-4">
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div className="min-w-0">
                          <p className="text-base font-semibold text-slate-950">{med.nome}</p>
                          <p className="mt-1 text-sm text-slate-600">
                            {med.classe_terapeutica || med.categoria || "Sem classificacao"}
                            {med.principio_ativo ? ` · ${med.principio_ativo}` : ""}
                          </p>
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                            {med.forma_farmaceutica ? (
                              <span className="rounded-full bg-white px-2.5 py-1">{med.forma_farmaceutica}</span>
                            ) : null}
                            {med.especie_alvo ? (
                              <span className="rounded-full bg-white px-2.5 py-1">{med.especie_alvo}</span>
                            ) : null}
                            {med.parametrizado ? (
                              <span className="rounded-full bg-teal-100 px-2.5 py-1 text-teal-700">Parametrizado</span>
                            ) : null}
                          </div>
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => abrirMedicamentoBuscaRapida(med)}
                            className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
                          >
                            <Eye className="h-4 w-4" />
                            Ver cadastro
                          </button>
                          <button
                            type="button"
                            onClick={() => selecionarMedicamentoBuscaRapida(med, prescricaoEntradaModo === "manipulado")}
                            className="inline-flex items-center gap-2 rounded-2xl bg-teal-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-teal-700"
                          >
                            <Plus className="h-4 w-4" />
                            {prescricaoEntradaModo === "manipulado" ? "Usar como formula" : "Selecionar"}
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-[24px] border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                    Nenhum medicamento encontrado para esta busca.
                  </div>
                )
              ) : (
                <div className="rounded-[24px] border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                  Escolha um tipo de entrada acima para abrir a busca sem poluir a tela inicial da receita.
                </div>
              )}
            </div>
          </div>

          <div className="rounded-[26px] border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Atalhos do fluxo</p>
            <div className="mt-4 space-y-3 text-sm text-slate-600">
              <p>1. Escolha o tipo do item.</p>
              <p>2. Busque o medicamento ou abra um item manual.</p>
              <p>3. Defina apresentacao, dose, frequencia e via.</p>
              <p>4. Revise as sugestoes e gere o PDF.</p>
            </div>
            {prescricaoEntradaModo === "manipulado" ? (
              <button
                type="button"
                onClick={() => adicionarItemPrescricaoEmBranco({ manipulado: true })}
                className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-amber-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-amber-600"
              >
                <Plus className="h-4 w-4" />
                Nova formula em branco
              </button>
            ) : null}
          </div>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr),minmax(300px,0.95fr)]">
        <section className="rounded-[30px] border border-slate-200 bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Instrucoes gerais do tratamento</p>
          <textarea
            value={form.prescricao_orientacoes}
            onChange={(e) => setField("prescricao_orientacoes", e.target.value)}
            placeholder="Resumo para o tutor, cuidados, horarios, retornos e observacoes gerais."
            rows={5}
            className="mt-4 w-full rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900 placeholder:text-slate-400 transition focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-4 focus:ring-teal-100"
          />
        </section>

        <section className="rounded-[30px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Contexto da prescricao</p>
              <p className="mt-1 text-sm text-slate-600">Data base, retorno e protocolos rapidos para acelerar a emissao.</p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {form.data_atendimento ? formatDate(form.data_atendimento) : formatDate(new Date().toISOString())}
            </span>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Retorno (dias)</p>
              <input
                type="number"
                value={form.prescricao_retorno_dias}
                onChange={(e) => setField("prescricao_retorno_dias", e.target.value)}
                placeholder="Ex.: 7"
                className="mt-2 w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 transition focus:border-teal-400 focus:outline-none focus:ring-4 focus:ring-teal-100"
              />
            </div>
            <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Protocolo recomendado</p>
              <p className="mt-2 text-sm font-semibold text-slate-900">{protocoloPrescricaoRecomendado?.label || "Nenhum protocolo automatico"}</p>
              <p className="mt-1 text-xs text-slate-500">
                {protocoloPrescricaoSelecionadoDetalhe?.descricao || "Voce pode aplicar um protocolo rapido abaixo."}
              </p>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {PROTOCOLOS_PRESCRICAO.map((protocolo: any) => (
              <button
                key={protocolo.key}
                type="button"
                onClick={() => selecionarProtocoloPrescricao(protocolo.key)}
                className={`rounded-2xl px-3 py-2 text-xs font-medium transition ${
                  protocoloPrescricaoSelecionado === protocolo.key
                    ? "bg-teal-600 text-white"
                    : protocoloPrescricaoRecomendado?.key === protocolo.key
                      ? "bg-teal-100 text-teal-800"
                      : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                }`}
              >
                {protocolo.label}
              </button>
            ))}
          </div>

          {protocoloPrescricaoSelecionadoDetalhe ? (
            <div className="mt-4 rounded-[22px] border border-teal-200 bg-teal-50/60 px-4 py-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.2em] text-teal-700">Previa do protocolo</p>
                  <p className="mt-1 text-sm font-semibold text-slate-900">{protocoloPrescricaoSelecionadoDetalhe.label}</p>
                  <p className="mt-1 text-xs text-slate-600">
                    {protocoloPrescricaoSelecionadoGatilho ? (
                      <>
                        Gatilho identificado no diagnostico: <span className="font-medium text-teal-700">&quot;{protocoloPrescricaoSelecionadoGatilho}&quot;</span>
                      </>
                    ) : (
                      "Selecionado manualmente - nenhum gatilho do diagnostico atual casou com este protocolo."
                    )}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={descartarProtocoloSelecionado}
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Descartar
                  </button>
                  <button
                    type="button"
                    onClick={aplicarProtocoloSelecionado}
                    className="rounded-xl bg-teal-600 px-3 py-2 text-xs font-medium text-white hover:bg-teal-700"
                  >
                    Aplicar protocolo
                  </button>
                </div>
              </div>

              {protocoloPrescricaoSelecionadoItensPreview.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {protocoloPrescricaoSelecionadoItensPreview.map((item: any, index: number) => (
                    <div key={index} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700">
                      <p className="font-semibold text-slate-900">{item.medicamento_nome}</p>
                      <p className="mt-0.5 text-slate-600">
                        {[item.dose, item.frequencia, item.duracao, item.via].filter(Boolean).join(" - ")}
                      </p>
                      {item.instrucoes ? <p className="mt-0.5 text-slate-500">{item.instrucoes}</p> : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-xs text-slate-500">Este protocolo nao inclui itens de receita - apenas orientacoes e retorno.</p>
              )}

              {protocoloPrescricaoSelecionadoDetalhe.orientacoesPadrao ? (
                <div className="mt-3 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400">Orientacoes a inserir</p>
                  <p className="mt-1 whitespace-pre-line">{protocoloPrescricaoSelecionadoDetalhe.orientacoesPadrao}</p>
                </div>
              ) : null}

              {protocoloPrescricaoSelecionadoDetalhe.retornoDias ? (
                <p className="mt-3 text-xs text-slate-500">
                  Retorno sugerido: {protocoloPrescricaoSelecionadoDetalhe.retornoDias} dia(s)
                  {form.prescricao_retorno_dias ? " (mantido o valor ja preenchido)." : "."}
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="mt-4 rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Seus presets de prescricao</p>
                <p className="mt-1 text-sm text-slate-600">
                  Salve prescricoes recorrentes completas para reaplicar com os itens e orientacoes.
                </p>
                {presetPrescricaoEmEdicaoId ? (
                  <p className="mt-1 text-xs font-medium text-sky-700">Editando preset selecionado</p>
                ) : null}
              </div>
              <div className="flex w-full flex-col gap-2 lg:w-auto lg:min-w-[320px] lg:flex-row">
                <input
                  value={nomeNovoPresetPrescricao}
                  onChange={(e) => setNomeNovoPresetPrescricao(e.target.value)}
                  placeholder="Nome do preset"
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900"
                />
                <button
                  type="button"
                  onClick={salvarPresetPrescricaoAtual}
                  className="rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
                >
                  {presetPrescricaoEmEdicaoId ? "Atualizar preset" : "Salvar preset"}
                </button>
                {presetPrescricaoEmEdicaoId ? (
                  <button
                    type="button"
                    onClick={cancelarEdicaoPresetPrescricao}
                    className="rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
                  >
                    Cancelar
                  </button>
                ) : null}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {prescriptionPresets.length > 0 ? (
                prescriptionPresets.map((preset: any) => (
                  <div key={preset.id} className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2">
                    <button
                      type="button"
                      onClick={() => aplicarPresetPrescricao(preset)}
                      className="text-sm font-medium text-slate-800"
                    >
                      {preset.nome}
                    </button>
                    <span className="text-xs text-slate-500">{preset.itens.length} item(ns)</span>
                    <button
                      type="button"
                      onClick={() => editarPresetPrescricao(preset)}
                      className="rounded-full bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-600 transition hover:bg-sky-50 hover:text-sky-700"
                    >
                      Editar
                    </button>
                    <button
                      type="button"
                      onClick={() => removerPresetPrescricao(preset.id)}
                      className="rounded-full bg-slate-50 p-1 text-slate-500 transition hover:bg-rose-50 hover:text-rose-600"
                      aria-label={`Remover preset ${preset.nome}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">Nenhum preset salvo ainda.</p>
              )}
            </div>
          </div>
        </section>
      </div>

      {prescricaoSupport.alertasGerais.length > 0 ? (
        <section className="rounded-[30px] border border-amber-200 bg-amber-50 px-5 py-5 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl bg-amber-100 p-3">
              <AlertTriangle className="h-5 w-5 text-amber-700" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Alertas de interacao</p>
              <h3 className="mt-1 text-lg font-semibold text-amber-950">Revise antes de fechar o receituario</h3>
            </div>
          </div>
          <div className="mt-4 grid gap-2">
            {prescricaoSupport.alertasGerais.map((alerta: string) => (
              <p
                key={alerta}
                className={`rounded-2xl border px-4 py-3 text-sm ${getAlertaPrescricaoClass(classificarAlertaPrescricao(alerta))}`}
              >
                {alerta}
              </p>
            ))}
          </div>
        </section>
      ) : null}

      <section id="prescricao-itens" className="space-y-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Itens da receita</p>
            <h3 className="mt-1 text-lg font-semibold text-slate-950">Configure cada medicamento com mais contexto visual</h3>
          </div>
          <button
            type="button"
            onClick={() => adicionarItemPrescricaoEmBranco()}
            className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
          >
            <Plus className="h-4 w-4" />
            Adicionar item manual
          </button>
        </div>

        {prescricaoTemRascunhoInicial ? (
          <div className="rounded-[30px] border border-dashed border-slate-300 bg-white px-6 py-12 text-center shadow-sm">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-3xl bg-teal-100 text-teal-700">
              <ClipboardPlus className="h-6 w-6" />
            </div>
            <h4 className="mt-4 text-xl font-semibold text-slate-950">A receita ainda esta vazia</h4>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Comece pelos cards de entrada rapida acima ou crie um item manual para preencher do seu jeito.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <button
                type="button"
                onClick={() => setPrescricaoEntradaModo("industrializado")}
                className="inline-flex items-center gap-2 rounded-2xl bg-teal-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-teal-700"
              >
                <Search className="h-4 w-4" />
                Buscar industrializado
              </button>
              <button
                type="button"
                onClick={() => adicionarItemPrescricaoEmBranco({ manipulado: true })}
                className="inline-flex items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-800 transition hover:bg-amber-100"
              >
                <Pill className="h-4 w-4" />
                Criar formula manipulada
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {form.prescricao_itens.map((item: any, idx: number) => renderPrescricaoItemCard(item, idx))}
          </div>
        )}
      </section>
    </section>
  );
}
