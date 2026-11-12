"use client";

import { useRef, useState } from "react";
import {
  AlertTriangle,
  Archive,
  Bold,
  Download,
  Edit3,
  Eye,
  FileText,
  FileUp,
  Italic,
  Link2,
  List,
  Loader2,
  Paperclip,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings2,
  Trash2,
  TrendingUp,
  X,
} from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";
import AtendimentoHistoricoEdicoes from "./AtendimentoHistoricoEdicoes";

type AtendimentoDocumentosSectionProps = LooseAtendimentoComponentProps;

export type FormatoMarkdownDocumento = "negrito" | "italico" | "lista";

/**
 * Insere marcacao markdown-lite (**negrito**, *italico*, "- item") ao redor
 * da selecao atual do textarea. O PDF do documento (backend) interpreta essa
 * mesma marcacao - ver _texto_pdf_html_documento em atendimento.py.
 */
export function aplicarFormatacaoMarkdownDocumento(
  textarea: HTMLTextAreaElement | null,
  valorAtual: string,
  formato: FormatoMarkdownDocumento
): { valor: string; selecaoInicio: number; selecaoFim: number } | null {
  if (!textarea) return null;
  const inicio = textarea.selectionStart ?? valorAtual.length;
  const fim = textarea.selectionEnd ?? valorAtual.length;
  const selecionado = valorAtual.slice(inicio, fim);
  const antes = valorAtual.slice(0, inicio);
  const depois = valorAtual.slice(fim);

  if (formato === "lista") {
    const textoBase = selecionado || "Item da lista";
    const linhasFormatadas = textoBase
      .split("\n")
      .map((linha) => (linha.trimStart().startsWith("- ") ? linha : `- ${linha}`))
      .join("\n");
    const valor = `${antes}${linhasFormatadas}${depois}`;
    return { valor, selecaoInicio: antes.length, selecaoFim: antes.length + linhasFormatadas.length };
  }

  const marcador = formato === "negrito" ? "**" : "*";
  const textoBase = selecionado || (formato === "negrito" ? "texto em negrito" : "texto em italico");
  const inserido = `${marcador}${textoBase}${marcador}`;
  const valor = `${antes}${inserido}${depois}`;
  const selecaoInicio = antes.length + marcador.length;
  const selecaoFim = selecaoInicio + textoBase.length;
  return { valor, selecaoInicio, selecaoFim };
}

export default function AtendimentoDocumentosSection(props: AtendimentoDocumentosSectionProps) {
  const {
    ATENDIMENTO_ATTACHMENT_ACCEPT,
    adicionarLinkAnexo,
    anexosGerais,
    anexoArquivos,
    anexoForm,
    abrirAnexo,
    baixarPdfDocumentoClinico,
    cancelarUploadAnexo,
    criarDocumentoClinicoDeTemplate,
    documentTemplates,
    documentoPdfDownload,
    restaurarDocumentoClinico,
    atualizarListaDocumentos,
    documentoClinicoForm,
    documentoTemplateForm,
    documentoTemplateSelecionado,
    documentoVariaveisNaoResolvidas,
    editarDocumentoTemplate,
    evolucaoForm,
    excluirDocumentoClinico,
    excluirAnexo,
    formatBytes,
    formatDate,
    gerandoDocumentoPdfId,
    novoDocumentoClinicoLivre,
    openingAttachmentId,
    progressoUploadGeral,
    selecionado,
    setAnexoArquivos,
    setAnexoForm,
    setDocumentoClinicoForm,
    setDocumentoTemplateForm,
    setDocumentoTemplateSelecionado,
    setErro,
    setEvolucaoForm,
    setShowDocumentoTemplateEditor,
    setSucesso,
    showDocumentoTemplateEditor,
    salvandoDocumentoClinico,
    salvandoDocumentoTemplate,
    salvarDocumentoClinico,
    salvarDocumentoTemplate,
    selecionarDocumentoClinico,
    toggleDocumentoTemplate,
    uploadArquivosAnexoGeral,
    uploadGeralEmAndamento,
    abrirAtendimento,
    api,
    form,
  } = props;

  const templateEditorFormRef = useRef<HTMLDivElement | null>(null);
  const documentoCorpoRef = useRef<HTMLTextAreaElement | null>(null);
  const templateCorpoRef = useRef<HTMLTextAreaElement | null>(null);
  const [buscaDocumento, setBuscaDocumento] = useState("");

  const formatarDocumentoCorpo = (formato: FormatoMarkdownDocumento) => {
    const resultado = aplicarFormatacaoMarkdownDocumento(documentoCorpoRef.current, documentoClinicoForm.corpo, formato);
    if (!resultado) return;
    setDocumentoClinicoForm({ ...documentoClinicoForm, corpo: resultado.valor });
    requestAnimationFrame(() => {
      documentoCorpoRef.current?.focus();
      documentoCorpoRef.current?.setSelectionRange(resultado.selecaoInicio, resultado.selecaoFim);
    });
  };

  const formatarTemplateCorpo = (formato: FormatoMarkdownDocumento) => {
    const resultado = aplicarFormatacaoMarkdownDocumento(
      templateCorpoRef.current,
      documentoTemplateForm.corpo_template,
      formato
    );
    if (!resultado) return;
    setDocumentoTemplateForm({ ...documentoTemplateForm, corpo_template: resultado.valor });
    requestAnimationFrame(() => {
      templateCorpoRef.current?.focus();
      templateCorpoRef.current?.setSelectionRange(resultado.selecaoInicio, resultado.selecaoFim);
    });
  };
  const templatesAtivos = (documentTemplates || []).filter((template: AtendimentoDocumentosSectionProps) => Number(template.ativo ?? 1) === 1);
  const templatesPorTipo = templatesAtivos.reduce((grupos: Record<string, AtendimentoDocumentosSectionProps[]>, template: AtendimentoDocumentosSectionProps) => {
    const chave = template.tipo || "Outros";
    grupos[chave] = grupos[chave] || [];
    grupos[chave].push(template);
    return grupos;
  }, {});
  const documentosAtendimento = form.documentos || [];
  const templateEmEdicao = Boolean(documentoTemplateForm.id);

  const buscaDocumentoNormalizada = buscaDocumento.trim().toLowerCase();
  const documentosFiltrados = buscaDocumentoNormalizada
    ? documentosAtendimento.filter((documento: AtendimentoDocumentosSectionProps) =>
        (documento.titulo || "").toLowerCase().includes(buscaDocumentoNormalizada)
      )
    : documentosAtendimento;
  const documentosRascunho = documentosFiltrados.filter(
    (documento: AtendimentoDocumentosSectionProps) => documento.status !== "emitido" && documento.status !== "arquivado"
  );
  const documentosEmitidos = documentosFiltrados.filter(
    (documento: AtendimentoDocumentosSectionProps) => documento.status === "emitido"
  );

  const documentosArquivados = documentosFiltrados.filter((documento: AtendimentoDocumentosSectionProps) => documento.status === "arquivado");

  const renderDocumentoCard = (documento: AtendimentoDocumentosSectionProps) => (
    <div key={documento.id} className="rounded-[18px] border border-slate-200 bg-white p-3">
      <button type="button" onClick={() => selecionarDocumentoClinico(documento)} className="w-full text-left">
        <p className="text-sm font-semibold text-slate-900">{documento.titulo}</p>
        <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
              documento.status === "emitido" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"
            }`}
          >
            {documento.status === "arquivado" ? "Arquivado" : documento.status === "emitido" ? "Emitido" : "Rascunho"}
          </span>
          {(documento.emitido_at || documento.updated_at) ? <span>{documento.emitido_at ? "Emissao: " : "Atualizacao: "}{formatDate(documento.emitido_at || documento.updated_at)}</span> : null}
        </div>
      </button>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => selecionarDocumentoClinico(documento)}
          disabled={documento.status === "arquivado"}
          className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-700 hover:bg-slate-200"
        >
          <Edit3 className="h-3.5 w-3.5" />
          Editar
        </button>
        <button
          type="button"
          onClick={() => baixarPdfDocumentoClinico(documento)}
          disabled={gerandoDocumentoPdfId === documento.id || documento.status === "arquivado"}
          className="inline-flex items-center gap-1 rounded-lg bg-blue-100 px-2 py-1 text-xs text-blue-700 hover:bg-blue-200 disabled:opacity-50"
        >
          {gerandoDocumentoPdfId === documento.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          PDF
        </button>
        <button
          type="button"
          onClick={() => documento.status === "arquivado" ? restaurarDocumentoClinico(documento) : excluirDocumentoClinico(documento)}
          className="inline-flex items-center gap-1 rounded-lg bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200"
        >
          <Archive className="h-3.5 w-3.5" />
          {documento.status === "arquivado" ? "Restaurar" : "Arquivar"}
        </button>
      </div>
    </div>
  );

  const focusTemplateEditorForm = () => {
    window.requestAnimationFrame(() => {
      templateEditorFormRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      templateEditorFormRef.current
        ?.querySelector<HTMLInputElement>("input")
        ?.focus({ preventScroll: true });
    });
  };

  const handleToggleDocumentoTemplateEditor = () => {
    setShowDocumentoTemplateEditor(!showDocumentoTemplateEditor);
  };

  const handleEditarDocumentoTemplate = (template: AtendimentoDocumentosSectionProps) => {
    editarDocumentoTemplate(template);
    focusTemplateEditorForm();
  };

  return (
    <>
      {documentoPdfDownload ? (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm">
          PDF recebido. Confira o arquivo antes de considerar a entrega concluida.
          <a className="ml-3 underline" href={documentoPdfDownload.url} target="_blank" rel="noopener noreferrer">Abrir PDF</a>
          <a className="ml-3 underline" href={documentoPdfDownload.url} download={documentoPdfDownload.filename}>Baixar novamente</a>
        </div>
      ) : null}
      <button type="button" onClick={atualizarListaDocumentos} disabled={!selecionado} className="text-sm text-blue-700 underline">Atualizar lista de documentos</button>
      <section className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <FileText className="w-4 h-4 text-teal-600" />
              Documentos clinicos
            </h2>
            <p className="mt-1 text-sm text-slate-500">Pareceres, atestados, declaracoes e orientacoes do atendimento.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={novoDocumentoClinicoLivre}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              <Plus className="h-4 w-4" />
              Novo
            </button>
            <button
              type="button"
              onClick={handleToggleDocumentoTemplateEditor}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              <Settings2 className="h-4 w-4" />
              Templates
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[360px,minmax(0,1fr)]">
          <div className="space-y-3">
            <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-4">
              <label className="text-xs font-semibold uppercase text-slate-500">Template</label>
              <div className="mt-2 flex gap-2">
                <select
                  value={documentoTemplateSelecionado}
                  onChange={(event) => setDocumentoTemplateSelecionado(event.target.value)}
                  className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
                >
                  <option value="">Selecionar...</option>
                  {Object.entries(templatesPorTipo).map(([tipo, templates]) => (
                    <optgroup key={tipo} label={tipo}>
                      {(templates as AtendimentoDocumentosSectionProps[]).map((template: AtendimentoDocumentosSectionProps) => (
                        <option key={template.id} value={template.id}>
                          {template.nome}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={criarDocumentoClinicoDeTemplate}
                  disabled={!documentoTemplateSelecionado || salvandoDocumentoClinico}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-teal-600 px-3 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-50"
                >
                  {salvandoDocumentoClinico ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  Criar
                </button>
              </div>
            </div>

            {documentosAtendimento.length > 4 ? (
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={buscaDocumento}
                  onChange={(event) => setBuscaDocumento(event.target.value)}
                  placeholder="Buscar documento por titulo..."
                  className="w-full rounded-2xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm text-slate-900"
                />
              </div>
            ) : null}

            <div className="space-y-4">
              {documentosAtendimento.length === 0 ? (
                <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50 px-4 py-5 text-sm text-slate-500">
                  Nenhum documento clinico salvo neste atendimento.
                </div>
              ) : documentosFiltrados.length === 0 ? (
                <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50 px-4 py-5 text-sm text-slate-500">
                  <p>Nenhum documento encontrado para &quot;{buscaDocumento.trim()}&quot;.</p>
                  <button
                    type="button"
                    onClick={() => setBuscaDocumento("")}
                    className="mt-3 rounded-xl bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
                  >
                    Limpar busca
                  </button>
                </div>
              ) : (
                <>
                  {documentosRascunho.length > 0 ? (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Rascunhos ({documentosRascunho.length})
                      </p>
                      <div className="space-y-2">
                        {documentosRascunho.map((documento: AtendimentoDocumentosSectionProps) => renderDocumentoCard(documento))}
                      </div>
                    </div>
                  ) : null}
                  {documentosArquivados.length > 0 ? (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Arquivados ({documentosArquivados.length})</p>
                      {documentosArquivados.map((documento: AtendimentoDocumentosSectionProps) => renderDocumentoCard(documento))}
                    </div>
                  ) : null}
                  {documentosEmitidos.length > 0 ? (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Emitidos ({documentosEmitidos.length})
                      </p>
                      <div className="space-y-2">
                        {documentosEmitidos.map((documento: AtendimentoDocumentosSectionProps) => renderDocumentoCard(documento))}
                      </div>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>

          <div className="rounded-[20px] border border-slate-200 bg-white p-4">
            <div className="grid grid-cols-1 gap-3">
              {documentoClinicoForm.status === "emitido" ? (
                <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>
                    Um PDF deste documento ja foi gerado. Isso nao confirma o download nem a entrega.
                    Voce pode editar e salvar normalmente; as alteracoes ficam no historico e so aparecem em um novo PDF.
                  </span>
                </div>
              ) : null}
              {documentoVariaveisNaoResolvidas && documentoVariaveisNaoResolvidas.length > 0 ? (
                <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>
                    {documentoVariaveisNaoResolvidas.length} campo(s) do template nao {documentoVariaveisNaoResolvidas.length === 1 ? "foi reconhecido" : "foram reconhecidos"}:{" "}
                    {documentoVariaveisNaoResolvidas.join(", ")} - revise o texto antes de gerar o PDF.
                  </span>
                </div>
              ) : null}
              <input
                readOnly={documentoClinicoForm.status === "arquivado"}
                value={documentoClinicoForm.titulo}
                onChange={(event) => setDocumentoClinicoForm({ ...documentoClinicoForm, titulo: event.target.value })}
                placeholder="Titulo do documento"
                className="rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium"
              />
              <div>
                <div className="flex flex-wrap gap-1 rounded-t-xl border border-b-0 border-slate-200 bg-slate-50 p-1">
                  <button
                    type="button"
                    title="Negrito (**texto**)"
                    onClick={() => formatarDocumentoCorpo("negrito")}
                    className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-200"
                  >
                    <Bold className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    title="Italico (*texto*)"
                    onClick={() => formatarDocumentoCorpo("italico")}
                    className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-200"
                  >
                    <Italic className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    title="Lista (- item)"
                    onClick={() => formatarDocumentoCorpo("lista")}
                    className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-200"
                  >
                    <List className="h-3.5 w-3.5" />
                  </button>
                </div>
                <textarea
                  readOnly={documentoClinicoForm.status === "arquivado"}
                  ref={documentoCorpoRef}
                  value={documentoClinicoForm.corpo}
                  onChange={(event) => setDocumentoClinicoForm({ ...documentoClinicoForm, corpo: event.target.value })}
                  placeholder="Texto do documento..."
                  rows={12}
                  className="min-h-[280px] w-full rounded-b-xl rounded-t-none border border-slate-200 px-3 py-2 text-sm leading-6"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => salvarDocumentoClinico()}
                  disabled={documentoClinicoForm.status === "arquivado" || salvandoDocumentoClinico || !documentoClinicoForm.titulo.trim() || !documentoClinicoForm.corpo.trim()}
                  className="inline-flex items-center gap-2 rounded-xl bg-teal-600 px-4 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-50"
                >
                  {salvandoDocumentoClinico ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Salvar documento
                </button>
                <button
                  type="button"
                  onClick={() => baixarPdfDocumentoClinico()}
                  disabled={documentoClinicoForm.status === "arquivado" || (gerandoDocumentoPdfId != null && gerandoDocumentoPdfId === documentoClinicoForm.id) || !documentoClinicoForm.titulo.trim() || !documentoClinicoForm.corpo.trim()}
                  className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {gerandoDocumentoPdfId === documentoClinicoForm.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                  Gerar PDF
                </button>
              </div>
              {selecionado && documentoClinicoForm.id ? (
                <AtendimentoHistoricoEdicoes
                  key={`${selecionado}:${documentoClinicoForm.id}`}
                  atendimentoId={selecionado}
                  documentoId={documentoClinicoForm.id}
                  refreshKey={documentoClinicoForm.versao}
                />
              ) : null}
            </div>
          </div>
        </div>

        {showDocumentoTemplateEditor ? (
          <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-4">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr),minmax(320px,420px)]">
              <div className="space-y-2">
                {(documentTemplates || []).map((template: AtendimentoDocumentosSectionProps) => (
                  <div key={template.id} className="flex flex-col gap-2 rounded-[16px] border border-slate-200 bg-white p-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">{template.nome}</p>
                      <p className="text-xs text-slate-500">{template.tipo} · {Number(template.ativo ?? 1) === 1 ? "ativo" : "inativo"}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => handleEditarDocumentoTemplate(template)}
                        className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-700 hover:bg-slate-200"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                        Editar
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleDocumentoTemplate(template)}
                        className="inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-xs text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                        {Number(template.ativo ?? 1) === 1 ? "Desativar" : "Reativar"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <div ref={templateEditorFormRef} className="space-y-3 rounded-[16px] border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      {templateEmEdicao ? "Editando template" : "Novo template"}
                    </p>
                    {templateEmEdicao ? (
                      <p className="text-xs text-slate-500">{documentoTemplateForm.nome}</p>
                    ) : null}
                  </div>
                  {templateEmEdicao ? (
                    <span className="rounded-full bg-teal-50 px-2 py-1 text-xs font-medium text-teal-700">
                      #{documentoTemplateForm.id}
                    </span>
                  ) : null}
                </div>
                <input
                  value={documentoTemplateForm.nome}
                  onChange={(event) => setDocumentoTemplateForm({ ...documentoTemplateForm, nome: event.target.value })}
                  placeholder="Nome do template"
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                />
                <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr),96px]">
                  <input
                    value={documentoTemplateForm.tipo}
                    onChange={(event) => setDocumentoTemplateForm({ ...documentoTemplateForm, tipo: event.target.value })}
                    placeholder="Tipo"
                    className="rounded-xl border border-slate-200 px-3 py-2 text-sm"
                  />
                  <input
                    value={documentoTemplateForm.ordem}
                    onChange={(event) => setDocumentoTemplateForm({ ...documentoTemplateForm, ordem: event.target.value })}
                    placeholder="Ordem"
                    type="number"
                    className="rounded-xl border border-slate-200 px-3 py-2 text-sm"
                  />
                </div>
                <input
                  value={documentoTemplateForm.titulo_padrao}
                  onChange={(event) => setDocumentoTemplateForm({ ...documentoTemplateForm, titulo_padrao: event.target.value })}
                  placeholder="Titulo padrao"
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                />
                <div>
                  <div className="flex flex-wrap gap-1 rounded-t-xl border border-b-0 border-slate-200 bg-slate-50 p-1">
                    <button
                      type="button"
                      title="Negrito (**texto**)"
                      onClick={() => formatarTemplateCorpo("negrito")}
                      className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-200"
                    >
                      <Bold className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      title="Italico (*texto*)"
                      onClick={() => formatarTemplateCorpo("italico")}
                      className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-200"
                    >
                      <Italic className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      title="Lista (- item)"
                      onClick={() => formatarTemplateCorpo("lista")}
                      className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-200"
                    >
                      <List className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <textarea
                    ref={templateCorpoRef}
                    value={documentoTemplateForm.corpo_template}
                    onChange={(event) => setDocumentoTemplateForm({ ...documentoTemplateForm, corpo_template: event.target.value })}
                    placeholder="Corpo do template com variaveis como {{paciente_nome}}, {{tutor_nome}}, {{veterinario_nome}}, {{crmv}}..."
                    rows={9}
                    className="w-full rounded-b-xl rounded-t-none border border-slate-200 px-3 py-2 text-sm leading-6"
                  />
                </div>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={Number(documentoTemplateForm.ativo ?? 1) === 1}
                    onChange={(event) => setDocumentoTemplateForm({ ...documentoTemplateForm, ativo: event.target.checked ? 1 : 0 })}
                  />
                  Ativo
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={salvarDocumentoTemplate}
                    disabled={salvandoDocumentoTemplate}
                    className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    {salvandoDocumentoTemplate ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    {templateEmEdicao ? "Atualizar template" : "Salvar template"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDocumentoTemplateForm({ id: null, nome: "", tipo: "documento", titulo_padrao: "", corpo_template: "", ordem: "", ativo: 1 })}
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    <Plus className="h-4 w-4" />
                    Limpar
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </section>

      <section className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <h2 className="font-semibold text-gray-900 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-purple-600" />
          Evolucao Clinica
        </h2>
        {form.evolucoes.length > 0 && (
          <div className="space-y-2 mb-4">
            <h3 className="font-medium text-sm text-gray-600">Historico de evolucoes</h3>
            {form.evolucoes.map((evo: AtendimentoDocumentosSectionProps) => (
              <div key={evo.id} className="border rounded-lg p-3 bg-gray-50">
                <div className="flex justify-between items-start">
                  <span className="text-xs text-gray-500">
                    {formatDate(evo.data_evolucao)} - {evo.responsavel_nome}
                  </span>
                </div>
                <p className="text-sm mt-1">{evo.descricao}</p>
                {evo.sinais_vitais ? (
                  <p className="text-xs text-gray-500 mt-1">Sinais vitais: {evo.sinais_vitais}</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
        <div className="border-t pt-4">
          <h3 className="font-medium text-sm text-gray-700 mb-2">Nova evolucao</h3>
          <textarea
            value={evolucaoForm.descricao}
            onChange={(e) => setEvolucaoForm({ ...evolucaoForm, descricao: e.target.value })}
            placeholder="Descricao da evolucao..."
            rows={3}
            className="w-full px-3 py-2 border rounded-lg text-sm mb-2"
          />
          <textarea
            value={evolucaoForm.sinais_vitais}
            onChange={(e) => setEvolucaoForm({ ...evolucaoForm, sinais_vitais: e.target.value })}
            placeholder="Sinais vitais (opcional)..."
            rows={2}
            className="w-full px-3 py-2 border rounded-lg text-sm mb-2"
          />
          <button
            onClick={async () => {
              if (!selecionado || !evolucaoForm.descricao.trim()) return;
              try {
                await api.post(`/atendimentos/${selecionado}/evolucoes`, evolucaoForm);
                setEvolucaoForm({ descricao: "", sinais_vitais: "" });
                await abrirAtendimento(selecionado);
                setSucesso("Evolucao registrada com sucesso.");
              } catch {
                setErro("Erro ao registrar evolucao.");
              }
            }}
            disabled={!selecionado || !evolucaoForm.descricao.trim()}
            className="px-4 py-2 rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 text-sm flex items-center gap-1"
          >
            <Plus className="w-4 h-4" />
            Registrar Evolucao
          </button>
        </div>
      </section>

      <section className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <h2 className="font-semibold text-gray-900 flex items-center gap-2">
          <Paperclip className="w-4 h-4 text-orange-600" />
          Anexos e Imagens
        </h2>
        {anexosGerais.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {anexosGerais.map((anexo: AtendimentoDocumentosSectionProps) => (
              <div key={anexo.id} className="overflow-hidden rounded-[20px] border border-slate-200 bg-slate-50 p-4">
                <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="break-all text-sm font-medium text-slate-900">{anexo.nome_original || anexo.tipo}</p>
                    <p className="mt-1 text-xs text-slate-500">{anexo.descricao || anexo.tipo}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatBytes(anexo.tamanho)}
                      {anexo.created_at ? ` · ${formatDate(anexo.created_at)}` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2 md:w-32 md:flex-col md:items-stretch">
                    <button
                      onClick={() => abrirAnexo(anexo, "preview")}
                      className="inline-flex items-center justify-center gap-1 rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-700 hover:bg-slate-200"
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
                      className="inline-flex items-center justify-center gap-1 rounded-xl bg-blue-100 px-3 py-2 text-sm text-blue-700 hover:bg-blue-200"
                    >
                      <Download className="h-4 w-4" />
                      Baixar
                    </button>
                    <button
                      onClick={() => excluirAnexo(anexo)}
                      className="inline-flex items-center justify-center gap-1 rounded-xl bg-red-100 px-3 py-2 text-sm text-red-700 hover:bg-red-200"
                    >
                      <Trash2 className="h-4 w-4" />
                      Remover
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-[20px] border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            Nenhum anexo geral registrado neste atendimento.
          </div>
        )}
        <div className="border-t pt-4 space-y-4">
          <h3 className="font-medium text-sm text-gray-700">Novo anexo</h3>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <select
              value={anexoForm.tipo}
              onChange={(e) => setAnexoForm({ ...anexoForm, tipo: e.target.value })}
              className="px-3 py-2 border rounded-lg text-sm"
            >
              <option value="imagem">Imagem</option>
              <option value="radiografia">Radiografia</option>
              <option value="ultrassom">Ultrassom</option>
              <option value="documento">Documento</option>
              <option value="outro">Outro</option>
            </select>
            <input
              value={anexoForm.descricao}
              onChange={(e) => setAnexoForm({ ...anexoForm, descricao: e.target.value })}
              placeholder="Descricao"
              className="px-3 py-2 border rounded-lg text-sm"
            />
            <div className="flex items-center gap-2 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-600">
              <FileUp className="h-4 w-4 text-slate-400" />
              <input
                key={
                  anexoArquivos.length > 0
                    ? anexoArquivos.map((file: File) => `${file.name}-${file.lastModified}`).join("|")
                    : "anexo-vazio"
                }
                type="file"
                multiple
                accept={ATENDIMENTO_ATTACHMENT_ACCEPT}
                onChange={(e) => setAnexoArquivos(Array.from(e.target.files || []))}
                className="w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:text-white"
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={async () => {
                if (anexoArquivos.length === 0) return;
                await uploadArquivosAnexoGeral(anexoArquivos);
              }}
              disabled={!selecionado || anexoArquivos.length === 0 || uploadGeralEmAndamento}
              className="inline-flex items-center gap-2 rounded-xl bg-orange-600 px-4 py-2 text-sm text-white hover:bg-orange-700 disabled:opacity-50"
            >
              {uploadGeralEmAndamento ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
              {uploadGeralEmAndamento
                ? typeof progressoUploadGeral === "number"
                  ? `Enviando ${progressoUploadGeral}%`
                  : "Enviando..."
                : anexoArquivos.length > 1
                ? `Enviar ${anexoArquivos.length} arquivos`
                : "Enviar arquivo"}
            </button>
            {uploadGeralEmAndamento ? (
              <button
                type="button"
                onClick={() => cancelarUploadAnexo("geral")}
                className="inline-flex items-center gap-2 rounded-xl bg-red-100 px-4 py-2 text-sm text-red-700 hover:bg-red-200"
              >
                <X className="h-4 w-4" />
                Cancelar upload
              </button>
            ) : null}
          </div>
          {anexoArquivos.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {anexoArquivos.map((file: File, index: number) => (
                <span
                  key={`${file.name}-${file.lastModified}-${index}`}
                  className="inline-flex items-center gap-2 rounded-xl bg-slate-100 px-3 py-2 text-xs text-slate-600"
                >
                  {file.name} · {formatBytes(file.size)}
                  <button
                    type="button"
                    onClick={() => setAnexoArquivos(anexoArquivos.filter((_: File, i: number) => i !== index))}
                    disabled={uploadGeralEmAndamento}
                    aria-label={`Remover ${file.name} da selecao`}
                    className="text-slate-400 hover:text-slate-700 disabled:opacity-50"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </span>
              ))}
            </div>
          ) : null}

          {uploadGeralEmAndamento ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                <div
                  className={`h-full rounded-full bg-orange-600 transition-[width] duration-200 ${
                    typeof progressoUploadGeral === "number" ? "" : "animate-pulse"
                  }`}
                  style={{ width: `${typeof progressoUploadGeral === "number" ? progressoUploadGeral : 35}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-slate-600">
                {typeof progressoUploadGeral === "number"
                  ? `Upload geral em andamento (${progressoUploadGeral}%).`
                  : "Upload geral em andamento..."}
              </p>
            </div>
          ) : null}

          <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm font-medium text-slate-900">Adicionar link externo</p>
            <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr),auto]">
              <input
                value={anexoForm.url}
                onChange={(e) => setAnexoForm({ ...anexoForm, url: e.target.value })}
                placeholder="URL do arquivo"
                className="px-3 py-2 border rounded-lg text-sm"
              />
              <button
                onClick={adicionarLinkAnexo}
                disabled={!selecionado || !anexoForm.url.trim()}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-4 py-2 text-sm text-slate-700 border border-slate-200 hover:bg-slate-100 disabled:opacity-50"
              >
                <Link2 className="h-4 w-4" />
                Adicionar link
              </button>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
