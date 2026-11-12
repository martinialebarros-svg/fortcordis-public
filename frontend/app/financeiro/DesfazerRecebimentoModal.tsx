"use client";

import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { Loader2, Undo2 } from "lucide-react";

interface DesfazerRecebimentoModalProps {
  numeroOS: string;
  paciente: string;
  clinica: string;
  valor: string;
  processando: boolean;
  erro: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function DesfazerRecebimentoModal({
  numeroOS,
  paciente,
  clinica,
  valor,
  processando,
  erro,
  onCancel,
  onConfirm,
}: DesfazerRecebimentoModalProps) {
  const tituloId = useId();
  const descricaoId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelarRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const focoAnterior = document.activeElement;
    const overflowAnterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    cancelarRef.current?.focus();
    return () => {
      document.body.style.overflow = overflowAnterior;
      if (focoAnterior instanceof HTMLElement && focoAnterior.isConnected) focoAnterior.focus();
    };
  }, []);

  useEffect(() => {
    if (processando) dialogRef.current?.focus();
    else cancelarRef.current?.focus();
  }, [processando]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (!processando) onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const botoes = dialogRef.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])");
    if (!botoes?.length) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const primeiro = botoes[0];
    const ultimo = botoes[botoes.length - 1];
    if (event.shiftKey && (document.activeElement === primeiro || document.activeElement === dialogRef.current)) {
      event.preventDefault();
      ultimo.focus();
    } else if (!event.shiftKey && (document.activeElement === ultimo || document.activeElement === dialogRef.current)) {
      event.preventDefault();
      primeiro.focus();
    }
  };

  return (
    <div
      data-fortcordis-overlay-safe="1"
      className="fixed inset-0 z-[130] flex items-center justify-center overflow-y-auto bg-slate-950/60 px-4 py-6"
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={tituloId}
        aria-describedby={descricaoId}
        aria-busy={processando}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
      >
        <div className="mb-4 flex items-center gap-3">
          <span className="rounded-xl bg-amber-100 p-2 text-amber-700">
            <Undo2 className="h-5 w-5" aria-hidden="true" />
          </span>
          <h2 id={tituloId} className="text-lg font-semibold text-slate-900">Desfazer recebimento?</h2>
        </div>
        <dl className="space-y-2 rounded-xl bg-slate-50 p-4 text-sm">
          <div className="flex justify-between gap-4"><dt className="text-slate-600">OS</dt><dd className="break-all text-right font-medium text-slate-900">{numeroOS}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-slate-600">Paciente</dt><dd className="break-words text-right font-medium text-slate-900">{paciente || "Não informado"}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-slate-600">Clínica</dt><dd className="break-words text-right font-medium text-slate-900">{clinica || "Não informada"}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-slate-600">Valor da OS</dt><dd className="font-semibold text-slate-900">{valor}</dd></div>
        </dl>
        <p id={descricaoId} className="mt-4 text-sm text-slate-600">
          O recebimento será revertido e a OS voltará para Pendente.
        </p>
        {erro && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">{erro}</p>}
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            ref={cancelarRef}
            type="button"
            onClick={onCancel}
            disabled={processando}
            className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-wait disabled:opacity-50"
          >Cancelar</button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={processando}
            className="flex items-center gap-2 rounded-xl bg-amber-700 px-4 py-2 text-sm font-medium text-white hover:bg-amber-800 disabled:cursor-wait disabled:opacity-50"
          >
            {processando && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {processando ? "Desfazendo..." : "Desfazer recebimento"}
          </button>
        </div>
      </div>
    </div>
  );
}
