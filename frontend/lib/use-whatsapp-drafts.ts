"use client";

import { useCallback, useState } from "react";

export interface WhatsAppDraftSnapshot {
  readonly body: string;
  readonly file: File | null;
}

const EMPTY_DRAFT: WhatsAppDraftSnapshot = { body: "", file: null };

/** Rascunhos privados vivem somente na memória desta montagem da central. */
export function useWhatsAppDrafts(conversationId: string | null) {
  const [drafts, setDrafts] = useState<Map<string, WhatsAppDraftSnapshot>>(() => new Map());
  const draftSnapshot = (conversationId && drafts.get(conversationId)) || EMPTY_DRAFT;

  const setBody = useCallback((body: string): void => {
    if (!conversationId) return;
    setDrafts((current) => {
      const previous = current.get(conversationId) || EMPTY_DRAFT;
      if (previous.body === body) return current;
      return new Map(current).set(conversationId, { ...previous, body });
    });
  }, [conversationId]);

  const setFile = useCallback((file: File | null): void => {
    if (!conversationId) return;
    setDrafts((current) => {
      const previous = current.get(conversationId) || EMPTY_DRAFT;
      if (previous.file === file) return current;
      return new Map(current).set(conversationId, { ...previous, file });
    });
  }, [conversationId]);

  const clearDraftIfUnchanged = useCallback((id: string, snapshot: WhatsAppDraftSnapshot): void => {
    setDrafts((current) => {
      // Uma resposta atrasada de envio só pode apagar exatamente o rascunho enviado.
      if (current.get(id) !== snapshot) return current;
      const next = new Map(current);
      next.delete(id);
      return next;
    });
  }, []);

  const clearDraft = useCallback((id: string | null = conversationId): void => {
    if (!id) return;
    setDrafts((current) => {
      if (!current.has(id)) return current;
      const next = new Map(current);
      next.delete(id);
      return next;
    });
  }, [conversationId]);

  const hasDraft = useCallback((id: string): boolean => {
    const draft = drafts.get(id);
    return Boolean(draft && (draft.body.trim() || draft.file));
  }, [drafts]);

  return {
    body: draftSnapshot.body,
    file: draftSnapshot.file,
    draftSnapshot,
    setBody,
    setFile,
    clearDraftIfUnchanged,
    clearDraft,
    hasDraft,
  };
}
