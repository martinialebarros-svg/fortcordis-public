"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckSquare, Download, FileSpreadsheet, FolderCheck, Loader2, RefreshCw } from "lucide-react";
import api from "@/lib/axios";
import { formatCalendarDate, operationalTodayDateInput } from "@/lib/calendar-date";
import {
  assinaturaSelecao,
  competenciaValida,
  FiscalErro,
  FiscalPacote,
  FiscalPrevia,
  formatarCompetencia,
  lerErroFiscal,
  nomeArquivoFiscal,
  servicoSelecionavel,
} from "@/lib/fiscal-fechamento";

const dinheiro = (value: number) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);

function baixarArquivo(data: Blob, filename: string) {
  const url = URL.createObjectURL(data);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  const revoke = URL.revokeObjectURL.bind(URL);
  window.setTimeout(() => revoke(url), 1000);
}

function dataHora(value: string): string {
  if (/(Z|[+-]\d{2}:\d{2})$/.test(value)) {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short", timeStyle: "short", timeZone: "America/Fortaleza",
    }).format(parsed);
  }
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return match ? `${match[3]}/${match[2]}/${match[1]} ${match[4]}:${match[5]}` : formatCalendarDate(value);
}

export default function FechamentoCompetenciaPage({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const [competencia, setCompetencia] = useState(() => operationalTodayDateInput().slice(0, 7));
  const [previa, setPrevia] = useState<FiscalPrevia | null>(null);
  const [loadingPrevia, setLoadingPrevia] = useState(true);
  const [erroPrevia, setErroPrevia] = useState("");
  const [atualizacao, setAtualizacao] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [datasConferidas, setDatasConferidas] = useState(false);
  const [exportacoesConferidas, setExportacoesConferidas] = useState(false);
  const [preparando, setPreparando] = useState(false);
  const [erroPreparacao, setErroPreparacao] = useState<FiscalErro | null>(null);
  const [pacotePreparado, setPacotePreparado] = useState<number | null>(null);
  const [historico, setHistorico] = useState<FiscalPacote[]>([]);
  const [loadingHistorico, setLoadingHistorico] = useState(true);
  const [erroHistorico, setErroHistorico] = useState("");
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [erroDownload, setErroDownload] = useState("");
  const previewGeneration = useRef(0);
  const historyGeneration = useRef(0);
  const preparingRef = useRef(false);
  const downloadingRef = useRef(false);
  const idempotencia = useRef<{ assinatura: string; chave: string } | null>(null);

  const carregarHistorico = useCallback(async () => {
    const generation = ++historyGeneration.current;
    setLoadingHistorico(true);
    setErroHistorico("");
    try {
      const response = await api.get<{ items: FiscalPacote[]; total: number }>("/fiscal/fechamentos");
      if (generation === historyGeneration.current) setHistorico(response.data.items);
    } catch (error) {
      const failure = await lerErroFiscal(error, "Não foi possível consultar os pacotes preparados.");
      if (generation === historyGeneration.current) setErroHistorico(failure.mensagem);
    } finally {
      if (generation === historyGeneration.current) setLoadingHistorico(false);
    }
  }, []);

  useEffect(() => {
    void carregarHistorico();
    return () => { historyGeneration.current += 1; };
  }, [carregarHistorico]);

  useEffect(() => {
    const generation = ++previewGeneration.current;
    const controller = new AbortController();
    setPrevia(null);
    setSelected(new Set());
    setDatasConferidas(false);
    setExportacoesConferidas(false);
    setErroPrevia("");
    if (!competenciaValida(competencia)) {
      setLoadingPrevia(false);
      return () => controller.abort();
    }
    setLoadingPrevia(true);
    void (async () => {
      try {
        const response = await api.get<FiscalPrevia>("/fiscal/fechamentos/previa", {
          params: { competencia }, signal: controller.signal,
        });
        if (controller.signal.aborted || generation !== previewGeneration.current) return;
        if (response.data.competencia !== competencia) throw new Error("A prévia recebida pertence a outro mês. Atualize a consulta.");
        setPrevia(response.data);
        setSelected(new Set(response.data.items.filter((item) => servicoSelecionavel(item, competencia)).map((item) => item.os_id)));
      } catch (error) {
        const failure = await lerErroFiscal(error, "Não foi possível carregar os serviços desta competência.");
        if (!controller.signal.aborted && generation === previewGeneration.current) setErroPrevia(failure.mensagem);
      } finally {
        if (!controller.signal.aborted && generation === previewGeneration.current) setLoadingPrevia(false);
      }
    })();
    return () => controller.abort();
  }, [competencia, atualizacao]);

  const aptas = useMemo(() => (previa?.items || []).filter((item) => servicoSelecionavel(item, competencia)), [previa, competencia]);
  const selecionadas = useMemo(() => aptas.filter((item) => selected.has(item.os_id)), [aptas, selected]);
  const totalSelecionado = selecionadas.reduce((total, item) => total + Number(item.valor_final || 0), 0);
  const temExportacoesAnteriores = selecionadas.some((item) => item.exportacoes_anteriores > 0);
  const podePreparar = selecionadas.length > 0 && datasConferidas && (!temExportacoesAnteriores || exportacoesConferidas) && !loadingPrevia && !preparando;

  function alterarSelecao(next: Set<number>) {
    setSelected(next);
    setDatasConferidas(false);
    setExportacoesConferidas(false);
    setErroPreparacao(null);
  }

  async function baixarPacote(id: number, filename?: string) {
    if (downloadingRef.current) return;
    downloadingRef.current = true;
    setDownloadingId(id);
    setErroDownload("");
    try {
      const response = await api.get(`/fiscal/fechamentos/${id}/download`, { responseType: "blob" });
      baixarArquivo(response.data, nomeArquivoFiscal(response.headers, filename || `fechamento_fiscal_${id}.zip`));
    } catch (error) {
      const failure = await lerErroFiscal(error, "Não foi possível baixar o pacote. Tente novamente.");
      setErroDownload(failure.mensagem);
    } finally {
      downloadingRef.current = false;
      setDownloadingId(null);
    }
  }

  async function prepararPacote() {
    if (!podePreparar || preparingRef.current) return;
    preparingRef.current = true;
    setPreparando(true);
    onBusyChange?.(true);
    setErroPreparacao(null);
    setPacotePreparado(null);
    const osIds = selecionadas.map((item) => item.os_id).sort((a, b) => a - b);
    const assinatura = assinaturaSelecao(competencia, osIds);
    try {
      if (idempotencia.current?.assinatura !== assinatura) {
        idempotencia.current = { assinatura, chave: crypto.randomUUID() };
      }
      const response = await api.post("/fiscal/fechamentos", {
        competencia,
        os_ids: osIds,
        chave_idempotencia: idempotencia.current.chave,
        confirmar_datas_prestacao: datasConferidas,
        confirmar_exportacoes_anteriores: temExportacoesAnteriores && exportacoesConferidas,
      }, { responseType: "blob" });
      const pacoteId = Number(response.headers["x-fechamento-id"]);
      if (Number.isInteger(pacoteId) && pacoteId > 0) setPacotePreparado(pacoteId);
      baixarArquivo(response.data, nomeArquivoFiscal(response.headers, `FortCordis_${competencia}.zip`));
      setAtualizacao((value) => value + 1);
      void carregarHistorico();
    } catch (error) {
      setErroPreparacao(await lerErroFiscal(error, "Não foi possível concluir o download. Tente novamente com a mesma seleção para recuperar o pacote."));
    } finally {
      preparingRef.current = false;
      setPreparando(false);
      onBusyChange?.(false);
    }
  }

  return (
    <div className="fc-fiscal-page">
      <header className="fc-fiscal-header">
        <div className="fc-fiscal-header-copy"><FileSpreadsheet className="mt-1 h-8 w-8 shrink-0" /><div>
          <span className="fc-fiscal-kicker">Informações para a contabilidade</span>
          <h1>Fechamento por competência</h1>
          <p>Prepare os serviços do mês em um pacote para conferência e envio ao contador.</p>
        </div></div>
      </header>

      <section className="fc-fiscal-scope">
        <div className="fc-fiscal-section-heading"><div><span>Etapa 1</span><h2>Mês da prestação dos serviços</h2></div></div>
        <div className="flex flex-wrap items-end gap-3">
          <div><label htmlFor="fiscal-competencia" className="mb-1 block text-sm">Competência</label>
            <input id="fiscal-competencia" type="month" value={competencia} disabled={preparando} onChange={(event) => {
              setCompetencia(event.target.value); setErroPreparacao(null); setPacotePreparado(null);
            }} className="rounded-lg border px-3 py-2" />
          </div>
          <button type="button" onClick={() => setAtualizacao((value) => value + 1)} disabled={loadingPrevia || preparando || !competenciaValida(competencia)} className="fc-fiscal-primary"><RefreshCw className="h-4 w-4" />Atualizar serviços</button>
        </div>
        <p className="mt-3 text-sm text-slate-600">A competência usa a data de atendimento registrada na OS. Confira se ela corresponde à prestação efetiva; o recebimento e a geração do arquivo podem ocorrer depois.</p>
        <p className="mt-2 text-sm text-slate-600">O pacote é informativo: contém Excel, PDF de conferência, mensagem em texto e manifesto. A emissão da nota e a orientação tributária ficam com o contador.</p>
      </section>

      {!competenciaValida(competencia) && <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Escolha o mês e o ano da prestação para consultar os serviços.</p>}
      {erroPrevia && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><p>{erroPrevia}</p><button type="button" onClick={() => setAtualizacao((value) => value + 1)} className="mt-2 font-semibold underline">Tentar carregar novamente</button></div>}
      {loadingPrevia && <div role="status" className="fc-fiscal-empty flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />Carregando serviços de {formatarCompetencia(competencia)}...</div>}
      {previa && !loadingPrevia && <>
        <section className="fc-fiscal-metrics" aria-label="Resumo da competência">
          <div className="fc-fiscal-metric fc-fiscal-metric-vital"><CheckSquare className="h-5 w-5" /><strong>{previa.resumo.quantidade_aptas}</strong><span>Aptas · {dinheiro(previa.resumo.valor_apto)}</span></div>
          <div className="fc-fiscal-metric fc-fiscal-metric-amber"><AlertCircle className="h-5 w-5" /><strong>{previa.resumo.quantidade_pendentes}</strong><span>Com pendências</span></div>
          <div className="fc-fiscal-metric fc-fiscal-metric-cordis"><AlertCircle className="h-5 w-5" /><strong>{previa.resumo.quantidade_canceladas}</strong><span>Canceladas · fora do fechamento</span></div>
          <div className="fc-fiscal-metric fc-fiscal-metric-ink"><FolderCheck className="h-5 w-5" /><strong>{previa.resumo.quantidade_ja_preparadas}</strong><span>Já incluídas em pacotes</span></div>
        </section>
        {previa.items.length > 0 ? <section className="fc-fiscal-results">
          <div className="fc-fiscal-results-heading">
            <div><h2 className="font-semibold text-slate-900">Serviços de {formatarCompetencia(competencia)}</h2><p className="text-sm">{selecionadas.length} selecionada(s) · {dinheiro(totalSelecionado)}</p></div>
            <button type="button" disabled={preparando || !aptas.length} onClick={() => alterarSelecao(selected.size === aptas.length ? new Set() : new Set(aptas.map((item) => item.os_id)))} className="text-sm font-medium text-blue-700">{selected.size === aptas.length ? "Desmarcar aptas" : "Selecionar aptas"}</button>
          </div>
          <div className="fc-fiscal-table-scroll"><table className="fc-fiscal-table">
            <thead><tr><th>Selecionar</th><th>OS / serviço</th><th>Data da prestação</th><th>Tomador / CPF ou CNPJ</th><th>Situação</th><th className="text-right">Valor</th></tr></thead>
            <tbody>{previa.items.map((item) => {
              const selecionavel = servicoSelecionavel(item, competencia);
              return <tr key={item.os_id} className={selected.has(item.os_id) ? "bg-blue-50" : ""}>
                <td><input type="checkbox" aria-label={`Selecionar OS ${item.numero_os}`} checked={selected.has(item.os_id) && selecionavel} disabled={!selecionavel || preparando} onChange={() => {
                  const next = new Set(selected); next.has(item.os_id) ? next.delete(item.os_id) : next.add(item.os_id); alterarSelecao(next);
                }} /></td>
                <td><span className="block font-medium">{item.numero_os}</span><span className="text-xs text-slate-500">{item.servico_nome || "Serviço não informado"}</span></td>
                <td className="whitespace-nowrap">{formatCalendarDate(item.data_prestacao)}</td>
                <td><span className="block font-medium">{item.cliente_nome || "Tomador não informado"}</span><span className="text-xs text-slate-500">{item.cliente_documento || "Documento pendente"}</span></td>
                <td><span className="block text-xs text-slate-600">OS {item.status_os}</span>
                  {item.motivos_pendencia?.map((reason) => <span key={reason} className="block text-xs text-amber-800">{reason}</span>)}
                  {item.exportacoes_anteriores > 0 && <span className="block text-xs text-amber-800">Consta em {item.exportacoes_anteriores} exportação(ões) anterior(es)</span>}
                  {item.fechamento_id && <button type="button" disabled={downloadingId !== null} onClick={() => void baixarPacote(item.fechamento_id!)} className="mt-1 text-xs font-semibold text-blue-700 underline">Baixar pacote #{item.fechamento_id}</button>}
                  {selecionavel && <span className="block text-xs text-emerald-800">Apta para preparação</span>}
                </td>
                <td className="whitespace-nowrap text-right font-semibold">{dinheiro(item.valor_final)}</td>
              </tr>;
            })}</tbody>
          </table></div>
        </section> : <div className="fc-fiscal-empty">Nenhuma OS com data registrada em {formatarCompetencia(competencia)}.</div>}

        <section className="fc-fiscal-export">
          <div className="fc-fiscal-section-heading"><div><span>Etapa 2</span><h2>Conferir e preparar o pacote</h2></div></div>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={datasConferidas} disabled={!selecionadas.length || preparando} onChange={(event) => setDatasConferidas(event.target.checked)} className="mt-1" /><span>Conferi que as datas das OS selecionadas correspondem aos serviços prestados em {formatarCompetencia(competencia)}.</span></label>
          {temExportacoesAnteriores && <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <p>Há serviços selecionados em exportações antigas. Esses downloads não comprovam envio ao contador nem emissão de nota.</p>
            <label className="mt-2 flex items-start gap-2"><input type="checkbox" checked={exportacoesConferidas} disabled={preparando} onChange={(event) => setExportacoesConferidas(event.target.checked)} className="mt-1" /><span>Conferi as exportações anteriores e confirmo a inclusão destes serviços no pacote.</span></label>
          </div>}
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <button type="button" onClick={() => void prepararPacote()} disabled={!podePreparar} className="fc-fiscal-export-button">{preparando ? <><Loader2 className="h-5 w-5 animate-spin" />Preparando pacote...</> : <><Download className="h-5 w-5" />Preparar e baixar pacote</>}</button>
            <span className="text-sm font-semibold text-slate-700">{selecionadas.length} OS · {dinheiro(totalSelecionado)}</span>
          </div>
          <p className="mt-3 text-xs text-slate-500">Depois da preparação, os serviços ficam vinculados ao pacote. A segunda via recupera o mesmo arquivo; o envio ao contador é feito por você.</p>
        </section>
      </>}

      {erroPreparacao && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800"><p>{erroPreparacao.mensagem}</p>
        {erroPreparacao.fechamentoIds.map((id) => <button key={id} type="button" disabled={downloadingId !== null} onClick={() => void baixarPacote(id)} className="mt-2 mr-4 font-semibold underline">Baixar pacote anterior #{id}</button>)}
        {!erroPreparacao.fechamentoIds.length && <p className="mt-2">Sua seleção foi mantida. Você pode tentar preparar novamente.</p>}
      </div>}
      {pacotePreparado && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">Pacote #{pacotePreparado} preparado. <button type="button" disabled={downloadingId !== null} onClick={() => void baixarPacote(pacotePreparado)} className="font-semibold underline">Baixar segunda via</button></div>}
      {erroDownload && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{erroDownload}</p>}

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" aria-label="Histórico de pacotes preparados">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold text-slate-900">Pacotes preparados</h2><p className="text-sm text-slate-600">A segunda via preserva a seleção e os valores da preparação original.</p></div>
          <button type="button" onClick={() => void carregarHistorico()} disabled={loadingHistorico} className="rounded-lg border px-3 py-2 text-sm">Atualizar histórico</button>
        </div>
        {erroHistorico ? <div role="alert" className="mt-3 text-sm text-red-800"><p>{erroHistorico}</p><button type="button" onClick={() => void carregarHistorico()} disabled={loadingHistorico} className="mt-1 font-semibold underline">Tentar consultar histórico novamente</button></div>
          : loadingHistorico ? <p role="status" className="py-4 text-sm text-slate-600">Carregando pacotes...</p>
          : !historico.length ? <p className="py-4 text-sm text-slate-600">Nenhum pacote preparado ainda.</p>
          : <div className="mt-3 overflow-x-auto"><table className="min-w-full text-sm"><thead className="border-b text-left text-xs uppercase text-slate-500"><tr><th className="px-2 py-2">Pacote / competência</th><th className="px-2 py-2">Preparado em</th><th className="px-2 py-2">OS</th><th className="px-2 py-2">Valor</th><th className="px-2 py-2">Responsável</th><th className="px-2 py-2">Arquivo</th></tr></thead>
            <tbody className="divide-y">{historico.map((item) => <tr key={item.id}><td className="px-2 py-3 font-medium">#{item.id} · {formatarCompetencia(item.competencia)}</td><td className="whitespace-nowrap px-2 py-3">{dataHora(item.preparado_em)}</td><td className="px-2 py-3">{item.quantidade_os}</td><td className="whitespace-nowrap px-2 py-3">{dinheiro(item.valor_total)}</td><td className="px-2 py-3">{item.usuario_nome || "—"}</td><td className="px-2 py-3"><button type="button" disabled={downloadingId !== null} onClick={() => void baixarPacote(item.id, item.arquivo_nome)} className="inline-flex items-center gap-2 font-semibold text-blue-700 underline">{downloadingId === item.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}Baixar segunda via #{item.id}</button></td></tr>)}</tbody>
          </table></div>}
      </section>
    </div>
  );
}
