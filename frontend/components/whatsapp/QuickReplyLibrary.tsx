"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import styles from "./QuickReplyLibrary.module.css";

export interface QuickReply {
  id: string;
  title: string;
  body: string;
  category: string;
  shortcut: string;
  active: boolean;
  created_at: string;
  updated_at: string;
}

interface QuickReplyLibraryProps {
  onInsert: (body: string) => void;
  disabled: boolean;
  shortcutQuery?: string;
  userId?: string;
}

interface EditFields { title: string; body: string; category: string; shortcut: string }
const EMPTY_FIELDS: EditFields = { title: "", body: "", category: "", shortcut: "" };

function normalize(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function authHeaders(): Record<string, string> {
  const token = window.localStorage.getItem("token");
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

function asFields(reply: QuickReply): EditFields {
  return { title: reply.title, body: reply.body, category: reply.category, shortcut: reply.shortcut };
}

export default function QuickReplyLibrary({ onInsert, disabled, shortcutQuery, userId }: QuickReplyLibraryProps) {
  const [replies, setReplies] = useState<QuickReply[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [favorites, setFavorites] = useState<{ userId?: string; ids: string[] }>({ ids: [] });
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const favoriteIds = useMemo(() => new Set(favorites.userId === userId ? favorites.ids : []), [favorites, userId]);
  useEffect(() => {
    let ids: string[] = [];
    try {
      const stored = userId ? JSON.parse(window.localStorage.getItem(`whatsapp-quick-reply-favorites:${userId}`) || "[]") : [];
      if (Array.isArray(stored)) ids = stored.filter((id): id is string => typeof id === "string" && /^[1-9]\d*$/.test(id)).slice(0, 500);
    } catch { /* Preferências indisponíveis não bloqueiam a biblioteca. */ }
    setFavorites({ userId, ids }); setOnlyFavorites(false);
  }, [userId]);
  const toggleFavorite = (id: string) => {
    if (!userId) return;
    const next = new Set(favoriteIds);
    if (next.has(id)) next.delete(id); else next.add(id);
    const ids = [...next].slice(0, 500);
    setFavorites({ userId, ids });
    try { window.localStorage.setItem(`whatsapp-quick-reply-favorites:${userId}`, JSON.stringify(ids)); }
    catch { /* Mantém os favoritos desta sessão quando storage está indisponível. */ }
  };
  const [managing, setManaging] = useState(false);
  const [editing, setEditing] = useState<QuickReply | null>(null);
  const [fields, setFields] = useState<EditFields>(EMPTY_FIELDS);
  const [saving, setSaving] = useState(false);
  const [staleReply, setStaleReply] = useState<QuickReply | null>(null);
  const mountedRef = useRef(false);
  const readRef = useRef<AbortController | null>(null);
  const readVersionRef = useRef(0);
  const savingRef = useRef(false);

  const loadReplies = useCallback(async () => {
    const version = ++readVersionRef.current;
    readRef.current?.abort();
    const controller = new AbortController();
    readRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    setLoading(true);
    try {
      const response = await fetch("/whatsapp/quick-replies", {
        cache: "no-store", headers: authHeaders(), signal: controller.signal,
      });
      if (!response.ok) throw new Error("Não foi possível carregar as respostas rápidas. Tente atualizar a biblioteca.");
      const payload = await response.json() as { data: QuickReply[] };
      if (!Array.isArray(payload.data)) throw new Error("A biblioteca retornou uma resposta inválida.");
      if (mountedRef.current && version === readVersionRef.current) {
        setReplies(payload.data); setError(null);
      }
    } catch (failure) {
      if (mountedRef.current && version === readVersionRef.current) {
        setError(failure instanceof Error && failure.name !== "AbortError" ? failure.message :
          "A biblioteca demorou para responder. Tente atualizar novamente.");
      }
    } finally {
      window.clearTimeout(timeout);
      if (mountedRef.current && version === readVersionRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void loadReplies();
    return () => { mountedRef.current = false; readVersionRef.current += 1; readRef.current?.abort(); };
  }, [loadReplies]);

  const activeReplies = useMemo(() => replies.filter((reply) => reply.active), [replies]);
  const categories = useMemo(() => [...new Set(activeReplies.map((reply) => reply.category).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "pt-BR")), [activeReplies]);
  const visibleReplies = useMemo(() => activeReplies.filter((reply) => {
    if (shortcutQuery !== undefined) return reply.shortcut.startsWith(shortcutQuery.toLowerCase().replace(/^\//, ""));
    if (onlyFavorites && !favoriteIds.has(reply.id)) return false;
    if (category && reply.category !== category) return false;
    const query = normalize(search.trim().replace(/^\//, ""));
    return !query || normalize([reply.title, reply.shortcut, reply.category, reply.body].join(" ")).includes(query);
  }), [activeReplies, category, search, shortcutQuery, onlyFavorites, favoriteIds]);

  const beginEdit = (reply: QuickReply | null) => {
    setEditing(reply); setFields(reply ? asFields(reply) : EMPTY_FIELDS);
    setStaleReply(null); setError(null); setNotice(null);
  };

  const save = async (target?: QuickReply) => {
    if (savingRef.current) return;
    const current = target || editing;
    const body = target ? { active: !target.active } : {
      title: fields.title.trim(), body: fields.body.trim(), category: fields.category.trim(), shortcut: fields.shortcut.trim().toLowerCase(),
    };
    if (!target) {
      if (!fields.title.trim() || fields.title.trim().length > 100 || !fields.body.trim() || fields.body.trim().length > 4096 || fields.category.trim().length > 60) {
        setError("Preencha título e texto, respeitando os limites indicados."); return;
      }
      if (!/^[a-z0-9_-]{2,32}$/.test(fields.shortcut.trim().toLowerCase())) {
        setError("O atalho deve ter de 2 a 32 letras, números, hífen ou sublinhado, sem a barra."); return;
      }
    }
    savingRef.current = true; setSaving(true); setError(null); setNotice(null); setStaleReply(null);
    // An older list response must not erase the newly saved item.
    readVersionRef.current += 1; readRef.current?.abort(); setLoading(false);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await fetch(`/whatsapp/quick-replies${current ? `/${current.id}` : ""}`, {
        method: current ? "PATCH" : "POST", headers: authHeaders(), signal: controller.signal,
        body: JSON.stringify({ ...body, ...(current ? { expected_updated_at: current.updated_at } : {}) }),
      });
      const payload = await response.json() as { data?: QuickReply; error?: string; code?: string };
      if (!mountedRef.current) return;
      if (!response.ok || !payload.data) {
        if (response.status === 409 && payload.code === "QUICK_REPLY_STALE" && payload.data) {
          setReplies((items) => items.map((item) => item.id === payload.data!.id ? payload.data! : item));
          if (!target) setStaleReply(payload.data);
        }
        setError(payload.error || (response.status === 403 ? "Seu perfil não permite alterar a biblioteca." : "Não foi possível salvar a resposta rápida."));
        return;
      }
      const updated = payload.data;
      setReplies((items) => items.some((item) => item.id === updated.id)
        ? items.map((item) => item.id === updated.id ? updated : item) : [...items, updated]);
      if (!target) { setEditing(null); setFields(EMPTY_FIELDS); }
      else if (editing?.id === updated.id) setEditing(updated);
      setNotice(target ? updated.active ? "Resposta reativada." : "Resposta desativada e preservada no cadastro." : "Resposta salva para a equipe.");
    } catch {
      if (mountedRef.current) setError("Não foi possível confirmar a alteração. O texto foi mantido; atualize a biblioteca antes de tentar novamente.");
    } finally {
      window.clearTimeout(timeout); savingRef.current = false;
      if (mountedRef.current) setSaving(false);
    }
  };

  return <section className={styles.library} aria-label="Biblioteca de respostas rápidas">
    <div className={styles.heading}>
      <strong>Respostas rápidas</strong>
      <button type="button" onClick={() => void loadReplies()} disabled={loading || saving}>Atualizar biblioteca</button>
      <button type="button" onClick={() => setManaging((current) => !current)} disabled={saving} aria-expanded={managing}>
        {managing ? "Fechar gerenciamento" : "Gerenciar respostas"}
      </button>
    </div>
    <p className={styles.hint}>Insira um texto para revisar antes de enviar. Digite /atalho na mensagem para encontrar uma resposta.</p>
    {error ? <div className={styles.error} role="alert">{error}</div> : null}
    {notice ? <p className={styles.notice} role="status">{notice}</p> : null}
    {shortcutQuery === undefined ? <div className={styles.filters}>
      <input aria-label="Buscar resposta rápida" placeholder="Título, atalho ou conteúdo" value={search} onChange={(event) => setSearch(event.target.value)} />
      <select aria-label="Categoria da resposta rápida" value={category} onChange={(event) => setCategory(event.target.value)}>
        <option value="">Todas as categorias</option>{categories.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
    </div> : <p className={styles.shortcutHint}>Respostas para /{shortcutQuery.replace(/^\//, "")}</p>}
    {userId && shortcutQuery === undefined ? <label className={styles.favoritesFilter}><input type="checkbox" checked={onlyFavorites} onChange={(event) => setOnlyFavorites(event.target.checked)} />Somente favoritas</label> : null}
    <div className={styles.results} aria-busy={loading}>
      {loading && replies.length === 0 ? <p>Carregando respostas rápidas...</p> : visibleReplies.length === 0 ?
        <p>{activeReplies.length ? "Nenhuma resposta corresponde à busca." : "Nenhuma resposta ativa. Cadastre uma em Gerenciar respostas."}</p> :
        visibleReplies.map((reply) => <div key={reply.id} className={styles.replyCard}><button type="button" className={styles.reply}
          onClick={() => onInsert(reply.body)} disabled={disabled} title={reply.body} aria-label={`Inserir resposta ${reply.title}`}>
          <span><strong>{reply.title}</strong><code>/{reply.shortcut}</code></span>
          {reply.category ? <small>{reply.category}</small> : null}<span className={styles.preview}>{reply.body}</span>
        </button>{userId ? <button type="button" className={styles.favorite} aria-pressed={favoriteIds.has(reply.id)}
          aria-label={`${favoriteIds.has(reply.id) ? "Remover dos favoritos" : "Favoritar"} resposta ${reply.title}`} onClick={() => toggleFavorite(reply.id)}>
          {favoriteIds.has(reply.id) ? "★" : "☆"}</button> : null}</div>)}
    </div>
    {managing ? <section className={styles.manager} aria-label="Gerenciar biblioteca de respostas rápidas">
      <div className={styles.editorHeading}><h3>{editing ? "Editar resposta rápida" : "Nova resposta rápida"}</h3>
        {editing ? <button type="button" onClick={() => beginEdit(null)} disabled={saving}>Cancelar edição</button> : null}</div>
      <div className={styles.editor}>
        <label>Título<input value={fields.title} maxLength={100} disabled={saving} onChange={(event) => setFields({ ...fields, title: event.target.value })} /></label>
        <label>Atalho sem barra<input value={fields.shortcut} maxLength={32} disabled={saving} placeholder="ex.: preparo" onChange={(event) => setFields({ ...fields, shortcut: event.target.value.toLowerCase() })} /></label>
        <label>Categoria<input value={fields.category} maxLength={60} disabled={saving} placeholder="ex.: Agenda" onChange={(event) => setFields({ ...fields, category: event.target.value })} /></label>
        <label className={styles.bodyField}>Texto da resposta<textarea value={fields.body} maxLength={4096} rows={4} disabled={saving} onChange={(event) => setFields({ ...fields, body: event.target.value })} /><small>{fields.body.length}/4096 caracteres</small></label>
      </div>
      <p className={styles.hint}>Atalhos são únicos, inclusive para respostas inativas. Desativar preserva o cadastro e permite reativar depois.</p>
      {staleReply ? <button type="button" onClick={() => beginEdit(staleReply)} disabled={saving}>Carregar versão da equipe</button> : null}
      <button type="button" className={styles.primary} onClick={() => void save()} disabled={saving}>{saving ? "Salvando..." : "Salvar resposta"}</button>
      <ul className={styles.manageList}>{replies.map((reply) => <li key={reply.id}>
        <span><strong>{reply.title}</strong><small>/{reply.shortcut} · {reply.active ? "Ativa" : "Inativa"}</small></span>
        <button type="button" onClick={() => beginEdit(reply)} disabled={saving} aria-label={`Editar resposta ${reply.title}`}>Editar</button>
        <button type="button" onClick={() => void save(reply)} disabled={saving} aria-label={`${reply.active ? "Desativar" : "Reativar"} resposta ${reply.title}`}>
          {reply.active ? "Desativar" : "Reativar"}</button>
      </li>)}</ul>
    </section> : null}
  </section>;
}
