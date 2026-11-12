"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/lib/axios";
import { lerErroFiscal } from "@/lib/fiscal-fechamento";
import { dataHoraFiscal, ETAPAS_FISCAIS, proximaEtapaFiscal, type EtapaFiscal, type FiscalAndamento } from "@/lib/fiscal-rotina";

const ACAO: Partial<Record<EtapaFiscal, { label: string; confirmacao: string }>> = {
  enviado_contador: { label: "Registrar envio ao contador", confirmacao: "Confirmo que enviei as informações desta OS ao contador." },
  nota_recebida: { label: "Registrar nota recebida", confirmacao: "Confirmo que recebi a nota desta OS, emitida pelo contador." },
  nota_encaminhada: { label: "Registrar encaminhamento da nota", confirmacao: "Confirmo que encaminhei a nota desta OS à clínica ou ao tomador." },
};

function AndamentoOS({ item, disabled, onUpdated, onRefresh, onBusyChange }: {
  item: FiscalAndamento;
  disabled: boolean;
  onUpdated: (item: FiscalAndamento) => void;
  onRefresh: () => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const destino = proximaEtapaFiscal(item.etapa);
  const acao = destino ? ACAO[destino] : null;
  const [referencia, setReferencia] = useState("");
  const [observacao, setObservacao] = useState("");
  const [confirmado, setConfirmado] = useState(false);
  const [saving, setSaving] = useState(false);
  const [erro, setErro] = useState("");
  const [conflito, setConflito] = useState(false);
  const savingRef = useRef(false);
  const requestKey = useRef<{ assinatura: string; chave: string } | null>(null);
  useEffect(() => {
    setReferencia(""); setObservacao(""); setConfirmado(false); setErro(""); setConflito(false);
    requestKey.current = null;
  }, [item]);

  async function registrar() {
    if (!destino || !confirmado || disabled || conflito || savingRef.current || (destino === "nota_recebida" && !referencia.trim())) return;
    savingRef.current = true;
    setSaving(true); onBusyChange(true); setErro("");
    const payload = {
      destino, versao_esperada: item.versao, confirmar_acao_manual: true,
      ...(destino === "nota_recebida" ? { referencia_nota: referencia.trim() } : {}),
      ...(observacao.trim() ? { observacao: observacao.trim() } : {}),
    };
    try {
      const assinatura = JSON.stringify([item.os_id, payload]);
      if (requestKey.current?.assinatura !== assinatura) requestKey.current = { assinatura, chave: crypto.randomUUID() };
      const response = await api.post<FiscalAndamento>(`/fiscal/os/${item.os_id}/andamento`, { ...payload, chave_idempotencia: requestKey.current.chave });
      onUpdated(response.data);
    } catch (error) {
      setErro((await lerErroFiscal(error, "Não foi possível registrar o andamento. A confirmação foi mantida para tentar novamente.")).mensagem);
      setConflito((error as { response?: { status?: number } }).response?.status === 409);
    } finally {
      savingRef.current = false;
      setSaving(false); onBusyChange(false);
    }
  }

  return <article className="rounded-lg border border-slate-200 p-3" aria-label={`Andamento da OS ${item.numero_os}`}>
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h4 className="font-semibold text-slate-900">OS {item.numero_os}</h4><p className="text-sm text-slate-600">{item.cliente_nome || item.clinica_nome || "Tomador não informado"}</p></div><span className="rounded-full bg-teal-50 px-2 py-1 text-xs font-semibold text-teal-900">{ETAPAS_FISCAIS[item.etapa]}</span></div>
    {item.referencia_nota && <p className="mt-2 text-sm text-slate-700">Referência da nota: {item.referencia_nota}</p>}
    {acao && <div className="mt-3 space-y-3 rounded-lg bg-slate-50 p-3">
      {destino === "nota_recebida" && <div><label htmlFor={`fiscal-nota-${item.os_id}`} className="mb-1 block text-sm">Número ou referência da nota *</label><input id={`fiscal-nota-${item.os_id}`} value={referencia} maxLength={200} disabled={disabled || saving} onChange={(event) => { setReferencia(event.target.value); setConfirmado(false); }} className="w-full rounded-lg border px-3 py-2 text-sm" /></div>}
      <div><label htmlFor={`fiscal-observacao-${item.os_id}`} className="mb-1 block text-sm">Observação do registro (opcional)</label><input id={`fiscal-observacao-${item.os_id}`} value={observacao} maxLength={2000} disabled={disabled || saving} onChange={(event) => { setObservacao(event.target.value); setConfirmado(false); }} className="w-full rounded-lg border px-3 py-2 text-sm" /></div>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmado} disabled={disabled || saving} onChange={(event) => setConfirmado(event.target.checked)} className="mt-1" /><span>{acao.confirmacao}</span></label>
      <p className="text-xs text-slate-500">Este botão registra uma ação que você já realizou.</p>
      <button type="button" onClick={() => void registrar()} disabled={disabled || saving || !confirmado || conflito || (destino === "nota_recebida" && !referencia.trim())} className="rounded-lg border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-900 disabled:opacity-50">{saving ? "Registrando..." : acao.label}</button>
    </div>}
    {erro && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800"><p>{erro}</p>{conflito && <button type="button" onClick={onRefresh} disabled={disabled} className="mt-2 font-semibold underline">Atualizar andamento antes de continuar</button>}</div>}
    {item.eventos.length > 0 && <details className="mt-3 text-sm"><summary className="cursor-pointer font-medium text-slate-700">Histórico desta OS ({item.eventos.length})</summary><ol className="mt-2 space-y-2">{item.eventos.map((event) => <li key={event.id} className="border-l-2 border-slate-200 pl-3"><p>{ETAPAS_FISCAIS[event.destino]} · {dataHoraFiscal(event.registrado_em)}</p><p className="text-xs text-slate-500">{event.usuario_nome || "Responsável não informado"}{event.referencia_nota ? ` · Nota ${event.referencia_nota}` : ""}</p>{event.observacao && <p className="text-xs text-slate-600">{event.observacao}</p>}</li>)}</ol></details>}
  </article>;
}

export default function FiscalAndamentos({ fechamentoId, disabled, onBusyChange }: { fechamentoId: number; disabled: boolean; onBusyChange: (busy: boolean) => void }) {
  const [items, setItems] = useState<FiscalAndamento[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState("");
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const carregar = useCallback(async () => {
    const requestId = ++generation.current;
    controller.current?.abort();
    const active = new AbortController(); controller.current = active;
    setLoading(true); setErro("");
    try {
      const response = await api.get<{ fechamento_id: number; items: FiscalAndamento[] }>(`/fiscal/fechamentos/${fechamentoId}/andamentos`, { signal: active.signal });
      if (!active.signal.aborted && requestId === generation.current) {
        if (response.data.fechamento_id !== fechamentoId) throw new Error("O andamento recebido pertence a outro pacote. Atualize a consulta.");
        setItems(response.data.items);
      }
    } catch (error) {
      const failure = await lerErroFiscal(error, "Não foi possível consultar os andamentos deste pacote.");
      if (!active.signal.aborted && requestId === generation.current) setErro(failure.mensagem);
    } finally {
      if (!active.signal.aborted && requestId === generation.current) setLoading(false);
    }
  }, [fechamentoId]);
  useEffect(() => {
    void carregar();
    return () => { controller.current?.abort(); generation.current += 1; };
  }, [carregar]);
  return <div className="space-y-3 rounded-lg bg-white p-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-slate-900">Andamento por OS · pacote #{fechamentoId}</h3><button type="button" onClick={() => void carregar()} disabled={loading || disabled} className="text-sm font-semibold text-blue-700 underline">Atualizar andamentos</button></div>
    <p className="text-xs text-slate-500">Cada OS tem seu próprio andamento, inclusive em pacotes com várias clínicas.</p>
    {loading ? <p role="status" className="text-sm text-slate-600">Carregando andamentos...</p> : erro ? <div role="alert" className="text-sm text-red-800"><p>{erro}</p><button type="button" onClick={() => void carregar()} className="mt-2 font-semibold underline">Tentar carregar andamentos novamente</button></div> : items.length ? items.map((item) => <AndamentoOS key={item.os_id} item={item} disabled={disabled} onBusyChange={onBusyChange} onRefresh={() => void carregar()} onUpdated={(updated) => setItems((previous) => previous.map((row) => row.os_id === updated.os_id ? updated : row))} />) : <p className="text-sm text-slate-600">Nenhuma OS encontrada neste pacote.</p>}
  </div>;
}
