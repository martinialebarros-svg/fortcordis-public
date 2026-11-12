"use client";

import {
  ChevronDown,
  ChevronRight,
  ClipboardPlus,
  Pill,
  Plus,
  RefreshCw,
  Save,
  Search,
} from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoBibliotecasSectionProps = LooseAtendimentoComponentProps;

export default function AtendimentoBibliotecasSection(props: AtendimentoBibliotecasSectionProps) {
  const {
    CLINICAL_SECTION_OPTIONS,
    adicionarMedicamentoNaPrescricao,
    carregarMaisFrasesClinicas,
    carregarMaisMedicamentosBanco,
    carregarFrasesClinicas,
    carregarMedicamentosBanco,
    clinicalPhraseForm,
    clinicalPhraseSearch,
    clinicalPhraseSectionFilter,
    clinicalPhrases,
    clinicalPhrasesFiltered,
    clinicalSectionLabels,
    desativarMedicamento,
    duplicarMedicamentoManipulado,
    editarFraseClinica,
    editarMedicamento,
    formatarOrigemMedicamento,
    medBusca,
    medFiltrados,
    medForm,
    medicamentos,
    resetClinicalPhraseForm,
    resetMedicationForm,
    saveClinicalPhrase,
    saveMedicamento,
    savingClinicalPhrase,
    setClinicalPhraseForm,
    setClinicalPhraseSearch,
    setClinicalPhraseSectionFilter,
    setMedBusca,
    setMedForm,
    setShowMedicationBank,
    setShowPhraseBank,
    showMedicationBank,
    showPhraseBank,
    toggleClinicalPhrase,
    totalClinicalPhrases,
    totalMedicamentos,
  } = props;

  return (
    <div className="w-full min-w-0 space-y-6">
      <div className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <button
            type="button"
            onClick={() => setShowPhraseBank((prev: boolean) => !prev)}
            className="flex min-w-0 items-center gap-3 text-left"
          >
            <div className="rounded-2xl bg-teal-50 p-3">
              <ClipboardPlus className="h-4 w-4 text-teal-600" />
            </div>
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Banco configuravel</p>
              <h2 className="text-lg font-semibold text-slate-900">Frases clinicas do atendimento</h2>
            </div>
            {showPhraseBank ? (
              <ChevronDown className="h-4 w-4 text-slate-500" />
            ) : (
              <ChevronRight className="h-4 w-4 text-slate-500" />
            )}
          </button>
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <button
              onClick={() => void carregarFrasesClinicas()}
              className="rounded-2xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
            >
              <span className="inline-flex items-center gap-2">
                <RefreshCw className="h-4 w-4" />
                Atualizar banco
              </span>
            </button>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {clinicalPhrases.length}{totalClinicalPhrases > clinicalPhrases.length ? ` de ${totalClinicalPhrases}` : ""} frase(s)
            </span>
          </div>
        </div>

        {showPhraseBank ? (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
            <div className="space-y-3 rounded-[22px] border border-slate-200 bg-slate-50 p-4">
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-1">
                <div>
                  <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Secao</label>
                  <select
                    value={clinicalPhraseForm.secao}
                    onChange={(e) =>
                      setClinicalPhraseForm((prev: AtendimentoBibliotecasSectionProps) => ({
                        ...prev,
                        secao: e.target.value,
                      }))
                    }
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
                  >
                    {CLINICAL_SECTION_OPTIONS.map((item: AtendimentoBibliotecasSectionProps) => (
                      <option key={item.key} value={item.key}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Ordem</label>
                  <input
                    value={clinicalPhraseForm.ordem}
                    onChange={(e) =>
                      setClinicalPhraseForm((prev: AtendimentoBibliotecasSectionProps) => ({
                        ...prev,
                        ordem: e.target.value,
                      }))
                    }
                    placeholder="10"
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
                  />
                </div>
              </div>

              <div>
                <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Titulo</label>
                <input
                  value={clinicalPhraseForm.titulo}
                  onChange={(e) =>
                    setClinicalPhraseForm((prev: AtendimentoBibliotecasSectionProps) => ({
                      ...prev,
                      titulo: e.target.value,
                    }))
                  }
                  placeholder="Ex.: Endocardiose mitral B1"
                  className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
                />
              </div>

              <div>
                <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Texto</label>
                <textarea
                  value={clinicalPhraseForm.texto}
                  onChange={(e) =>
                    setClinicalPhraseForm((prev: AtendimentoBibliotecasSectionProps) => ({
                      ...prev,
                      texto: e.target.value,
                    }))
                  }
                  rows={7}
                  placeholder="Texto da frase clinica."
                  className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
                />
              </div>

              <label className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={clinicalPhraseForm.ativo === 1}
                  onChange={(e) =>
                    setClinicalPhraseForm((prev: AtendimentoBibliotecasSectionProps) => ({
                      ...prev,
                      ativo: e.target.checked ? 1 : 0,
                    }))
                  }
                  className="h-4 w-4"
                />
                Frase ativa
              </label>

              <p className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
                As frases cadastradas aqui alimentam os atalhos do editor clinico por secao.
              </p>

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={saveClinicalPhrase}
                  disabled={savingClinicalPhrase}
                  className="rounded-2xl bg-teal-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-teal-700 disabled:opacity-50"
                >
                  <span className="inline-flex items-center gap-2">
                    <Save className="h-4 w-4" />
                    {savingClinicalPhrase ? "Salvando..." : clinicalPhraseForm.id ? "Atualizar frase" : "Salvar frase"}
                  </span>
                </button>
                <button
                  onClick={resetClinicalPhraseForm}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
                >
                  <span className="inline-flex items-center gap-2">
                    <Plus className="h-4 w-4" />
                    Nova frase
                  </span>
                </button>
              </div>
            </div>

            <div className="xl:col-span-2 rounded-[22px] border border-slate-200 bg-white">
              <div className="grid gap-3 border-b border-slate-200 p-4 md:grid-cols-[minmax(0,1fr),240px]">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    value={clinicalPhraseSearch}
                    onChange={(e) => setClinicalPhraseSearch(e.target.value)}
                    placeholder="Buscar frase clinica..."
                    className="w-full rounded-2xl border border-slate-200 bg-slate-50 py-3 pl-11 pr-3 text-sm text-slate-900"
                  />
                </div>
                <select
                  value={clinicalPhraseSectionFilter}
                  onChange={(e) => setClinicalPhraseSectionFilter(e.target.value || "")}
                  className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                >
                  <option value="">Todas as secoes</option>
                  {CLINICAL_SECTION_OPTIONS.map((item: AtendimentoBibliotecasSectionProps) => (
                    <option key={item.key} value={item.key}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="max-h-[420px] overflow-auto p-4">
                <div className="space-y-3">
                  {clinicalPhrasesFiltered.map((item: AtendimentoBibliotecasSectionProps) => (
                    <div
                      key={item.id}
                      className={`rounded-[22px] border px-4 py-4 ${
                        Number(item.ativo ?? 1) === 1
                          ? "border-slate-200 bg-slate-50"
                          : "border-slate-200 bg-slate-100/70 opacity-80"
                      }`}
                    >
                      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-semibold text-slate-900">{item.titulo}</p>
                            <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600">
                              {clinicalSectionLabels[item.secao] || item.secao}
                            </span>
                            <span
                              className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                                Number(item.ativo ?? 1) === 1
                                  ? "bg-emerald-100 text-emerald-700"
                                  : "bg-slate-200 text-slate-600"
                              }`}
                            >
                              {Number(item.ativo ?? 1) === 1 ? "Ativa" : "Inativa"}
                            </span>
                            <span className="rounded-full bg-sky-100 px-2.5 py-1 text-[11px] font-medium text-sky-700">
                              {item.parametrizacao_origem || "manual"}
                            </span>
                          </div>
                          <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{item.texto}</p>
                        </div>

                        <div className="flex shrink-0 flex-wrap gap-2">
                          <button
                            onClick={() => editarFraseClinica(item)}
                            className="rounded-xl bg-sky-100 px-3 py-2 text-xs font-medium text-sky-700 transition hover:bg-sky-200"
                          >
                            Editar
                          </button>
                          <button
                            onClick={() => void toggleClinicalPhrase(item)}
                            className={`rounded-xl px-3 py-2 text-xs font-medium transition ${
                              Number(item.ativo ?? 1) === 1
                                ? "bg-red-100 text-red-700 hover:bg-red-200"
                                : "bg-emerald-100 text-emerald-700 hover:bg-emerald-200"
                            }`}
                          >
                            {Number(item.ativo ?? 1) === 1 ? "Desativar" : "Reativar"}
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}

                  {clinicalPhrasesFiltered.length === 0 ? (
                    <div className="rounded-[22px] border border-dashed border-slate-200 px-4 py-10 text-center text-sm text-slate-500">
                      Nenhuma frase clinica encontrada para os filtros atuais.
                    </div>
                  ) : null}
                  {clinicalPhrases.length < totalClinicalPhrases ? (
                    <button
                      type="button"
                      onClick={() => void carregarMaisFrasesClinicas()}
                      className="mt-3 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
                    >
                      Carregar mais frases
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-[22px] border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            Abra este painel para cadastrar, editar e ativar frases do editor clinico.
          </div>
        )}
      </div>

      <div className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm space-y-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <button
            type="button"
            onClick={() => setShowMedicationBank((prev: boolean) => !prev)}
            className="flex min-w-0 items-center gap-3 text-left"
          >
            <div className="rounded-2xl bg-teal-50 p-3">
              <Pill className="w-4 h-4 text-teal-600" />
            </div>
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Banco configuravel</p>
              <h2 className="font-semibold text-gray-900">Banco de medicamentos</h2>
            </div>
            {showMedicationBank ? (
              <ChevronDown className="h-4 w-4 text-slate-500" />
            ) : (
              <ChevronRight className="h-4 w-4 text-slate-500" />
            )}
          </button>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
            {medicamentos.length}{totalMedicamentos > medicamentos.length ? ` de ${totalMedicamentos}` : ""} medicamento(s)
          </span>
        </div>

        {showMedicationBank ? (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
            <div className="space-y-3 rounded-[22px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-500">
                    {medForm.id ? "Editando medicamento" : "Novo medicamento"}
                  </p>
                  <p className="mt-1 text-sm text-slate-600">
                    Os campos importados do HTML ficam explicitos aqui e podem ser editados antes da prescricao.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-white px-3 py-1 text-[11px] font-medium text-slate-600">
                    {formatarOrigemMedicamento(medForm.parametrizacao_origem)}
                  </span>
                  <button
                    type="button"
                    onClick={resetMedicationForm}
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
                  >
                    Novo
                  </button>
                </div>
              </div>

              {medForm.parametrizacao_origem === "vetsmart_html" ? (
                <p className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-xs text-sky-800">
                  Este registro veio de HTML salvo da Vetsmart. Apresentacoes, indicacoes, interacoes e frequencia podem
                  ser ajustadas manualmente aqui.
                </p>
              ) : (
                <p className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs text-emerald-800">
                  Use esta ficha para cadastrar um medicamento proprio, ou criar uma versao reutilizavel de formula
                  manipulada.
                </p>
              )}

              <input
                value={medForm.nome}
                onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, nome: e.target.value }))}
                placeholder="Nome do medicamento"
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
              />
              <input
                value={medForm.principio_ativo}
                onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, principio_ativo: e.target.value }))}
                placeholder="Principio ativo"
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
              />

              <div>
                <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Apresentacoes / concentracao</label>
                <textarea
                  value={medForm.concentracao}
                  onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, concentracao: e.target.value }))}
                  placeholder="Uma apresentacao por linha. Ex.: Pimobendan 5 mg, capsula"
                  rows={3}
                  className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
                />
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                <input value={medForm.forma_farmaceutica} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, forma_farmaceutica: e.target.value }))} placeholder="Forma farmaceutica" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.classe_terapeutica} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, classe_terapeutica: e.target.value }))} placeholder="Classe terapeutica" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.especie_alvo} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, especie_alvo: e.target.value }))} placeholder="Especie alvo" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.categoria} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, categoria: e.target.value }))} placeholder="Categoria" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.dose_min_mg_kg} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, dose_min_mg_kg: e.target.value }))} placeholder="Dose min (mg/kg)" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.dose_max_mg_kg} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, dose_max_mg_kg: e.target.value }))} placeholder="Dose max (mg/kg)" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.dose_intervalo_horas} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, dose_intervalo_horas: e.target.value }))} placeholder="Intervalo/frequencia (h)" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.via_padrao} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, via_padrao: e.target.value }))} placeholder="Via padrao" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.duracao_padrao} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, duracao_padrao: e.target.value }))} placeholder="Duracao padrao (opcional)" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.concentracao_mg_ml} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, concentracao_mg_ml: e.target.value }))} placeholder="Concentracao mg/mL" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
                <input value={medForm.concentracao_mg_comprimido} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, concentracao_mg_comprimido: e.target.value }))} placeholder="Concentracao mg/comprimido" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
              </div>

              <div>
                <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Indicacoes</label>
                <textarea value={medForm.indicacoes} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, indicacoes: e.target.value }))} placeholder="Indicacoes clinicas importadas ou manuais" rows={3} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
              </div>
              <div>
                <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Contraindicacoes</label>
                <textarea value={medForm.contraindicacoes} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, contraindicacoes: e.target.value }))} placeholder="Contraindicacoes e precaucoes" rows={3} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
              </div>
              <div>
                <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Interacoes medicamentosas</label>
                <textarea value={medForm.interacoes} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, interacoes: e.target.value }))} placeholder="Uma interacao por linha" rows={4} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
              </div>
              <div>
                <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Observacao de seguranca</label>
                <textarea value={medForm.observacao_seguranca} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, observacao_seguranca: e.target.value }))} placeholder="Alertas, cuidados e avisos" rows={3} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
              </div>
              <div>
                <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-slate-500">Observacoes tecnicas</label>
                <textarea value={medForm.observacoes} onChange={(e) => setMedForm((p: AtendimentoBibliotecasSectionProps) => ({ ...p, observacoes: e.target.value }))} placeholder="Fonte, monitoramento, receita e notas adicionais" rows={5} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" />
              </div>

              <p className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
                Parametrize dose, interacoes e regras clinicas antes de automatizar receituarios em producao.
              </p>

              <div className="flex flex-wrap gap-2">
                <button onClick={saveMedicamento} className="rounded-2xl bg-teal-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-teal-700">
                  <span className="inline-flex items-center gap-2">
                    <Save className="w-4 h-4" />
                    {medForm.id ? "Atualizar medicamento" : "Salvar medicamento"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={resetMedicationForm}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
                >
                  Limpar ficha
                </button>
              </div>
            </div>

            <div className="xl:col-span-2 overflow-hidden rounded-[22px] border border-slate-200 bg-white">
              <div className="grid gap-3 border-b border-slate-200 p-3 md:grid-cols-[minmax(0,1fr),auto]">
                <input value={medBusca} onChange={(e) => setMedBusca(e.target.value)} placeholder="Buscar medicamento..." className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900" />
                <button
                  type="button"
                  onClick={() => void carregarMedicamentosBanco()}
                  className="rounded-2xl bg-slate-100 px-4 py-3 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
                >
                  Atualizar lista
                </button>
              </div>
              <div className="max-h-[520px] overflow-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="px-3 py-3 text-left">Nome</th>
                      <th className="px-3 py-3 text-left">Classe / origem</th>
                      <th className="px-3 py-3 text-left">Dose base</th>
                      <th className="px-3 py-3 text-right">Acoes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {medFiltrados.map((med: AtendimentoBibliotecasSectionProps) => (
                      <tr
                        key={med.id}
                        onClick={() => editarMedicamento(med)}
                        className={`border-t transition ${medForm.id === med.id ? "bg-teal-50" : "cursor-pointer hover:bg-slate-50"}`}
                      >
                        <td className="px-3 py-3">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              editarMedicamento(med);
                            }}
                            className="text-left"
                          >
                            <p className="font-medium text-slate-900">{med.nome}</p>
                            <p className="text-xs text-slate-500">{med.principio_ativo || "-"}</p>
                          </button>
                        </td>
                        <td className="px-3 py-3">
                          <p className="text-slate-800">{med.classe_terapeutica || med.categoria || "-"}</p>
                          <div className="mt-1 flex flex-wrap gap-1">
                            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                              {formatarOrigemMedicamento(med.parametrizacao_origem)}
                            </span>
                            {med.parametrizado ? (
                              <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
                                Parametrizado
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <p className="text-slate-800">
                            {med.dose_min_mg_kg || med.dose_max_mg_kg
                              ? `${med.dose_min_mg_kg ?? med.dose_max_mg_kg} a ${med.dose_max_mg_kg ?? med.dose_min_mg_kg} ${med.dose_unidade || "mg/kg"}`
                              : "Nao parametrizada"}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            {med.dose_intervalo_horas ? `a cada ${med.dose_intervalo_horas}h` : "Frequencia em aberto"}
                          </p>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex flex-wrap justify-end gap-2">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                editarMedicamento(med);
                              }}
                              className="rounded-xl bg-sky-100 px-3 py-2 text-xs font-medium text-sky-700 transition hover:bg-sky-200"
                            >
                              Editar
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                duplicarMedicamentoManipulado(med);
                              }}
                              className="rounded-xl bg-violet-100 px-3 py-2 text-xs font-medium text-violet-700 transition hover:bg-violet-200"
                            >
                              Duplicar formula
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                adicionarMedicamentoNaPrescricao(med);
                              }}
                              className="rounded-xl bg-teal-100 px-3 py-2 text-xs font-medium text-teal-700 transition hover:bg-teal-200"
                            >
                              Prescrever
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                adicionarMedicamentoNaPrescricao(med, { manipulado: true });
                              }}
                              className="rounded-xl bg-amber-100 px-3 py-2 text-xs font-medium text-amber-700 transition hover:bg-amber-200"
                            >
                              Presc. formula
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                void desativarMedicamento(med);
                              }}
                              className="rounded-xl bg-rose-100 px-3 py-2 text-xs font-medium text-rose-700 transition hover:bg-rose-200"
                            >
                              Desativar
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {medFiltrados.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-4 py-10 text-center text-sm text-slate-500">
                          Nenhum medicamento encontrado para a busca atual.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
              {medicamentos.length < totalMedicamentos ? (
                <div className="border-t border-slate-200 p-3">
                  <button
                    type="button"
                    onClick={() => void carregarMaisMedicamentosBanco()}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
                  >
                    Carregar mais medicamentos
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="rounded-[22px] border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            Abra este painel quando precisar parametrizar a biblioteca farmacologica.
          </div>
        )}
      </div>
    </div>
  );
}
