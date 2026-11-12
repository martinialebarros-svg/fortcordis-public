"use client";

import type { EchoEditorDraftController } from "../hooks/useEchoEditorDraft";

type DraftStatusProps = Pick<EchoEditorDraftController,
  "status" | "lastSavedAt" | "error" | "pendingImages" | "recovery" | "resumeRecovered" | "continueFresh" | "retry">;

export default function EchoDraftStatus({ draft, existing = false, allowContinueFresh = true }: {
  draft: DraftStatusProps; existing?: boolean; allowContinueFresh?: boolean;
}) {
  if (draft.status === "disabled" || draft.status === "closed") return null;
  const savedAt = draft.lastSavedAt && Number.isFinite(Date.parse(draft.lastSavedAt))
    ? new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: "America/Fortaleza" })
      .format(new Date(draft.lastSavedAt)) : null;
  const label = {
    loading: "Consultando rascunho…",
    recovery: "Há um rascunho deste exame para recuperar.",
    idle: "O rascunho será salvo automaticamente quando você alterar o preenchimento.",
    pending: "Alterações aguardando salvamento do rascunho…",
    saving: "Salvando rascunho…",
    saved: savedAt ? `Rascunho salvo às ${savedAt}.` : "Rascunho salvo.",
    error: "O rascunho precisa de atenção.",
    conflict: "O rascunho mudou em outra sessão.",
    paused: existing ? "Rascunho salvo. Preparando atualização…" : "Rascunho salvo. Preparando emissão…",
  }[draft.status];
  return <section aria-label="Rascunho do ecocardiograma"
    className={`rounded-lg border px-4 py-3 text-sm ${["error", "conflict", "recovery"].includes(draft.status)
      ? "border-amber-200 bg-amber-50 text-amber-950" : "border-teal-100 bg-teal-50/60 text-teal-950"}`}>
    <p role="status" aria-live="polite">{label}</p>
    {draft.error && <p className="mt-1">{draft.error}</p>}
    {draft.status === "recovery" && <>
      <p className="mt-1">{draft.recovery?.snapshot.submission
        ? "Há uma tentativa de salvamento registrada. Retome este rascunho para conferir o resultado antes de continuar."
        : `Escolha como continuar antes de ${existing ? "atualizar" : "emitir"}. O laudo oficial permanece inalterado.`}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className="rounded-md bg-teal-700 px-3 py-2 font-medium text-white"
          onClick={() => { void draft.resumeRecovered().catch(() => {}); }}>Retomar rascunho</button>
        {allowContinueFresh && !draft.recovery?.snapshot.submission && <button type="button" className="rounded-md border border-amber-300 bg-white px-3 py-2"
          onClick={draft.continueFresh}>Continuar com preenchimento atual</button>}
      </div>
    </>}
    {draft.status === "error" && <button type="button"
      className="mt-2 rounded-md border border-amber-300 bg-white px-3 py-2"
      onClick={() => { void draft.retry().catch(() => {}); }}>Tentar novamente</button>}
    {draft.pendingImages > 0 && <p className="mt-1 text-amber-900">
      {draft.pendingImages === 1 ? "1 imagem precisa de envio ou reenvio." : `${draft.pendingImages} imagens precisam de envio ou reenvio.`}
      {" "}A cópia do rascunho conserva a identificação; arquivos ainda não enviados precisam ser selecionados novamente após uma recarga.
    </p>}
  </section>;
}
