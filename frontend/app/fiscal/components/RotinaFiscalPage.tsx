"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckSquare, Download, FileSpreadsheet, Loader2, RefreshCw } from "lucide-react";
import api from "@/lib/axios";
import { formatCalendarDate, operationalTodayDateInput } from "@/lib/calendar-date";
import { competenciaValida, formatarCompetencia, lerErroFiscal, nomeArquivoFiscal, servicoSelecionavel, type FiscalErro } from "@/lib/fiscal-fechamento";
import { assinaturaRotina, dataHoraFiscal, domingoFiscal, type FiscalPacoteRotina, type FiscalPreviaRotina, type FiscalRotinaClinica, type FiscalRotinas, type ModoFiscalRotina } from "@/lib/fiscal-rotina";
import FiscalAndamentos from "./FiscalAndamentos";
import FiscalRotinaPreferencias from "./FiscalRotinaPreferencias";

const dinheiro = (value: number) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
const MODOS: { id: ModoFiscalRotina; label: string }[] = [{ id: "semanal", label: "Semana" }, { id: "por_servico", label: "Por serviço · prioritário" }, { id: "mensal", label: "Conferência mensal" }];
const FONTE_REALIZACAO: Record<string, string> = { agenda: "Agenda", atendimento: "Atendimento", laudo: "Laudo", sem_evidencia: "Sem confirmação de realização" };

function baixarArquivo(data: Blob, filename: string) {
  const url = URL.createObjectURL(data);
  const link = document.createElement("a");
  link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
  const revoke = URL.revokeObjectURL.bind(URL);
  window.setTimeout(() => revoke(url), 1000);
}

export default function RotinaFiscalPage({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const [competencia, setCompetencia] = useState(() => operationalTodayDateInput().slice(0, 7));
  const [modo, setModo] = useState<ModoFiscalRotina>("semanal");
  const [dataCorte, setDataCorte] = useState("");
  const [clinicaId, setClinicaId] = useState("");
  const [config, setConfig] = useState<FiscalRotinas | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [erroConfig, setErroConfig] = useState("");
  const [previa, setPrevia] = useState<FiscalPreviaRotina | null>(null);
  const [loadingPrevia, setLoadingPrevia] = useState(true);
  const [erroPrevia, setErroPrevia] = useState("");
  const [atualizacao, setAtualizacao] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [datasConferidas, setDatasConferidas] = useState(false);
  const [exportacoesConferidas, setExportacoesConferidas] = useState(false);
  const [preparando, setPreparando] = useState(false);
  const [preferenciaBusy, setPreferenciaBusy] = useState(false);
  const [andamentoBusy, setAndamentoBusy] = useState(false);
  const [erroPreparacao, setErroPreparacao] = useState<FiscalErro | null>(null);
  const [pacotePreparado, setPacotePreparado] = useState<number | null>(null);
  const [historico, setHistorico] = useState<FiscalPacoteRotina[]>([]);
  const [totalHistorico, setTotalHistorico] = useState(0);
  const [proximoHistorico, setProximoHistorico] = useState(0);
  const [loadingHistorico, setLoadingHistorico] = useState(true);
  const [loadingMaisHistorico, setLoadingMaisHistorico] = useState(false);
  const [erroHistorico, setErroHistorico] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [erroDownload, setErroDownload] = useState("");
  const previewGeneration = useRef(0);
  const configGeneration = useRef(0);
  const historyGeneration = useRef(0);
  const preparingRef = useRef(false);
  const downloadingRef = useRef(false);
  const idempotencia = useRef<{ assinatura: string; chave: string } | null>(null);
  const busy = preparando || preferenciaBusy || andamentoBusy;
  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false); }, [busy, onBusyChange]);
  useEffect(() => { setPacotePreparado(null); setExpanded(null); }, [competencia, modo, dataCorte, clinicaId]);

  const carregarConfig = useCallback(async () => {
    const generation = ++configGeneration.current;
    setLoadingConfig(true); setErroConfig("");
    try {
      const response = await api.get<FiscalRotinas>("/fiscal/rotinas");
      if (generation === configGeneration.current) setConfig(response.data);
    } catch (error) {
      const failure = await lerErroFiscal(error, "Não foi possível consultar as preferências fiscais.");
      if (generation === configGeneration.current) setErroConfig(failure.mensagem);
    } finally {
      if (generation === configGeneration.current) setLoadingConfig(false);
    }
  }, []);
  useEffect(() => { void carregarConfig(); return () => { configGeneration.current += 1; }; }, [carregarConfig]);

  const carregarHistorico = useCallback(async (skip = 0) => {
    const generation = ++historyGeneration.current;
    setLoadingHistorico(skip === 0); setLoadingMaisHistorico(skip > 0); setErroHistorico("");
    try {
      const response = await api.get<{ items: FiscalPacoteRotina[]; total: number }>("/fiscal/fechamentos", { params: { competencia, skip, limit: 20 } });
      if (generation === historyGeneration.current) {
        setHistorico((previous) => skip > 0 ? Array.from(new Map([...previous, ...response.data.items].map((item) => [item.id, item])).values()) : response.data.items);
        setTotalHistorico(response.data.total);
        setProximoHistorico(skip + response.data.items.length);
        if (skip === 0) setExpanded((current) => response.data.items.some((item) => item.id === current) ? current : null);
      }
    } catch (error) {
      const failure = await lerErroFiscal(error, "Não foi possível consultar os pacotes preparados.");
      if (generation === historyGeneration.current) setErroHistorico(failure.mensagem);
    } finally {
      if (generation === historyGeneration.current) { setLoadingHistorico(false); setLoadingMaisHistorico(false); }
    }
  }, [competencia]);
  useEffect(() => {
    setHistorico([]); setTotalHistorico(0); setProximoHistorico(0); setExpanded(null);
    if (competenciaValida(competencia)) void carregarHistorico(); else { setLoadingHistorico(false); setLoadingMaisHistorico(false); }
    return () => { historyGeneration.current += 1; };
  }, [carregarHistorico, competencia]);

  useEffect(() => {
    const generation = ++previewGeneration.current;
    const controller = new AbortController();
    setPrevia(null); setSelected(new Set()); setDatasConferidas(false); setExportacoesConferidas(false); setErroPrevia(""); setErroPreparacao(null);
    if (!competenciaValida(competencia) || (modo === "semanal" && dataCorte && !domingoFiscal(dataCorte))) {
      setLoadingPrevia(false);
      return () => controller.abort();
    }
    setLoadingPrevia(true);
    void (async () => {
      try {
        const response = await api.get<FiscalPreviaRotina>("/fiscal/rotinas/previa", {
          params: { competencia, modo, ...(modo === "semanal" && dataCorte ? { data_corte: dataCorte } : {}), ...(clinicaId ? { clinica_id: Number(clinicaId) } : {}) }, signal: controller.signal,
        });
        if (controller.signal.aborted || generation !== previewGeneration.current) return;
        if (response.data.competencia !== competencia || response.data.rotina.modo !== modo) throw new Error("A prévia recebida pertence a outro contexto. Atualize a consulta.");
        if (modo === "semanal" && dataCorte && response.data.rotina.data_corte !== dataCorte) throw new Error("A prévia recebida não corresponde ao domingo de corte escolhido. Atualize a consulta.");
        setPrevia(response.data);
        const ids = response.data.items.filter((item) => servicoSelecionavel(item, competencia)).map((item) => item.os_id);
        setSelected(new Set(modo === "por_servico" ? ids.slice(0, 1) : modo === "mensal" ? [] : ids));
      } catch (error) {
        const failure = await lerErroFiscal(error, "Não foi possível carregar os serviços desta rotina.");
        if (!controller.signal.aborted && generation === previewGeneration.current) setErroPrevia(failure.mensagem);
      } finally {
        if (!controller.signal.aborted && generation === previewGeneration.current) setLoadingPrevia(false);
      }
    })();
    return () => controller.abort();
  }, [competencia, modo, dataCorte, clinicaId, atualizacao]);

  const aptas = useMemo(() => (previa?.items || []).filter((item) => servicoSelecionavel(item, competencia)), [previa, competencia]);
  const selecionadas = useMemo(() => aptas.filter((item) => selected.has(item.os_id)), [aptas, selected]);
  const totalSelecionado = selecionadas.reduce((total, item) => total + Number(item.valor_final || 0), 0);
  const temExportacoesAnteriores = selecionadas.some((item) => item.exportacoes_anteriores > 0);
  const corteEfetivo = modo === "semanal" ? previa?.rotina.data_corte || "" : "";
  const podePreparar = modo !== "mensal" && selecionadas.length > 0 && (modo !== "por_servico" || selecionadas.length === 1) && datasConferidas && (!temExportacoesAnteriores || exportacoesConferidas) && !loadingPrevia && !busy && (modo !== "semanal" || domingoFiscal(corteEfetivo));

  function alterarSelecao(next: Set<number>) {
    setSelected(next); setDatasConferidas(false); setExportacoesConferidas(false); setErroPreparacao(null);
  }
  function preferenciaSalva(item: FiscalRotinaClinica) {
    setConfig((previous) => previous ? { ...previous, clinicas: previous.clinicas.map((row) => row.clinica_id === item.clinica_id ? item : row) } : previous);
    setAtualizacao((value) => value + 1);
  }
  async function baixarPacote(id: number, filename?: string) {
    if (downloadingRef.current) return;
    downloadingRef.current = true; setDownloadingId(id); setErroDownload("");
    try {
      const response = await api.get(`/fiscal/fechamentos/${id}/download`, { responseType: "blob" });
      baixarArquivo(response.data, nomeArquivoFiscal(response.headers, filename || `fechamento_fiscal_${id}.zip`));
    } catch (error) { setErroDownload((await lerErroFiscal(error, "Não foi possível baixar o pacote. Tente novamente.")).mensagem); }
    finally { downloadingRef.current = false; setDownloadingId(null); }
  }
  async function prepararPacote() {
    if (modo === "mensal" || !podePreparar || preparingRef.current) return;
    preparingRef.current = true; setPreparando(true); setErroPreparacao(null); setPacotePreparado(null);
    const osIds = selecionadas.map((item) => item.os_id).sort((a, b) => a - b);
    const scopeClinica = modo === "por_servico" ? selecionadas[0].clinica_id : clinicaId ? Number(clinicaId) : null;
    const contexto = { competencia, modo, data_corte: corteEfetivo || null, clinica_id: scopeClinica };
    try {
      const assinatura = assinaturaRotina(contexto, osIds);
      if (idempotencia.current?.assinatura !== assinatura) idempotencia.current = { assinatura, chave: crypto.randomUUID() };
      const response = await api.post("/fiscal/rotinas/preparar", {
        competencia, modo, os_ids: osIds, chave_idempotencia: idempotencia.current.chave,
        confirmar_datas_prestacao: datasConferidas, confirmar_exportacoes_anteriores: temExportacoesAnteriores && exportacoesConferidas,
        ...(modo === "semanal" ? { data_corte: corteEfetivo } : {}), ...(scopeClinica ? { clinica_id: scopeClinica } : {}),
      }, { responseType: "blob" });
      const pacoteId = Number(response.headers["x-fechamento-id"]);
      baixarArquivo(response.data, nomeArquivoFiscal(response.headers, `FortCordis_${competencia}.zip`));
      setAtualizacao((value) => value + 1);
      if (Number.isInteger(pacoteId) && pacoteId > 0) setPacotePreparado(pacoteId);
      void carregarHistorico();
    } catch (error) { setErroPreparacao(await lerErroFiscal(error, "Não foi possível concluir o download. Sua seleção foi mantida para tentar novamente.")); }
    finally { preparingRef.current = false; setPreparando(false); }
  }

  return <div className="fc-fiscal-page">
    <header className="fc-fiscal-header"><div className="fc-fiscal-header-copy"><FileSpreadsheet className="mt-1 h-8 w-8 shrink-0" /><div><span className="fc-fiscal-kicker">Informações para a contabilidade</span><h1>Rotina fiscal</h1><p>Prepare os serviços confirmados e acompanhe cada OS até o encaminhamento da nota.</p></div></div></header>
    <section className="fc-fiscal-scope">
      <div className="fc-fiscal-section-heading"><div><span>Preparação manual</span><h2>Como organizar os serviços</h2></div></div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Modo da rotina fiscal">{MODOS.map((option) => <button key={option.id} type="button" aria-pressed={modo === option.id} disabled={busy} onClick={() => { setModo(option.id); setDataCorte(""); }} className={`rounded-lg border px-3 py-2 text-sm font-semibold ${modo === option.id ? "border-teal-700 bg-teal-50 text-teal-900" : "border-slate-200 text-slate-600"}`}>{option.label}</button>)}</div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3"><div><label htmlFor="rotina-competencia" className="mb-1 block text-sm">Competência dos serviços</label><input id="rotina-competencia" type="month" value={competencia} disabled={busy} onChange={(event) => { setCompetencia(event.target.value); setDataCorte(""); }} className="w-full rounded-lg border px-3 py-2" /></div>
        {modo === "semanal" && <div><label htmlFor="rotina-corte" className="mb-1 block text-sm">Domingo de corte · 17h</label><input id="rotina-corte" type="date" value={dataCorte || corteEfetivo} disabled={busy} onChange={(event) => setDataCorte(event.target.value)} className="w-full rounded-lg border px-3 py-2" /></div>}
        <div><label htmlFor="rotina-clinica" className="mb-1 block text-sm">Filtrar clínica</label><select id="rotina-clinica" value={clinicaId} disabled={busy || loadingConfig} onChange={(event) => setClinicaId(event.target.value)} className="w-full rounded-lg border px-3 py-2"><option value="">Todas as clínicas e atendimentos domiciliares</option>{config?.clinicas.map((item) => <option key={item.clinica_id} value={item.clinica_id}>{item.nome}</option>)}</select></div>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-slate-600">{modo === "semanal" ? "Padrão semanal: domingo às 17h, no horário de Fortaleza. O corte reúne os serviços da competência até essa data." : modo === "por_servico" ? "Priorize as clínicas que precisam das informações a cada serviço. Cada pacote contém uma única OS." : "Conferência de todos os serviços do mês. A preparação de pacotes fica nos modos Semana e Por serviço."}</p><button type="button" disabled={loadingPrevia || busy || !competenciaValida(competencia)} onClick={() => setAtualizacao((value) => value + 1)} className="fc-fiscal-primary"><RefreshCw className="h-4 w-4" />Atualizar serviços</button></div>
      {modo === "semanal" && previa?.rotina.corte_em && <p className="mt-2 text-sm font-semibold text-teal-900">Corte deste pacote: {dataHoraFiscal(previa.rotina.corte_em)} · Fortaleza</p>}
      <p className="mt-3 text-xs text-slate-500">Nenhum pacote, mensagem ou nota é enviado ou emitido automaticamente. O recebimento financeiro não define a competência. Confira as datas de prestação antes de preparar.</p>
    </section>

    {erroConfig && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800"><p>{erroConfig}</p><button type="button" disabled={busy || loadingConfig} onClick={() => void carregarConfig()} className="mt-2 font-semibold underline">Tentar consultar preferências novamente</button></div>}
    {config && <FiscalRotinaPreferencias clinicas={config.clinicas} disabled={busy || loadingConfig || modo === "mensal"} onSaved={preferenciaSalva} onRefresh={() => void carregarConfig()} onBusyChange={setPreferenciaBusy} />}
    {modo === "mensal" && <p className="text-sm text-slate-600">Conferência mensal em modo de leitura. Para preparar informações, alterar preferências ou registrar andamentos, abra Semana ou Por serviço.</p>}
    {!competenciaValida(competencia) && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Escolha o mês e o ano da prestação.</p>}
    {modo === "semanal" && dataCorte && !domingoFiscal(dataCorte) && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Escolha um domingo para o corte semanal às 17h de Fortaleza.</p>}
    {erroPrevia && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800"><p>{erroPrevia}</p><button type="button" onClick={() => setAtualizacao((value) => value + 1)} className="mt-2 font-semibold underline">Tentar carregar serviços novamente</button></div>}
    {loadingPrevia && <div role="status" className="fc-fiscal-empty flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />Carregando rotina de {formatarCompetencia(competencia)}...</div>}
    {previa && !loadingPrevia && <>
      <section className="fc-fiscal-metrics" aria-label="Resumo da rotina"><div className="fc-fiscal-metric fc-fiscal-metric-vital"><CheckSquare className="h-5 w-5" /><strong>{previa.resumo.quantidade_aptas}</strong><span>Aptas · {dinheiro(previa.resumo.valor_apto)}</span></div><div className="fc-fiscal-metric fc-fiscal-metric-amber"><AlertCircle className="h-5 w-5" /><strong>{previa.resumo.quantidade_pendentes}</strong><span>Com pendências de conferência</span></div><div className="fc-fiscal-metric fc-fiscal-metric-cordis"><FileSpreadsheet className="h-5 w-5" /><strong>{previa.resumo.quantidade_por_servico}</strong><span>Preparação por serviço</span></div><div className="fc-fiscal-metric fc-fiscal-metric-ink"><AlertCircle className="h-5 w-5" /><strong>{previa.resumo.quantidade_pagamento_depende_nf}</strong><span>Pagamento depende da NF</span></div></section>
      {previa.items.length ? <section className="fc-fiscal-results"><div className="fc-fiscal-results-heading"><div><h2 className="font-semibold text-slate-900">Serviços de {formatarCompetencia(competencia)}</h2><p className="text-sm">{modo === "mensal" ? "Conferência sem preparação" : `${selecionadas.length} selecionada(s) · ${dinheiro(totalSelecionado)}`}</p></div>{modo === "semanal" && <button type="button" disabled={busy || !aptas.length} onClick={() => alterarSelecao(selected.size === aptas.length ? new Set() : new Set(aptas.map((item) => item.os_id)))} className="text-sm font-semibold text-blue-700">{selected.size === aptas.length ? "Desmarcar aptas" : "Selecionar aptas"}</button>}</div>
        <div className="fc-fiscal-table-scroll"><table className="fc-fiscal-table"><thead><tr>{modo !== "mensal" && <th>Selecionar</th>}<th>OS / serviço</th><th>Prestação / realização</th><th>Tomador / documento</th><th>Rotina e situação</th><th className="text-right">Valor</th></tr></thead><tbody>{previa.items.map((item) => {
          const selecionavel = servicoSelecionavel(item, competencia);
          return <tr key={item.os_id} className={selected.has(item.os_id) && modo !== "mensal" ? "bg-blue-50" : ""}>{modo !== "mensal" && <td><input type={modo === "por_servico" ? "radio" : "checkbox"} name={modo === "por_servico" ? "rotina-os-individual" : undefined} aria-label={`Selecionar OS ${item.numero_os}`} checked={selected.has(item.os_id) && selecionavel} disabled={!selecionavel || busy} onChange={() => {
            if (modo === "por_servico") alterarSelecao(new Set([item.os_id]));
            else { const next = new Set(selected); next.has(item.os_id) ? next.delete(item.os_id) : next.add(item.os_id); alterarSelecao(next); }
          }} /></td>}<td><span className="block font-semibold">{item.numero_os}</span><span className="text-xs text-slate-500">{item.servico_nome || "Serviço não informado"}</span></td><td><span className="block whitespace-nowrap">{formatCalendarDate(item.data_prestacao)}</span><span className={`text-xs ${item.realizacao_confirmada ? "text-emerald-800" : "text-amber-800"}`}>{item.realizacao_confirmada ? `Realizado · ${FONTE_REALIZACAO[item.fonte_realizacao] || item.fonte_realizacao}` : "Realização pendente de confirmação"}</span></td><td><span className="block font-medium">{item.cliente_nome || "Tomador não informado"}</span><span className="text-xs text-slate-500">{item.cliente_documento || "Documento pendente"}</span></td><td><span className="block text-xs font-medium">{item.modo_preparacao === "por_servico" ? "Por serviço · prioritário" : "Semanal"}</span>{item.pagamento_depende_nf && <span className="block text-xs font-semibold text-amber-900">Pagamento depende da NF</span>}<span className="block text-xs text-slate-500">Financeiro: {item.status_os}</span>{item.motivos_pendencia?.map((reason) => <span key={reason} className="block text-xs text-amber-800">{reason}</span>)}{item.exportacoes_anteriores > 0 && <span className="block text-xs text-amber-800">Consta em exportações anteriores: {item.exportacoes_anteriores}</span>}{item.fechamento_id && <button type="button" disabled={downloadingId !== null} onClick={() => void baixarPacote(item.fechamento_id!)} className="mt-1 text-xs font-semibold text-blue-700 underline">Baixar pacote #{item.fechamento_id}</button>}</td><td className="whitespace-nowrap text-right font-semibold">{dinheiro(item.valor_final)}</td></tr>;
        })}</tbody></table></div>
      </section> : <div className="fc-fiscal-empty">Nenhum serviço encontrado nesta rotina e competência.</div>}
      {modo !== "mensal" && <section className="fc-fiscal-export"><div className="fc-fiscal-section-heading"><div><span>Conferência obrigatória</span><h2>{modo === "por_servico" ? "Preparar informações da OS selecionada" : "Preparar pacote semanal"}</h2></div></div><label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={datasConferidas} disabled={!selecionadas.length || busy} onChange={(event) => setDatasConferidas(event.target.checked)} className="mt-1" /><span>Conferi as datas de prestação e os serviços selecionados da competência {formatarCompetencia(competencia)}.</span></label>{temExportacoesAnteriores && <div className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><p>Exportação antiga não comprova envio ao contador nem emissão de nota.</p><label className="mt-2 flex items-start gap-2"><input type="checkbox" checked={exportacoesConferidas} disabled={busy} onChange={(event) => setExportacoesConferidas(event.target.checked)} className="mt-1" /><span>Conferi as exportações anteriores e confirmo a inclusão destes serviços.</span></label></div>}<div className="mt-4 flex flex-wrap items-center gap-4"><button type="button" onClick={() => void prepararPacote()} disabled={!podePreparar} className="fc-fiscal-export-button">{preparando ? <><Loader2 className="h-5 w-5 animate-spin" />Preparando pacote...</> : <><Download className="h-5 w-5" />{modo === "por_servico" ? "Preparar e baixar pacote desta OS" : "Preparar e baixar pacote semanal"}</>}</button><span className="text-sm font-semibold">{selecionadas.length} OS · {dinheiro(totalSelecionado)}</span></div><p className="mt-3 text-xs text-slate-500">O ZIP contém Excel, PDF de conferência, texto para o contador e manifesto. Depois, registre manualmente o andamento de cada OS no histórico.</p></section>}
    </>}
    {erroPreparacao && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800"><p>{erroPreparacao.mensagem}</p>{erroPreparacao.fechamentoIds.map((id) => <button key={id} type="button" disabled={downloadingId !== null} onClick={() => void baixarPacote(id)} className="mt-2 mr-4 font-semibold underline">Baixar pacote anterior #{id}</button>)}</div>}
    {pacotePreparado && <div role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">Pacote #{pacotePreparado} preparado. <button type="button" disabled={downloadingId !== null} onClick={() => void baixarPacote(pacotePreparado)} className="font-semibold underline">Baixar segunda via</button></div>}
    {erroDownload && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{erroDownload}</p>}
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" aria-label="Pacotes e andamento das OS">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-lg font-semibold text-slate-900">Pacotes e andamento por OS</h2><p className="text-sm text-slate-600">Competência {formatarCompetencia(competencia)}. A segunda via mantém o arquivo original.</p></div>
        <button type="button" onClick={() => void carregarHistorico()} disabled={loadingHistorico || loadingMaisHistorico || busy} className="rounded-lg border px-3 py-2 text-sm">Atualizar histórico</button>
      </div>
      {erroHistorico && <div role="alert" className="mt-3 text-sm text-red-800"><p>{erroHistorico}</p><button type="button" disabled={busy} onClick={() => void carregarHistorico()} className="mt-2 font-semibold underline">Tentar consultar histórico novamente</button></div>}
      {loadingHistorico ? <p role="status" className="py-4 text-sm text-slate-600">Carregando pacotes...</p> : !historico.length ? !erroHistorico && <p className="py-4 text-sm text-slate-600">Nenhum pacote preparado nesta competência.</p> : <>
        <div className="mt-3 overflow-x-auto"><table className="min-w-full text-sm">
          <thead className="border-b text-left text-xs uppercase text-slate-500"><tr><th className="p-2">Pacote</th><th className="p-2">Preparado em</th><th className="p-2">OS / valor</th><th className="p-2">Responsável</th><th className="p-2">Conferir</th></tr></thead>
          <tbody className="divide-y">{historico.map((item) => <Fragment key={item.id}>
            <tr><td className="p-2 font-semibold">#{item.id} · {formatarCompetencia(item.competencia)}</td><td className="whitespace-nowrap p-2">{dataHoraFiscal(item.preparado_em)}</td><td className="whitespace-nowrap p-2">{item.quantidade_os} OS · {dinheiro(item.valor_total)}</td><td className="p-2">{item.usuario_nome || "—"}</td>
              <td className="space-y-2 p-2">
                <button type="button" disabled={downloadingId !== null} onClick={() => void baixarPacote(item.id, item.arquivo_nome)} className="block font-semibold text-blue-700 underline">{downloadingId === item.id ? "Baixando..." : `Baixar segunda via #${item.id}`}</button>
                <button type="button" disabled={busy} aria-expanded={expanded === item.id} onClick={() => setExpanded(expanded === item.id ? null : item.id)} className="block font-semibold text-teal-800 underline">{expanded === item.id ? "Fechar" : "Ver"} andamento das OS #{item.id}</button>
              </td>
            </tr>
            {expanded === item.id && <tr><td colSpan={5} className="bg-slate-50 p-2"><FiscalAndamentos fechamentoId={item.id} disabled={busy || modo === "mensal"} onBusyChange={setAndamentoBusy} /></td></tr>}
          </Fragment>)}</tbody>
        </table></div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">{historico.length} de {totalHistorico} pacote(s) nesta competência.</p>
          {proximoHistorico < totalHistorico && <button type="button" disabled={loadingMaisHistorico || busy} onClick={() => void carregarHistorico(proximoHistorico)} className="rounded-lg border px-3 py-2 text-sm font-semibold text-teal-900">{loadingMaisHistorico ? "Carregando mais pacotes..." : "Carregar mais pacotes"}</button>}
        </div>
      </>}
    </section>
  </div>;
}
