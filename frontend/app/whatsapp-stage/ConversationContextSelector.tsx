"use client";

import { useEffect, useRef, useState } from "react";
import type { WhatsAppContextSelectionPayload, WhatsAppSelectableContext } from "@/lib/whatsapp-contexto";

interface Props {
  context: WhatsAppSelectableContext;
  onSave: (payload: WhatsAppContextSelectionPayload) => Promise<void>;
  onReload: () => void;
}

export default function ConversationContextSelector({ context, onSave, onReload }: Props) {
  const selection = context.selecao;
  const savedChoice = selection?.valida && selection.match_type && selection.cadastro_id != null
    ? `${selection.match_type}:${selection.cadastro_id}` : "";
  const [choice, setChoice] = useState(savedChoice);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(true);
  const busy = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setChoice(savedChoice); }, [savedChoice, selection?.versao]);

  const candidates = [
    ...(context.candidatos?.clinicas ?? []).map((item) => ({ ...item, type: "clinica" as const, label: "Clínica" })),
    ...(context.candidatos?.tutores ?? []).map((item) => ({ ...item, type: "tutor" as const, label: "Tutor" })),
  ];
  const selectedCandidate = candidates.find((item) => `${item.type}:${item.id}` === savedChoice);
  const hasSelection = Boolean(selection?.match_type && selection.cadastro_id != null);
  if (!context.candidatos) return null;
  if (!candidates.length && !hasSelection) return null;

  const save = async (clear = false) => {
    if (busy.current) return;
    const candidate = candidates.find((item) => `${item.type}:${item.id}` === choice);
    if (!clear && !candidate) return;
    busy.current = true; setSaving(true); setError(null); setNotice(null);
    try {
      await onSave({
        match_type: clear ? null : candidate!.type,
        cadastro_id: clear ? null : candidate!.id,
        versao_esperada: selection?.versao ?? 0,
      });
      if (mounted.current) setNotice(clear
        ? "Escolha removida. O bot voltará a verificar os vínculos pelo telefone."
        : "Cadastro escolhido para esta conversa. A escolha passa a valer na próxima mensagem recebida. Confira o modo e a pausa do bot antes de testar.");
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : "Não foi possível salvar a escolha. Atualize os vínculos e tente novamente.");
    } finally {
      busy.current = false;
      if (mounted.current) setSaving(false);
    }
  };

  return <div className="fc-wa-context-section" aria-label="Cadastro usado pelo bot">
    {selectedCandidate ? <p className="fc-wa-bot-state-note">Escolha atual: <strong>{selectedCandidate.label}: {selectedCandidate.nome}</strong>.</p> : null}
    <label className="fc-wa-field"><span>Cadastro para esta conversa</span>
      <select value={choice} disabled={saving || !candidates.length} onChange={(event) => {
        setChoice(event.target.value); setError(null); setNotice(null);
      }}>
        <option value="">Selecione o cadastro</option>
        {candidates.map((item) => <option key={`${item.type}:${item.id}`} value={`${item.type}:${item.id}`}>{item.label}: {item.nome} (#{item.id})</option>)}
      </select>
    </label>
    <p className="fc-wa-bot-state-note">Escolha qual cadastro o bot deve consultar neste atendimento. Os cadastros e seus telefones serão preservados.</p>
    <div className="fc-wa-owner-actions">
      <button type="button" className="fc-wa-secondary" disabled={saving || !choice || choice === savedChoice} onClick={() => void save()}>{saving ? "Salvando escolha..." : "Salvar escolha"}</button>
      {hasSelection ? <button type="button" className="fc-wa-ghost-danger" disabled={saving} onClick={() => void save(true)}>Remover escolha</button> : null}
    </div>
    {error ? <div className="fc-wa-domain-state-error" role="alert"><p>{error}</p><button type="button" className="fc-wa-secondary" disabled={saving} onClick={onReload}>Atualizar vínculos</button></div> : null}
    {notice ? <p className="fc-wa-bot-state-note" role="status">{notice}</p> : null}
  </div>;
}
