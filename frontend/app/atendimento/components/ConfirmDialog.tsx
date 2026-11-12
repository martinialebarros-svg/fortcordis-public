"use client";

import { AlertTriangle, Trash2, X } from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type ConfirmDialogProps = LooseAtendimentoComponentProps;

export default function ConfirmDialog(props: ConfirmDialogProps) {
  const {
    aberto,
    titulo,
    descricao,
    variante = "default",
    confirmLabel = "Confirmar",
    cancelLabel = "Cancelar",
    onConfirm,
    onCancel,
  } = props;

  if (!aberto) {
    return null;
  }

  const destrutivo = variante === "destructive";

  return (
    <div
      data-fortcordis-overlay-safe="1"
      className="fixed inset-0 z-[130] flex items-center justify-center bg-slate-950/70 px-4 py-6"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          onCancel();
        }
      }}
    >
      <button
        type="button"
        aria-label={cancelLabel}
        onClick={onCancel}
        className="absolute inset-0 cursor-default"
      />
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-titulo"
        aria-describedby="confirm-dialog-descricao"
        data-fortcordis-overlay-safe="1"
        className="relative z-[131] w-full max-w-md rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl"
      >
        <div className="flex items-start gap-3">
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
              destrutivo ? "bg-red-100 text-red-600" : "bg-amber-100 text-amber-600"
            }`}
          >
            {destrutivo ? <Trash2 className="h-5 w-5" /> : <AlertTriangle className="h-5 w-5" />}
          </span>
          <div className="min-w-0 flex-1">
            <h3 id="confirm-dialog-titulo" className="text-base font-semibold text-slate-900">
              {titulo}
            </h3>
            <p id="confirm-dialog-descricao" className="mt-1 text-sm text-slate-600">
              {descricao}
            </p>
          </div>
          <button
            type="button"
            aria-label={cancelLabel}
            onClick={onCancel}
            className="shrink-0 rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            autoFocus={destrutivo}
            onClick={onCancel}
            className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            autoFocus={!destrutivo}
            onClick={onConfirm}
            className={`rounded-xl px-4 py-2 text-sm font-medium text-white ${
              destrutivo ? "bg-red-600 hover:bg-red-700" : "bg-slate-900 hover:bg-slate-800"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
