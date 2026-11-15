"use client";

import axios from "axios";
import { useCallback, useEffect, useRef, useState } from "react";
import { BarChart3, RefreshCw } from "lucide-react";
import api from "@/lib/axios";
import { formatCalendarDate, OPERATIONAL_TIME_ZONE, operationalTodayDateInput } from "@/lib/calendar-date";
import MetricasPainel from "./MetricasPainel";
import PremissasEditor from "./PremissasEditor";
import { premissasDoContexto, premissasVazias, type ContextoGestao, type PainelGestao, type PremissasGestao, type PremissasSalvas } from "./types";

function contextoInicial(): ContextoGestao {
  const hoje = operationalTodayDateInput();
  return { data_inicio: `${hoje.slice(0, 7)}-01`, data_fim: hoje, clinica_id: null, regiao: null };
}
function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 403) return "Este painel é exclusivo de administradores.";
    if (error.response?.status === 409) return "Outro administrador alterou as premissas. Recarregue as premissas salvas e revise antes de salvar novamente.";
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}
function validar(contexto: ContextoGestao, values: PremissasGestao): string | null {
  if (!contexto.data_inicio || !contexto.data_fim || contexto.data_inicio > contexto.data_fim) return "Informe um período válido, com a data inicial anterior ou igual à final.";
  if ((Date.parse(contexto.data_fim) - Date.parse(contexto.data_inicio)) / 86_400_000 >= 366) return "Selecione no máximo 366 dias por consulta.";
  for (const [key, value] of Object.entries(values)) {
    if (typeof value !== "number") continue;
    if (!Number.isFinite(value) || (key !== "saldo_inicial" && value < 0) || (key.endsWith("_percentual") && value > 100)) return "Revise os valores das premissas. Percentuais devem estar entre 0 e 100; custos e horas não podem ser negativos.";
  }
  if (values.movimentos.some((m) => !m.data || !m.descricao.trim() || m.valor == null || !Number.isFinite(m.valor) || m.valor <= 0)) return "Preencha data, descrição e valor maior que zero em cada movimento adicional.";
  return null;
}
function atualizadoEm(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: OPERATIONAL_TIME_ZONE }).format(date);
}

export function GestaoWorkspace() {
  const [contexto, setContexto] = useState<ContextoGestao>(contextoInicial);
  const [salvas, setSalvas] = useState<PremissasSalvas | null>(null);
  const [values, setValues] = useState<PremissasGestao>(premissasVazias);
  const [painel, setPainel] = useState<PainelGestao | null>(null);
  const [filtros, setFiltros] = useState<PainelGestao["filtros"]>({ clinicas: [], regioes: [] });
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [storageAvailable, setStorageAvailable] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [storageWarning, setStorageWarning] = useState("");
  const [draftChanged, setDraftChanged] = useState(false);
  const [retry, setRetry] = useState(0);
  const requestId = useRef(0);
  const request = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const contextoRef = useRef(contexto);

  const carregarPainel = useCallback(async (recorte: ContextoGestao, premissas: PremissasGestao) => {
    const validation = validar(recorte, premissas);
    if (validation) { setError(validation); return; }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    setPainel(null);
    try {
      const response = await api.post<PainelGestao>("/gestao/painel", { ...recorte, premissas }, { signal: controller.signal, timeout: 30_000 });
      if (!mounted.current || controller.signal.aborted || id !== requestId.current) return;
      setPainel(response.data);
      setFiltros(response.data.filtros);
      setDraftChanged(false);
    } catch (err) {
      if (!mounted.current || controller.signal.aborted || id !== requestId.current) return;
      setError(errorMessage(err, "Não foi possível atualizar o painel. Tente novamente; os registros permanecem preservados."));
    } finally {
      if (mounted.current && id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let cancelled = false;
    const initialize = async () => {
      setLoading(true); setError("");
      try {
        const me = await api.get<{ papeis?: Array<string | { nome?: string }> }>("/auth/me", { signal: controller.signal });
        if (cancelled) return;
        const admin = me.data.papeis?.some((role) => (typeof role === "string" ? role : role.nome || "").toLowerCase() === "admin") === true;
        setAuthorized(admin);
        if (!admin) { setLoading(false); return; }
        let saved: PremissasSalvas | null = null;
        try {
          const response = await api.get<PremissasSalvas>("/gestao/premissas", { signal: controller.signal });
          saved = response.data;
          if (!cancelled) { setSalvas(saved); setStorageAvailable(true); setStorageWarning(""); }
        } catch (err) {
          if (cancelled) return;
          if (axios.isAxiosError(err) && [401, 403].includes(err.response?.status || 0)) throw err;
          setStorageAvailable(false);
          setStorageWarning("As premissas salvas estão indisponíveis. Você pode consultar e simular o painel; salvar ficará disponível após recuperar esse serviço.");
        }
        if (cancelled) return;
        const initial = premissasDoContexto(saved, contextoRef.current);
        setValues(initial);
        await carregarPainel(contextoRef.current, initial);
      } catch (err) {
        if (!cancelled) { setError(errorMessage(err, "Não foi possível validar o acesso administrativo. Tente novamente.")); setLoading(false); }
      }
    };
    void initialize();
    return () => { cancelled = true; mounted.current = false; controller.abort(); request.current?.abort(); ++requestId.current; };
  }, [carregarPainel, retry]);

  const alterarContexto = (next: ContextoGestao) => {
    request.current?.abort(); ++requestId.current;
    setContexto(next); contextoRef.current = next;
    setValues(premissasDoContexto(salvas, next)); setPainel(null); setLoading(false); setDraftChanged(false); setError("");
    setNotice("Recorte alterado. Atualize o painel para consultar os indicadores. Só serão usadas premissas salvas para este mesmo recorte.");
  };
  const salvar = async () => {
    const validation = validar(contexto, values);
    if (validation) { setError(validation); return; }
    if (!storageAvailable || !salvas) { setError("Recarregue as premissas salvas antes de salvar o cenário."); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      const response = await api.put<PremissasSalvas>("/gestao/premissas", { expected_revision: salvas.revision, contexto, values }, { timeout: 20_000 });
      if (!mounted.current) return;
      setSalvas(response.data);
      setNotice("Premissas salvas para este recorte. Nenhum registro operacional ou financeiro foi alterado.");
      await carregarPainel(contexto, values);
    } catch (err) {
      if (mounted.current) setError(errorMessage(err, "Não foi possível salvar as premissas. Confira o serviço e tente novamente."));
    } finally { if (mounted.current) setSaving(false); }
  };
  const recarregarPremissas = async () => {
    setSaving(true); setError("");
    try {
      const response = await api.get<PremissasSalvas>("/gestao/premissas");
      if (!mounted.current) return;
      setSalvas(response.data); setStorageAvailable(true); setStorageWarning("");
      setValues(premissasDoContexto(response.data, contexto)); setDraftChanged(true);
      setNotice("Premissas recarregadas para este recorte. Clique em Simular sem salvar para atualizar os números.");
    } catch (err) { if (mounted.current) setError(errorMessage(err, "Não foi possível recuperar as premissas salvas. A simulação continua disponível.")); }
    finally { if (mounted.current) setSaving(false); }
  };

  if (authorized === false) return <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-6">Este painel é exclusivo de administradores.</div>;
  return <div className="mx-auto max-w-[1600px] space-y-5 pb-10 text-slate-900">
    <header className="rounded-2xl bg-teal-950 p-6 text-white sm:p-8"><p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-teal-200"><BarChart3 className="h-4 w-4" />Fort Cordis · Administração</p><h1 className="mt-3 text-3xl font-semibold tracking-tight">Gestão do negócio</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-teal-100">Receita, capacidade, parceiros e caixa com a origem de cada número. Escolha um recorte para acompanhar as seis métricas e revisar as informações que ainda faltam.</p></header>
    {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900"><p>{error}</p><button type="button" disabled={loading || saving} onClick={() => authorized ? void carregarPainel(contexto, values) : setRetry((value) => value + 1)} className="mt-2 font-semibold underline">Tentar novamente</button></div>}
    {notice && <p role="status" className="rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-950">{notice}</p>}
    {storageWarning && <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">{storageWarning}<button type="button" onClick={() => void recarregarPremissas()} disabled={saving} className="ml-2 underline">Recuperar premissas</button></div>}
    {authorized && <>
      <form onSubmit={(event) => { event.preventDefault(); setNotice(""); void carregarPainel(contexto, values); }} className="grid items-end gap-3 rounded-2xl border border-slate-200 bg-white p-5 sm:grid-cols-2 xl:grid-cols-5">
        <label className="text-sm font-medium">Data inicial<input type="date" required value={contexto.data_inicio} disabled={saving} onChange={(event) => alterarContexto({ ...contexto, data_inicio: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
        <label className="text-sm font-medium">Data final<input type="date" required value={contexto.data_fim} disabled={saving} onChange={(event) => alterarContexto({ ...contexto, data_fim: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
        <label className="text-sm font-medium">Clínica<select value={contexto.clinica_id ?? ""} disabled={saving} onChange={(event) => alterarContexto({ ...contexto, clinica_id: event.target.value ? Number(event.target.value) : null })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"><option value="">Todas, inclusive sem vínculo</option>{filtros.clinicas.map((clinica) => <option key={clinica.id} value={clinica.id}>{clinica.nome}{clinica.ativo ? "" : " (inativa)"}</option>)}</select></label>
        <label className="text-sm font-medium">Região<select value={contexto.regiao ?? ""} disabled={saving} onChange={(event) => alterarContexto({ ...contexto, regiao: event.target.value || null })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"><option value="">Todas as regiões</option>{filtros.regioes.map((regiao) => <option key={regiao} value={regiao}>{regiao}</option>)}</select></label>
        <button type="submit" disabled={loading || saving} className="flex items-center justify-center gap-2 rounded-lg bg-teal-800 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{loading ? "Atualizando..." : "Atualizar painel"}</button>
      </form>
      <PremissasEditor value={values} onChange={(next) => { setValues(next); setDraftChanged(true); }} contexto={contexto} salvas={salvas} disabled={loading} saving={saving} canSave={storageAvailable} onSimulate={() => { setNotice("Simulação com as premissas do formulário. Estas alterações ainda não foram salvas."); void carregarPainel(contexto, values); }} onSave={() => void salvar()} onRestore={() => void recarregarPremissas()} />
      {draftChanged && painel && <p role="status" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-950">Há premissas editadas. Os indicadores abaixo ainda mostram o último cálculo; clique em Simular sem salvar ou salve o cenário para atualizar.</p>}
      {painel && <><div className="space-y-1 text-sm text-slate-600"><p><strong className="text-slate-900">{formatCalendarDate(painel.periodo.inicio)} a {formatCalendarDate(painel.periodo.fim)}</strong> · Comparação: {formatCalendarDate(painel.periodo.anterior_inicio)} a {formatCalendarDate(painel.periodo.anterior_fim)}</p><p>Atualizado em {atualizadoEm(painel.atualizado_em)} · Horário de Fortaleza.</p><p>A comparação usa períodos com o mesmo número de dias e o estado atual dos registros. Custos, horas, saldo e movimentos informados neste cenário não são extrapolados ao período anterior.</p></div><MetricasPainel atual={painel.atual} anterior={painel.anterior} /></>}
    </>}
    {loading && <div role="status" aria-live="polite" className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-600">{authorized ? "Consultando registros e calculando indicadores..." : "Validando acesso administrativo..."}</div>}
  </div>;
}
