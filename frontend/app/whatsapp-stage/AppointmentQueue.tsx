"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

type Item = {
  id: number; agendamento_id?: number | null; conversation_id: string; wa_identity: string; clinica_id: number; clinica_nome?: string; resumo: string; status: string;
  responsavel_nome: string | null; minha: boolean; sem_responsavel: boolean;
  prazo_em: string; atrasada: boolean; versao: number;
  historico: { acao: string; em: string; usuario_nome?: string; status?: string; observacao?: string; horario_preferido?: string; divergencias_confirmadas?: Record<string, { informado: string; selecionado: string }> }[];
};
type Queue = { itens: Item[]; total: number; contagens: Record<string, number> };
const labels: Record<string, string> = { aguardando_equipe: "Aguardando equipe", em_atendimento: "Em atendimento", aguardando_cliente: "Aguardando cliente", agendado: "Agendado", cancelado: "Cancelado" };
const date = (value: string) => new Date(value).toLocaleString("pt-BR");
async function request(url: string, init?: RequestInit) {
  const controller = init?.signal ? null : new AbortController();
  const timeout = controller ? window.setTimeout(() => controller.abort(), 15000) : null;
  try {
    const response = await fetch(url, { cache: "no-store", ...init, signal: init?.signal || controller?.signal, headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("token") || ""}` } });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Não foi possível atualizar a fila.");
    return result;
  } catch (error) {
    if (controller?.signal.aborted) throw new Error("A resposta demorou. Atualize a fila para conferir se a alteração foi salva antes de repetir.");
    throw error;
  } finally { if (timeout !== null) window.clearTimeout(timeout); }
}

export default function AppointmentQueue({ onOpen, conversationId }: { onOpen: (conversationId: string, identity: string) => void; conversationId?: string }) {
  const [open, setOpen] = useState(Boolean(conversationId));
  const [filtro, setFiltro] = useState("abertas");
  const [minhas, setMinhas] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Queue | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const sequence = useRef(0);
  const refresh = useCallback(() => setRevision(v => v + 1), []);
  useEffect(() => {
    if (!open) return;
    const seq = ++sequence.current;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setLoading(true);
    request(`/api/v1/whatsapp/bot/solicitacoes?filtro=${filtro}&minhas=${minhas}&page=${page}${conversationId ? `&conversation_id=${encodeURIComponent(conversationId)}` : ""}`, { signal: controller.signal })
      .then(result => { if (seq === sequence.current) { setData(result); setError(""); } })
      .catch(() => { if (seq === sequence.current) setError("Não foi possível carregar a fila. Tente atualizar."); })
      .finally(() => { if (seq === sequence.current) setLoading(false); });
    return () => { ++sequence.current; controller.abort(); window.clearTimeout(timeout); };
  }, [open, filtro, minhas, page, revision, conversationId]);
  useEffect(() => {
    if (!open || busy !== null) return;
    const timer = window.setInterval(refresh, 30000);
    return () => window.clearInterval(timer);
  }, [open, busy, refresh]);
  useEffect(() => {
    window.addEventListener("whatsapp-pedidos-atualizados", refresh);
    return () => window.removeEventListener("whatsapp-pedidos-atualizados", refresh);
  }, [refresh]);
  const update = async (item: Item, body: object) => {
    setBusy(item.id); setError("");
    try { await request(`/api/v1/whatsapp/bot/solicitacoes/${item.id}`, { method: "PATCH", body: JSON.stringify({ versao: item.versao, ...body }) }); refresh(); window.dispatchEvent(new Event("whatsapp-pedidos-atualizados")); }
    catch (e) { setError(e instanceof Error ? e.message : "Falha ao salvar. Atualize antes de repetir."); }
    finally { setBusy(null); }
  };
  return <section className={`rounded-xl border border-slate-200 bg-white p-4 ${conversationId ? "max-h-[40vh] shrink-0 overflow-y-auto" : ""}`} aria-label="Fila de solicitações de agendamento">
    <button type="button" className="font-semibold text-slate-900" aria-expanded={open} onClick={() => setOpen(!open)}>{conversationId ? "Pedidos desta conversa" : "Solicitações de agendamento"} {open ? "▴" : "▾"}</button>
    {open && <div className="mt-3 space-y-3">
      <p className="text-sm text-slate-600">Prazo inicial: 2 horas corridas para resposta, ajustável pelo responsável. Use “Agendar pedido” para escolher o horário na agenda e vincular o registro.</p>
      <div className="flex flex-wrap items-center gap-3">
        <select aria-label="Filtrar solicitações" value={filtro} onChange={e => { setFiltro(e.target.value); setPage(1); setData(null); }}>
          <option value="abertas">Em aberto</option><option value="atrasadas">Prazo vencido</option><option value="todas">Todas</option>
          {Object.entries(labels).map(([key,label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <label><input type="checkbox" checked={minhas} onChange={e => { setMinhas(e.target.checked); setPage(1); setData(null); }} /> Minhas solicitações</label>
        <button type="button" disabled={loading} onClick={refresh}>Atualizar fila</button>
      </div>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {loading && <p role="status">Atualizando solicitações…</p>}
      {data && !conversationId && <p className="text-sm">{data.total} pedidos neste filtro · {data.contagens.agendado || 0} agendados · {data.contagens.cancelado || 0} cancelados (total geral)</p>}
      {data?.itens.length === 0 && <p>Nenhuma solicitação neste filtro.</p>}
      {data?.itens.map(item => <QueueItem key={`${item.id}-${item.versao}`} item={item} disabled={busy !== null || loading} onUpdate={body => void update(item,body)} onOpen={conversationId ? undefined : () => onOpen(item.conversation_id, item.wa_identity)} />)}
      {data && data.total > 20 && <div className="flex gap-4"><button disabled={page === 1 || loading} onClick={() => {setPage(page-1);setData(null);}}>Anterior</button><span>Página {page}</span><button disabled={page*20 >= data.total || loading} onClick={() => {setPage(page+1);setData(null);}}>Próxima</button></div>}
    </div>}
  </section>;
}

function QueueItem({ item, disabled, onUpdate, onOpen }: { item: Item; disabled: boolean; onUpdate: (body: object) => void; onOpen?: () => void }) {
  const [status, setStatus] = useState(item.status);
  const [note, setNote] = useState("");
  const [deadline, setDeadline] = useState("");
  const closed = ["agendado", "cancelado"].includes(item.status);
  const complemento = [...item.historico].reverse().find(h => h.acao === 'complemento_cliente');
  const terminal = ["agendado", "cancelado"].includes(status);
  return <article className={`rounded-lg border p-3 ${item.atrasada ? "border-amber-500 bg-amber-50" : "border-slate-200"}`}>
    <div className="flex flex-wrap justify-between gap-2"><strong>Pedido #{item.id} · {item.clinica_nome || `Clínica #${item.clinica_id}`}</strong><span>{labels[item.status]}</span></div>
    <p>Responsável: {item.responsavel_nome || "Ainda não atribuído"}</p>
    <p className={item.atrasada ? "font-semibold text-amber-900" : "text-sm"}>{item.atrasada ? "Prazo vencido · " : "Prazo: "}{date(item.prazo_em)}</p>
    <pre className="my-2 whitespace-pre-wrap font-sans text-sm">{item.resumo}</pre>
    {complemento?.horario_preferido && <p className="my-2 rounded bg-sky-50 p-2 text-sm">Horário escolhido pelo cliente: {new Date(complemento.horario_preferido).toLocaleString("pt-BR", { timeZone: "America/Fortaleza" })} (Fortaleza). Sem reserva; confira a disponibilidade antes de agendar.</p>}
    {onOpen && <button type="button" onClick={onOpen}>Abrir conversa</button>}
    {item.agendamento_id && <p>Agendamento vinculado #{item.agendamento_id}. Consulte a agenda para o horário e eventuais alterações.</p>}
    {!closed && item.minha && <Link className="ml-4 font-semibold text-emerald-700" href={`/agenda?pedido_whatsapp=${item.id}`}>Agendar pedido</Link>}
    {!closed && item.sem_responsavel && <button type="button" className="ml-4 font-semibold" disabled={disabled} onClick={() => onUpdate({ acao: "assumir" })}>Assumir atendimento</button>}
    {!closed && item.minha && <div className="mt-3 flex flex-wrap items-end gap-3">
      <label>Status<select className="block" aria-label={`Status do pedido ${item.id}`} value={status} onChange={e => setStatus(e.target.value)}>{Object.entries(labels).filter(([k]) => k !== "aguardando_equipe" && k !== "agendado").map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label>Novo prazo (opcional)<input className="block" type="datetime-local" value={deadline} onChange={e => setDeadline(e.target.value)} /></label>
      <label>Resultado / observação<input className="block border" maxLength={500} value={note} onChange={e => setNote(e.target.value)} /></label>
      <button type="button" disabled={disabled || (terminal && !note.trim())} onClick={() => onUpdate({ acao: "atualizar", status, observacao: note, ...(deadline ? { prazo_em: new Date(deadline).toISOString() } : {}) })}>Salvar pedido</button>
      <button type="button" disabled={disabled} onClick={() => onUpdate({ acao: "liberar" })}>Devolver à equipe</button>
    </div>}
    <details className="mt-2 text-sm"><summary>Histórico do pedido</summary>{item.historico.map((h,i) => <p key={i}>{date(h.em)} · {h.usuario_nome || "Sistema"} · {h.status ? labels[h.status] : h.acao}{h.observacao ? ` · ${h.observacao}` : ""}{h.divergencias_confirmadas && Object.entries(h.divergencias_confirmadas).map(([campo, nomes]) => <span className="block" key={campo}>Divergência conferida ({campo}): “{nomes.informado}” → “{nomes.selecionado}”.</span>)}</p>)}</details>
  </article>;
}
