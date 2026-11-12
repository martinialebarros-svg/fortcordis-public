import type { EchoEditorDraftSnapshot } from "./echo-editor-draft";
import type { EchoReviewTarget } from "./echo-final-review";

/** The preview and the explicit update use the same ordered image selection. */
export function echoEditorImageSelection(snapshot: EchoEditorDraftSnapshot) {
  const persisted = snapshot.existing?.imagensPersistidas ?? [];
  return {
    persistidas: persisted.map((image, index) => ({
      id: image.serverId, ordem: index, incluir_no_pdf: image.incluirNoPdf !== false, descricao: image.descricao,
    })),
    removidas_ids: snapshot.existing?.imagensRemovidas ?? [],
    temp_session_id: snapshot.sessionId,
    temp_config: snapshot.imagens.map((image, index) => ({
      id: image.tempId,
      ordem: snapshot.editor === "existing-echo" ? persisted.length + index : image.ordem,
      incluir_no_pdf: image.incluirNoPdf !== false,
      descricao: image.descricao,
    })),
  };
}

/** Merely changing the visible tab does not alter the PDF. Everything else is
 * kept so an old preview cannot remain current after a protocol/image edit. */
export function echoPreviewSnapshotKey(snapshot: EchoEditorDraftSnapshot): string {
  return JSON.stringify({ ...snapshot, aba: undefined });
}

export function navigateEchoFinalReview(
  target: EchoReviewTarget,
  setTab: (tab: "paciente" | "medidas" | "qualitativa" | "imagens" | "referencias") => void,
) {
  const tab = target === "patient" ? "paciente" : target === "references" ? "referencias"
    : target === "qualitative" ? "qualitativa" : target === "images" ? "imagens" : "medidas";
  setTab(tab);
  // Wait for React to mount the requested tab. Targets are fixed local enum
  // values, never selectors provided by imported clinical text.
  requestAnimationFrame(() => {
    const anchor = document.querySelector<HTMLElement>(`[data-echo-review-target="${target}"]`);
    if (!anchor) return;
    anchor.scrollIntoView?.({ block: "center", behavior: "smooth" });
    let field = anchor.matches("input, select, textarea") ? anchor
      : anchor.querySelector<HTMLElement>("input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])");
    if (!field && target === "diastolic") {
      // The diastolic heading precedes the feline review selector or the first
      // Doppler field. Focus that control, retaining ordinary keyboard order.
      let sibling = anchor.nextElementSibling;
      while (sibling && !/^H[1-6]$/.test(sibling.tagName)) {
        field = sibling.querySelector<HTMLElement>("input:not([disabled]), select:not([disabled]), textarea:not([disabled])");
        if (field) break;
        sibling = sibling.nextElementSibling;
      }
    }
    if (field) field.focus({ preventScroll: true });
    else { anchor.tabIndex = -1; anchor.focus({ preventScroll: true }); }
  });
}
