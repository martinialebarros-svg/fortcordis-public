"use client";

import { Fragment, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  FileText,
  FileUp,
  ImageIcon,
  Loader2,
  Paperclip,
  Plus,
  Printer,
  Search,
  ShieldCheck,
  ShieldOff,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import PainelExamesModal from "./PainelExamesModal";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoExamesSectionProps = LooseAtendimentoComponentProps;

export default function AtendimentoExamesSection(props: AtendimentoExamesSectionProps) {
  const {
    adicionarExameDoCatalogo,
    aplicarPainel,
    aplicarPainelExames,
    ATENDIMENTO_ATTACHMENT_ACCEPT,
    atualizarExame,
    baixarPdfAtendimento,
    cancelarUploadAnexo,
    catalogoExames,
    clearExamDropState,
    clearExamUploadDraft,
    colapsarTodosExames,
    customPaineis,
    editarPainelExame,
    emptyExam,
    exameBusca,
    exameFiltroRapido,
    examDropActive,
    examUploadDrafts,
    examesCatalogoFiltrados,
    examesExpandidos,
    examesVisiveis,
    excluirAnexo,
    excluirCatalogoExameCustomizado,
    excluirPainelExame,
    expandirTodosExames,
    EXAME_FILTRO_OPCOES,
    EXAME_STATUS_META,
    form,
    formatBytes,
    formatDate,
    gerandoPdfTipo,
    getExameStateKey,
    goLaudo,
    hasExamRequest,
    imprimirSolicitacaoExames,
    openingAttachmentId,
    painelEmEdicao,
    painelExameAtual,
    painelExameSelecionado,
    painelFormCategoria,
    painelFormErro,
    painelFormItens,
    painelFormNome,
    painelFormSearch,
    painelModalMode,
    painelModalOpen,
    paineisExames,
    removerExame,
    removerExamesVazios,
    alternarLiberacaoExameNoPortal,
    portalExameAcaoId,
    exameTemPdfAnexado,
    isExamePortalLiberado,
    resolvePreviewKind,
    resumoExamesFluxo,
    salvando,
    salvarCatalogoExameCustomizado,
    salvarPainelExame,
    selecionado,
    setExamDropActive,
    setExamUploadDraftFile,
    setExameFiltroRapido,
    setExameBusca,
    setExamesExpandidos,
    setField,
    setPainelEmEdicao,
    setPainelExameSelecionado,
    setPainelFormCategoria,
    setPainelFormErro,
    setPainelFormItens,
    setPainelFormNome,
    setPainelFormSearch,
    setPainelModalMode,
    setPainelModalOpen,
    abrirAnexo,
    uploadArquivoResultadoExame,
    uploadArquivosResultadoExame,
    uploadingAttachmentKey,
    uploadProgressByKey,
  } = props;

  const [exameBuscaFoco, setExameBuscaFoco] = useState(false);

  const gruposExamesVisiveis = useMemo(() => {
    const grupos: { categoria: string; itens: AtendimentoExamesSectionProps[] }[] = [];
    const indicePorCategoria = new Map<string, number>();
    (examesVisiveis as AtendimentoExamesSectionProps[]).forEach((item) => {
      const categoria = (item.exame?.categoria_exame || "").trim() || "Sem categoria";
      let idx = indicePorCategoria.get(categoria);
      if (idx === undefined) {
        idx = grupos.length;
        indicePorCategoria.set(categoria, idx);
        grupos.push({ categoria, itens: [] });
      }
      grupos[idx].itens.push(item);
    });
    return grupos;
  }, [examesVisiveis]);

  return (
    <section className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm space-y-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <h2 className="font-semibold text-gray-900 flex items-center gap-2">
          <FileText className="w-4 h-4 text-blue-600" />
          Solicitacao de exames
        </h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={imprimirSolicitacaoExames}
            className="text-sm px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-700 flex items-center gap-1"
          >
            <Printer className="w-4 h-4" />
            Imprimir
          </button>
          <button
            type="button"
            onClick={() => baixarPdfAtendimento("exames")}
            disabled={!hasExamRequest || salvando || Boolean(gerandoPdfTipo)}
            className="text-sm px-3 py-1.5 rounded-lg bg-blue-100 hover:bg-blue-200 text-blue-700 disabled:cursor-not-allowed disabled:opacity-50 flex items-center gap-1"
          >
            <Download className="w-4 h-4" />
            {gerandoPdfTipo === "exames" ? "Gerando..." : "Gerar PDF"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Solicitados</p>
          <p className="mt-1 text-lg font-semibold text-slate-900">{resumoExamesFluxo.solicitados}</p>
        </div>
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-[0.2em] text-amber-700">Sem arquivo</p>
          <p className="mt-1 text-lg font-semibold text-amber-900">{resumoExamesFluxo.aguardando_arquivo}</p>
        </div>
        <div className="rounded-2xl border border-sky-200 bg-sky-50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-[0.2em] text-sky-700">Com arquivo</p>
          <p className="mt-1 text-lg font-semibold text-sky-900">{resumoExamesFluxo.arquivo_anexado}</p>
        </div>
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-[0.2em] text-emerald-700">Interpretados</p>
          <p className="mt-1 text-lg font-semibold text-emerald-900">{resumoExamesFluxo.interpretado}</p>
        </div>
        <div className="rounded-2xl border border-violet-200 bg-violet-50 px-3 py-2">
          <p className="text-[11px] uppercase tracking-[0.2em] text-violet-700">No portal</p>
          <p className="mt-1 text-lg font-semibold text-violet-900">{resumoExamesFluxo.liberado_portal}</p>
        </div>
      </div>

      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-2">
          {EXAME_FILTRO_OPCOES.map((filtro: AtendimentoExamesSectionProps) => {
            const ativo = exameFiltroRapido === filtro.key;
            return (
              <button
                key={filtro.key}
                type="button"
                onClick={() => setExameFiltroRapido(filtro.key)}
                className={`rounded-xl px-3 py-1.5 text-xs font-medium transition ${
                  ativo ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                }`}
              >
                {filtro.label}
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={expandirTodosExames}
            className="rounded-xl bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
          >
            Expandir todos
          </button>
          <button
            type="button"
            onClick={colapsarTodosExames}
            className="rounded-xl bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
          >
            Colapsar todos
          </button>
          <button
            type="button"
            onClick={removerExamesVazios}
            className="rounded-xl bg-rose-100 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-200"
          >
            Remover vazios
          </button>
        </div>
      </div>

      <div className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr),260px,auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={exameBusca}
              onChange={(e) => setExameBusca(e.target.value)}
              onFocus={() => setExameBuscaFoco(true)}
              onBlur={() => setExameBuscaFoco(false)}
              placeholder="Buscar exame por nome, categoria ou sinonimo..."
              className="w-full rounded-2xl border border-slate-200 bg-white py-3 pl-11 pr-3 text-sm text-slate-900"
            />
            {(exameBusca.trim() || exameBuscaFoco) && examesCatalogoFiltrados.length > 0 ? (
              <div className="absolute z-10 mt-2 max-h-72 w-full overflow-auto rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
                {!exameBusca.trim() ? (
                  <p className="px-3 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    Sugestoes
                  </p>
                ) : null}
                {examesCatalogoFiltrados.map((item: AtendimentoExamesSectionProps) => (
                  <button
                    key={item.id}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      setExameBuscaFoco(false);
                      adicionarExameDoCatalogo(item);
                    }}
                    className="w-full rounded-2xl px-3 py-3 text-left transition hover:bg-sky-50"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-slate-900">{item.nome}</p>
                        <p className="mt-1 text-xs text-slate-500">
                          {item.categoria}
                          {item.subcategoria ? ` · ${item.subcategoria}` : ""}
                        </p>
                      </div>
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                        Catalogo
                      </span>
                    </div>
                    {item.preparo ? <p className="mt-2 text-xs text-slate-500">Preparo: {item.preparo}</p> : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <select
            value={painelExameSelecionado}
            onChange={(e) => setPainelExameSelecionado(e.target.value)}
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900"
          >
            <option value="">Selecionar painel de exames</option>
            {paineisExames.map((painel: AtendimentoExamesSectionProps) => (
              <option key={painel.id} value={painel.id}>
                {painel.nome}
              </option>
            ))}
          </select>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={aplicarPainelExames}
              disabled={!painelExameAtual}
              className="text-sm px-3 py-2 rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Aplicar painel
            </button>
            <button
              onClick={() => {
                const novoExame = emptyExam();
                setExameFiltroRapido("todos");
                setField("exames", [...form.exames, novoExame]);
                setExamesExpandidos((prev: AtendimentoExamesSectionProps) => ({
                  ...prev,
                  [getExameStateKey(novoExame)]: true,
                }));
              }}
              className="text-sm px-3 py-2 rounded-xl bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 flex items-center gap-1"
            >
              <Plus className="w-4 h-4" />
              Exame manual
            </button>
          </div>
        </div>

        {painelExameAtual ? (
          <div className="mt-3 rounded-[20px] border border-blue-200 bg-blue-50 px-4 py-3">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-sm font-semibold text-blue-900">{painelExameAtual.nome}</p>
                <p className="text-xs text-blue-700">
                  {painelExameAtual.observacoes || `${painelExameAtual.itens.length} exame(s) parametrizados.`}
                </p>
              </div>
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-blue-700">
                {painelExameAtual.itens.length} itens
              </span>
            </div>
          </div>
        ) : null}

        <div className="mt-3 rounded-[20px] border border-slate-200 bg-white px-4 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Seus paineis customizados</p>
              <p className="mt-1 text-sm text-slate-600">Gerencie paineis de exames ou salve a combinacao atual.</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setPainelFormNome("");
                  setPainelFormCategoria("");
                  setPainelFormItens([]);
                  setPainelFormSearch("");
                  setPainelFormErro("");
                  setPainelModalMode("create");
                  setPainelEmEdicao(null);
                  setPainelModalOpen(true);
                }}
                className="rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
              >
                + Novo painel
              </button>
              <button
                type="button"
                onClick={() => {
                  setPainelModalMode("list");
                  setPainelModalOpen(true);
                }}
                className="rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
              >
                Gerenciar
              </button>
            </div>
          </div>
          {customPaineis.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {customPaineis.map((painel: AtendimentoExamesSectionProps) => (
                <div key={painel.id} className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2">
                  <button
                    type="button"
                    onClick={() => aplicarPainel(painel)}
                    className="text-sm font-medium text-slate-800"
                  >
                    {painel.nome}
                  </button>
                  <span className="text-xs text-slate-500">{painel.itens?.length || 0} item(ns)</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">
              Nenhum painel customizado ainda. Clique em &quot;+&quot; Novo painel para criar.
            </p>
          )}
        </div>

        {painelModalOpen ? (
          <PainelExamesModal
            catalogoExames={catalogoExames}
            customPaineis={customPaineis}
            editarPainelExame={editarPainelExame}
            excluirCatalogoExameCustomizado={excluirCatalogoExameCustomizado}
            excluirPainelExame={excluirPainelExame}
            painelEmEdicao={painelEmEdicao}
            painelFormCategoria={painelFormCategoria}
            painelFormErro={painelFormErro}
            painelFormItens={painelFormItens}
            painelFormNome={painelFormNome}
            painelFormSearch={painelFormSearch}
            painelModalMode={painelModalMode}
            salvarCatalogoExameCustomizado={salvarCatalogoExameCustomizado}
            salvarPainelExame={salvarPainelExame}
            setPainelEmEdicao={setPainelEmEdicao}
            setPainelFormCategoria={setPainelFormCategoria}
            setPainelFormErro={setPainelFormErro}
            setPainelFormItens={setPainelFormItens}
            setPainelFormNome={setPainelFormNome}
            setPainelFormSearch={setPainelFormSearch}
            setPainelModalMode={setPainelModalMode}
            setPainelModalOpen={setPainelModalOpen}
          />
        ) : null}
      </div>

      <div className="space-y-3">
        {(() => {
        const renderExameCard = ({ exame, index, anexosResultado, flowStatus }: AtendimentoExamesSectionProps) => {
          const exameKey = getExameStateKey(exame);
          const exameExpandido = examesExpandidos[exameKey] ?? index === 0;
          const exameUploadKey = `exame-${index}`;
          const exameEmUpload = uploadingAttachmentKey === exameUploadKey;
          const exameUploadProgress = uploadProgressByKey[exameUploadKey] ?? null;
          const examDropzoneId = `exame-upload-${index}`;
          const uploadDraft = examUploadDrafts[exameKey] || null;
          const dropAtivo = examDropActive[exameKey] || false;
          const flowMeta = EXAME_STATUS_META[flowStatus];
          const exameLiberadoNoPortal = isExamePortalLiberado(exame);
          const temPdfParaPortal = exameTemPdfAnexado(anexosResultado);
          const portalAcaoEmAndamento = portalExameAcaoId === exame.id;
          return (
            <div key={exameKey} className={`rounded-[22px] border p-4 ${flowMeta.cardClass}`}>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="flex flex-wrap gap-2">
                    {exame.categoria_exame ? (
                      <span className="rounded-full bg-sky-100 px-2.5 py-1 text-[11px] font-medium text-sky-700">
                        {exame.categoria_exame}
                      </span>
                    ) : null}
                    {exame.painel_exame_nome ? (
                      <span className="rounded-full bg-violet-100 px-2.5 py-1 text-[11px] font-medium text-violet-700">
                        {exame.painel_exame_nome}
                      </span>
                    ) : null}
                    {exame.catalogo_exame_id ? (
                      <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
                        Catalogo
                      </span>
                    ) : null}
                    {exame.data_solicitacao ? (
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                        Solicitado em {formatDate(exame.data_solicitacao)}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setExamesExpandidos((prev: AtendimentoExamesSectionProps) => {
                          const atual = prev[exameKey] ?? index === 0;
                          return { ...prev, [exameKey]: !atual };
                        })
                      }
                      className="self-start rounded-xl bg-slate-100 px-3 py-2 text-slate-700 hover:bg-slate-200"
                    >
                      {exameExpandido ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </button>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${flowMeta.chipClass}`}>
                      {flowMeta.label}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        goLaudo({
                          id: selecionado,
                          paciente_id: Number(form.paciente_id || 0),
                          clinica_id: Number(form.clinica_id || 0),
                          agendamento_id: form.agendamento_id ? Number(form.agendamento_id) : null,
                        })
                      }
                      disabled={!form.paciente_id}
                      className="self-start rounded-xl bg-sky-100 px-3 py-2 text-sky-700 hover:bg-sky-200 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span className="inline-flex items-center gap-1">
                        <FileText className="h-4 w-4" />
                        Laudar
                      </span>
                    </button>
                    {exame.id ? (
                      <button
                        type="button"
                        onClick={() =>
                          alternarLiberacaoExameNoPortal(
                            exame,
                            exameLiberadoNoPortal ? "revogar" : "liberar"
                          )
                        }
                        disabled={portalAcaoEmAndamento || (!exameLiberadoNoPortal && !temPdfParaPortal)}
                        title={
                          exameLiberadoNoPortal
                            ? "Revogar o acesso da clinica parceira a este exame"
                            : temPdfParaPortal
                              ? "Liberar este exame no portal da clinica parceira"
                              : "Anexe o PDF do resultado para liberar no portal"
                        }
                        className={`self-start rounded-xl px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                          exameLiberadoNoPortal
                            ? "bg-violet-100 text-violet-700 hover:bg-violet-200"
                            : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                        }`}
                      >
                        <span className="inline-flex items-center gap-1">
                          {portalAcaoEmAndamento ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : exameLiberadoNoPortal ? (
                            <ShieldOff className="h-4 w-4" />
                          ) : (
                            <ShieldCheck className="h-4 w-4" />
                          )}
                          {exameLiberadoNoPortal ? "Revogar portal" : "Liberar no portal"}
                        </span>
                      </button>
                    ) : null}
                    {exameLiberadoNoPortal ? (
                      <span
                        title={
                          exame.visualizado_portal_em
                            ? `Clinica parceira visualizou em ${formatDate(exame.visualizado_portal_em)}`
                            : "A clinica parceira ainda nao abriu este exame."
                        }
                        className={`self-start rounded-full px-2.5 py-1 text-[11px] font-medium ${
                          exame.visualizado_portal_em
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-amber-100 text-amber-700"
                        }`}
                      >
                        {exame.visualizado_portal_em
                          ? `Visto em ${formatDate(exame.visualizado_portal_em)}`
                          : "Ainda nao visto"}
                      </span>
                    ) : null}
                    <div className="ml-1 flex items-center self-start border-l border-slate-200 pl-3">
                      <button
                        type="button"
                        onClick={() => removerExame(index)}
                        title={
                          exame.id
                            ? "Excluir este exame do prontuario"
                            : "Remover este exame da solicitacao"
                        }
                        className="rounded-xl bg-red-100 px-3 py-2 text-red-700 hover:bg-red-200"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>

                {!exameExpandido ? (
                  <div
                    onDragEnter={(event) => {
                      event.preventDefault();
                      setExamDropActive((prev: AtendimentoExamesSectionProps) => ({ ...prev, [exameKey]: true }));
                      setExamesExpandidos((prev: AtendimentoExamesSectionProps) => ({ ...prev, [exameKey]: true }));
                    }}
                    onDragOver={(event) => {
                      event.preventDefault();
                    }}
                    onDragLeave={(event) => {
                      event.preventDefault();
                      if (event.currentTarget.contains(event.relatedTarget as Node)) return;
                      clearExamDropState(exameKey);
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      clearExamDropState(exameKey);
                      setExamesExpandidos((prev: AtendimentoExamesSectionProps) => ({ ...prev, [exameKey]: true }));
                      const files = Array.from(event.dataTransfer.files || []);
                      if (files.length > 1) {
                        void uploadArquivosResultadoExame(index, files);
                      } else if (files[0]) {
                        setExamUploadDraftFile(exameKey, files[0]);
                      }
                    }}
                    className={`rounded-[18px] border px-3 py-2 text-xs transition ${
                      dropAtivo ? "border-blue-300 bg-blue-50 text-blue-700" : "border-slate-200 bg-slate-50 text-slate-600"
                    }`}
                  >
                    {dropAtivo
                      ? "Solte o arquivo aqui para anexar a este exame..."
                      : `${exame.tipo_exame || "Exame sem nome"} · ${anexosResultado.length} arquivo(s) · ${
                          exame.resultado?.trim() ? "com interpretacao" : "sem interpretacao"
                        }`}
                  </div>
                ) : null}

                {exameExpandido ? (
                  <>
                    <div className="grid grid-cols-1 gap-2 lg:grid-cols-5">
                      <input
                        value={exame.tipo_exame}
                        onChange={(e) => atualizarExame(index, { tipo_exame: e.target.value })}
                        placeholder="Tipo de exame"
                        className="lg:col-span-3 px-3 py-2 border rounded-lg text-sm"
                      />
                      <input
                        value={exame.observacoes || ""}
                        onChange={(e) => atualizarExame(index, { observacoes: e.target.value })}
                        placeholder="Observacoes complementares da solicitacao (opcional)"
                        className="lg:col-span-2 px-3 py-2 border rounded-lg text-sm"
                      />
                    </div>

                    <div className="rounded-[16px] border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                      Data da solicitacao registrada automaticamente no atendimento.
                      {exame.data_solicitacao ? ` Solicitado em ${formatDate(exame.data_solicitacao)}.` : ""}
                    </div>

                    <textarea
                      value={exame.resultado || ""}
                      onChange={(e) => atualizarExame(index, { resultado: e.target.value })}
                      rows={3}
                      placeholder="Interpretacao resumida do resultado (opcional)..."
                      className="w-full px-3 py-2 border rounded-lg text-sm"
                    />

                    {exame.preparo ? (
                      <div className="rounded-[18px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                        <span className="font-medium">Preparo sugerido:</span> {exame.preparo}
                      </div>
                    ) : null}

                    <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-4">
                      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <div>
                          <p className="text-sm font-semibold text-slate-900">Arquivos do exame</p>
                          <p className="text-xs text-slate-500">
                            PDF, JPG, JPEG, PNG e WEBP entram no prontuario e na timeline.
                          </p>
                        </div>
                      </div>

                      <div
                        onDragEnter={(event) => {
                          event.preventDefault();
                          setExamDropActive((prev: AtendimentoExamesSectionProps) => ({ ...prev, [exameKey]: true }));
                        }}
                        onDragOver={(event) => {
                          event.preventDefault();
                          setExamDropActive((prev: AtendimentoExamesSectionProps) => ({ ...prev, [exameKey]: true }));
                        }}
                        onDragLeave={(event) => {
                          event.preventDefault();
                          if (event.currentTarget.contains(event.relatedTarget as Node)) return;
                          clearExamDropState(exameKey);
                        }}
                        onDrop={(event) => {
                          event.preventDefault();
                          clearExamDropState(exameKey);
                          const files = Array.from(event.dataTransfer.files || []);
                          if (files.length > 1) {
                            void uploadArquivosResultadoExame(index, files);
                          } else if (files[0]) {
                            setExamUploadDraftFile(exameKey, files[0]);
                          }
                        }}
                        className={`mt-3 rounded-2xl border-2 border-dashed p-4 transition ${
                          dropAtivo ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white"
                        }`}
                      >
                        <input
                          id={examDropzoneId}
                          type="file"
                          multiple
                          accept={ATENDIMENTO_ATTACHMENT_ACCEPT}
                          className="hidden"
                          onChange={(event) => {
                            const files = Array.from(event.target.files || []);
                            if (files.length > 1) {
                              void uploadArquivosResultadoExame(index, files);
                            } else if (files[0]) {
                              setExamUploadDraftFile(exameKey, files[0]);
                            }
                            event.target.value = "";
                          }}
                        />
                        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                          <div>
                            <p className="text-sm font-medium text-slate-900">Arraste e solte o arquivo aqui</p>
                            <p className="text-xs text-slate-500">
                              Aceita envio unico ou em lote. Ao enviar, o exame e o atendimento sao salvos
                              automaticamente se necessario.
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <label
                              htmlFor={examDropzoneId}
                              className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-slate-200 bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
                            >
                              <FileUp className="h-4 w-4" />
                              Selecionar arquivo(s)
                            </label>
                            <button
                              type="button"
                              onClick={async () => {
                                if (!uploadDraft) return;
                                await uploadArquivoResultadoExame(index, uploadDraft.file);
                              }}
                              disabled={!uploadDraft || exameEmUpload || !form.paciente_id}
                              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {exameEmUpload ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                              {exameEmUpload
                                ? typeof exameUploadProgress === "number"
                                  ? `Enviando ${exameUploadProgress}%`
                                  : "Enviando..."
                                : "Enviar agora"}
                            </button>
                            {exameEmUpload ? (
                              <button
                                type="button"
                                onClick={() => cancelarUploadAnexo(exameUploadKey)}
                                className="inline-flex items-center gap-2 rounded-xl bg-red-100 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-200"
                              >
                                <X className="h-4 w-4" />
                                Cancelar upload
                              </button>
                            ) : null}
                          </div>
                        </div>

                        {exameEmUpload ? (
                          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                            <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                              <div
                                className={`h-full rounded-full bg-slate-900 transition-[width] duration-200 ${
                                  typeof exameUploadProgress === "number" ? "" : "animate-pulse"
                                }`}
                                style={{ width: `${typeof exameUploadProgress === "number" ? exameUploadProgress : 35}%` }}
                              />
                            </div>
                            <p className="mt-1 text-xs text-slate-600">
                              {typeof exameUploadProgress === "number"
                                ? `Upload do exame em andamento (${exameUploadProgress}%).`
                                : "Upload do exame em andamento..."}
                            </p>
                          </div>
                        ) : null}

                        {uploadDraft ? (
                          <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                            <div className="flex min-w-0 items-center gap-3">
                              {uploadDraft.kind === "image" && uploadDraft.previewUrl ? (
                                <img
                                  src={uploadDraft.previewUrl}
                                  alt={uploadDraft.file.name}
                                  className="h-12 w-12 rounded-lg border border-slate-200 object-cover"
                                />
                              ) : (
                                <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-slate-200 bg-white">
                                  {uploadDraft.kind === "pdf" ? (
                                    <FileText className="h-5 w-5 text-red-500" />
                                  ) : (
                                    <Paperclip className="h-5 w-5 text-slate-500" />
                                  )}
                                </div>
                              )}
                              <div className="min-w-0">
                                <p className="truncate text-sm font-medium text-slate-900">{uploadDraft.file.name}</p>
                                <p className="text-xs text-slate-500">{formatBytes(uploadDraft.file.size)}</p>
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => clearExamUploadDraft(exameKey)}
                              disabled={exameEmUpload}
                              className="inline-flex items-center gap-1 rounded-xl bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50"
                            >
                              <X className="h-3.5 w-3.5" />
                              Remover
                            </button>
                          </div>
                        ) : (
                          <p className="mt-3 text-xs text-slate-500">Nenhum arquivo selecionado para envio.</p>
                        )}
                      </div>

                      {!form.paciente_id ? (
                        <p className="mt-3 text-xs text-amber-700">
                          Selecione um paciente para habilitar o envio do arquivo.
                        </p>
                      ) : null}

                      {anexosResultado.length > 0 ? (
                        <div className="mt-4 space-y-2">
                          {anexosResultado.map((anexo: AtendimentoExamesSectionProps) => (
                            <div key={anexo.id} className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 md:flex-row md:items-center md:justify-between">
                              <div className="flex min-w-0 items-center gap-3">
                                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-slate-50">
                                  {resolvePreviewKind(anexo) === "image" ? (
                                    <ImageIcon className="h-4 w-4 text-emerald-600" />
                                  ) : resolvePreviewKind(anexo) === "pdf" ? (
                                    <FileText className="h-4 w-4 text-red-500" />
                                  ) : (
                                    <Paperclip className="h-4 w-4 text-slate-500" />
                                  )}
                                </div>
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-medium text-slate-900">{anexo.nome_original || anexo.tipo}</p>
                                  <p className="mt-1 text-xs text-slate-500">
                                    {formatBytes(anexo.tamanho)}
                                    {anexo.created_at ? ` · ${formatDate(anexo.created_at)}` : ""}
                                  </p>
                                </div>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                <button
                                  onClick={() => abrirAnexo(anexo, "preview")}
                                  className="inline-flex items-center gap-1 rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-700 hover:bg-slate-200"
                                >
                                  {openingAttachmentId === anexo.id ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Eye className="h-4 w-4" />
                                  )}
                                  Visualizar
                                </button>
                                <button
                                  onClick={() => abrirAnexo(anexo, "download")}
                                  className="inline-flex items-center gap-1 rounded-xl bg-blue-100 px-3 py-2 text-sm text-blue-700 hover:bg-blue-200"
                                >
                                  <Download className="h-4 w-4" />
                                  Baixar
                                </button>
                                <button
                                  onClick={() => excluirAnexo(anexo)}
                                  className="inline-flex items-center gap-1 rounded-xl bg-red-100 px-3 py-2 text-sm text-red-700 hover:bg-red-200"
                                >
                                  <Trash2 className="h-4 w-4" />
                                  Remover
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="mt-3 text-sm text-slate-500">Nenhum arquivo enviado para este exame.</p>
                      )}
                    </div>
                  </>
                ) : null}
              </div>
            </div>
          );
        };
        return gruposExamesVisiveis.map((grupo) => (
          <Fragment key={grupo.categoria}>
            <div className="sticky top-0 z-10 -mx-1 bg-white/95 px-1 py-2 backdrop-blur-sm xl:top-[330px]">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                {grupo.categoria}
                <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium normal-case tracking-normal text-slate-500">
                  {grupo.itens.length}
                </span>
              </p>
            </div>
            {grupo.itens.map((item: AtendimentoExamesSectionProps) => renderExameCard(item))}
          </Fragment>
        ));
        })()}
        {examesVisiveis.length === 0 ? (
          <div className="rounded-[20px] border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            {exameFiltroRapido === "todos" ? (
              <p>Nenhum exame solicitado ainda.</p>
            ) : (
              <>
                <p>
                  Nenhum exame encontrado para o filtro &quot;
                  {EXAME_FILTRO_OPCOES.find((filtro: AtendimentoExamesSectionProps) => filtro.key === exameFiltroRapido)
                    ?.label || exameFiltroRapido}
                  &quot;.
                </p>
                <button
                  type="button"
                  onClick={() => setExameFiltroRapido("todos")}
                  className="mt-3 rounded-xl bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
                >
                  Ver todos os exames
                </button>
              </>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}
