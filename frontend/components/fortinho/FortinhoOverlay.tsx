"use client";

import FortinhoMascot, { type FortinhoGesture, type FortinhoMood } from "@/components/FortinhoMascot";

interface FortinhoOverlayConfirmState {
  confirmLabel: string;
  cancelLabel: string;
}

interface FortinhoOverlayProps {
  hidden: boolean;
  message: string;
  mood: FortinhoMood;
  gesture: FortinhoGesture;
  confirmState: FortinhoOverlayConfirmState | null;
  stickyNotice: boolean;
  onHide: () => void;
  onShow: () => void;
  onDismiss: () => void;
  onConfirm: () => void;
}

export default function FortinhoOverlay({
  hidden,
  message,
  mood,
  gesture,
  confirmState,
  stickyNotice,
  onHide,
  onShow,
  onDismiss,
  onConfirm,
}: FortinhoOverlayProps) {
  if (hidden) {
    return (
      <button
        type="button"
        onClick={onShow}
        data-fortcordis-overlay-safe="1"
        className="fixed bottom-4 right-4 z-[90] rounded-full border border-rose-300 bg-white px-3 py-2 text-xs font-semibold text-rose-700 shadow-md hover:bg-rose-50"
      >
        Mostrar Fortinho
      </button>
    );
  }

  return (
    <div
      className={`fixed bottom-4 right-4 flex w-[238px] flex-col items-end ${confirmState ? "z-[110]" : "z-[90]"}`}
      data-fortcordis-overlay-safe="1"
    >
      {!confirmState && (
        <button
          type="button"
          onClick={onHide}
          className="mb-2 pointer-events-auto rounded-full border border-rose-300 bg-white px-2 py-1 text-[11px] font-medium text-rose-700 shadow-sm hover:bg-rose-50"
        >
          Ocultar Fortinho
        </button>
      )}

      <div className="pointer-events-auto">
        <FortinhoMascot
          mood={mood}
          gesture={gesture}
          message={message}
          className="origin-bottom-right scale-[0.84] md:scale-100"
        />
      </div>

      {confirmState && (
        <div className="pointer-events-auto mt-2 w-full rounded-2xl border border-slate-200 bg-white p-3 shadow-lg">
          <p className="mb-2 text-xs text-slate-600">Como devemos seguir?</p>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-xl border border-slate-300 px-2 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              {confirmState.cancelLabel}
            </button>
            <button
              type="button"
              onClick={onConfirm}
              className="rounded-xl border border-rose-600 bg-rose-600 px-2 py-2 text-xs font-semibold text-white hover:bg-rose-700"
            >
              {confirmState.confirmLabel}
            </button>
          </div>
        </div>
      )}

      {!confirmState && stickyNotice && (
        <button
          type="button"
          onClick={onDismiss}
          className="pointer-events-auto mt-2 w-full rounded-xl border border-rose-300 bg-white px-3 py-2 text-xs font-semibold text-rose-700 shadow-sm hover:bg-rose-50"
        >
          Entendi
        </button>
      )}
    </div>
  );
}
