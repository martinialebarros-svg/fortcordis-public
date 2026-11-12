"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./FollowUpPanel.module.css";

export interface FollowUp {
  due_at: string; note: string; agent_id: string; agent_name: string | null;
  status: "pending" | "completed" | "cancelled"; revision: number;
  inbound_received_at: string | null; updated_at: string;
}
interface Agent { id: string; name: string | null; email: string | null; active: boolean }
interface Draft { due: string; note: string; agent: string; revision: number }
interface Entry { loaded?: boolean; data?: FollowUp | null; draft?: Draft; error?: string; notice?: string; conflict?: boolean }
const headers = () => {
  const token = window.localStorage.getItem("token");
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
};
export const followUpDateInput = (date: Date) => new Date(date.getTime() - 3 * 3600000).toISOString().slice(0, 16);
export const followUpDateLabel = (date: string) => new Date(date).toLocaleString("pt-BR", {
  timeZone: "America/Fortaleza", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
});
export function followUpLabel(followUp: FollowUp, now: number): string {
  if (followUp.inbound_received_at) return "Cliente respondeu · revisar retorno";
  return `${Date.parse(followUp.due_at) <= now ? "Retorno atrasado" : "Retorno"} · ${followUpDateLabel(followUp.due_at)}`;
}

export default function FollowUpPanel({ conversationId, agents, defaultAgentId, onChanged }: {
  conversationId: string; agents: Agent[]; defaultAgentId?: string | null; onChanged: () => void;
}) {
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const [busyIds, setBusyIds] = useState<Record<string, boolean>>({});
  const versions = useRef<Record<string, number>>({});
  const busy = useRef(new Set<string>());
  const mounted = useRef(true);
  const changed = useRef(onChanged); changed.current = onChanged;
  const refresh = useRef<() => Promise<void>>(async () => {});
  const patch = (id: string, update: Partial<Entry>) => setEntries((all) => ({ ...all, [id]: { ...all[id], ...update } }));
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true; let reading = false; let controller: AbortController | undefined;
    const load = async () => {
      if (reading || busy.current.has(conversationId)) return;
      const version = versions.current[conversationId] ?? 0;
      reading = true; controller = new AbortController();
      const timer = window.setTimeout(() => controller?.abort(), 15000);
      try {
        const response = await fetch(`/whatsapp/conversations/${conversationId}/follow-up`, { headers: headers(), signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error("Não foi possível atualizar o retorno. Tente novamente.");
        const payload = await response.json() as { data: FollowUp | null };
        if (payload.data === undefined) throw new Error("Retorno indisponível. Tente novamente.");
        if (active && !busy.current.has(conversationId) && version === (versions.current[conversationId] ?? 0)) patch(conversationId, { loaded: true, data: payload.data, error: undefined });
      } catch (error) {
        if (active && version === (versions.current[conversationId] ?? 0)) patch(conversationId, { error: error instanceof Error ? error.message : "Falha ao carregar retorno." });
      } finally { reading = false; window.clearTimeout(timer); }
    };
    refresh.current = load; void load();
    const visible = () => { if (document.visibilityState !== "hidden") void load(); };
    const timer = window.setInterval(visible, 15000);
    document.addEventListener("visibilitychange", visible);
    return () => { active = false; controller?.abort(); window.clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [conversationId]);
  const entry = entries[conversationId] ?? {};
  const current = entry.data;
  const draft = entry.draft;
  const saving = busyIds[conversationId] ?? false;
  const start = () => patch(conversationId, { draft: {
    due: followUpDateInput(current?.status === "pending" ? new Date(current.due_at) : new Date(Date.now() + 30 * 60000)),
    note: current?.status === "pending" ? current.note : "",
    agent: current?.status === "pending" ? current.agent_id : defaultAgentId ?? "",
    revision: current?.revision ?? 0,
  }, error: undefined, notice: undefined, conflict: false });
  const setDraft = (values: Partial<Draft>) => { if (draft) patch(conversationId, { draft: { ...draft, ...values } }); };
  const save = async (action: "schedule" | "complete" | "cancel") => {
    const id = conversationId;
    if (busy.current.has(id) || !entry.loaded) return;
    let body: Record<string, unknown> = { action, expected_revision: current?.revision ?? 0 };
    if (action === "schedule") {
      if (!draft) return;
      const due = new Date(`${draft.due}:00-03:00`);
      if (!Number.isFinite(due.getTime()) || due.getTime() <= Date.now() || !draft.note.trim() || !draft.agent) {
        patch(id, { error: "Preencha a nota, o responsável e um horário futuro." }); return;
      }
      body = { ...body, expected_revision: draft.revision, due_at: due.toISOString(), note: draft.note, agent_id: draft.agent };
    }
    versions.current[id] = (versions.current[id] ?? 0) + 1;
    busy.current.add(id); setBusyIds((all) => ({ ...all, [id]: true }));
    patch(id, { error: undefined, notice: undefined });
    const controller = new AbortController(); const timer = window.setTimeout(() => controller.abort(), 15000);
    let conflict = false;
    try {
      const response = await fetch(`/whatsapp/conversations/${id}/follow-up`, {
        method: "PATCH", headers: headers(), body: JSON.stringify(body), signal: controller.signal,
      });
      const payload = await response.json() as { data?: FollowUp; error?: string };
      if (!response.ok || !payload.data) {
        conflict = response.status === 409;
        throw new Error(payload.error || "Não foi possível salvar o retorno. Atualize antes de tentar novamente.");
      }
      if (mounted.current) {
        patch(id, { data: payload.data, draft: undefined, conflict: false,
          notice: action === "schedule" ? "Retorno agendado. O lembrete é interno." : action === "complete" ? "Retorno concluído. A conversa mantém seu status." : "Retorno cancelado." });
        changed.current();
      }
    } catch (error) {
      if (mounted.current) patch(id, { error: error instanceof Error ? error.message : "Falha ao salvar retorno.", conflict });
    } finally {
      window.clearTimeout(timer); busy.current.delete(id);
      if (mounted.current) setBusyIds((all) => ({ ...all, [id]: false }));
    }
  };
  return <section className={`fc-wa-context-section ${styles.panel}`} aria-label="Retorno programado">
    <h3>Retorno programado</h3>
    <p className={styles.hint}>Lembrete interno da equipe. Horários de Fortaleza.</p>
    {entry.error ? <p role="alert">{entry.error}</p> : null}
    {entry.notice ? <p role="status">{entry.notice}</p> : null}
    <button type="button" className="fc-wa-secondary" disabled={saving} onClick={() => void refresh.current()}>Atualizar retorno</button>
    {!entry.loaded ? <p>Carregando retorno...</p> : <>
      {current?.status === "pending" ? <div className={styles.card}>
        <strong>{followUpLabel(current, Date.now())}</strong><span>{current.agent_name || "Responsável cadastrado"}</span>
        <p className={styles.note}>{current.note}</p>
      </div> : <p>{current?.status === "completed" ? "Último retorno concluído." : current?.status === "cancelled" ? "Último retorno cancelado." : "Nenhum retorno programado."}</p>}
      {draft ? <form onSubmit={(event) => { event.preventDefault(); void save("schedule"); }}>
        <fieldset disabled={saving}>
          <div className={styles.actions}><button type="button" onClick={() => setDraft({ due: followUpDateInput(new Date(Date.now() + 30 * 60000)) })}>Em 30 minutos</button>
            <button type="button" onClick={() => setDraft({ due: `${followUpDateInput(new Date(Date.now() + 86400000)).slice(0, 10)}T09:00` })}>Amanhã às 9h</button></div>
          <label>Data e hora do retorno<input type="datetime-local" value={draft.due} required onChange={(event) => setDraft({ due: event.target.value })} /></label>
          <label>Responsável pelo retorno<select value={draft.agent} required onChange={(event) => setDraft({ agent: event.target.value })}>
            <option value="">Selecione um atendente</option>
            {agents.filter((agent) => agent.active).map((agent) => <option key={agent.id} value={agent.id}>{agent.name || agent.email}</option>)}
          </select></label>
          <label>Nota interna do retorno<textarea maxLength={1000} required rows={3} value={draft.note} onChange={(event) => setDraft({ note: event.target.value })} placeholder="Qual é o próximo passo combinado?" /></label>
          {draft.revision !== (current?.revision ?? 0) ? <div role="status"><p>O retorno foi atualizado. Revise os dados acima; sua nota foi preservada.</p>
            <button type="button" onClick={() => setDraft({ revision: current?.revision ?? 0 })}>Usar versão atual e manter nota</button></div> : null}
          <div className={styles.actions}><button type="submit" disabled={draft.revision !== (current?.revision ?? 0)} className="fc-wa-secondary">Salvar retorno</button>
            <button type="button" onClick={() => patch(conversationId, { draft: undefined, conflict: false })}>Descartar edição</button></div>
        </fieldset>
      </form> : <div className={styles.actions}><button type="button" className="fc-wa-secondary" onClick={start} disabled={saving}>{current?.status === "pending" ? "Reagendar retorno" : "Agendar retorno"}</button>
        {current?.status === "pending" ? <><button type="button" disabled={saving} onClick={() => void save("complete")}>Concluir retorno</button>
          <button type="button" disabled={saving} onClick={() => void save("cancel")}>Cancelar retorno</button></> : null}</div>}
    </>}
  </section>;
}
