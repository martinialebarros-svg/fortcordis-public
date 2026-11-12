"use client";

import { BookmarkPlus, ClipboardList, Eraser, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import type { ClinicalFieldConfig } from "@/lib/atendimento-clinical-notes";

interface ClinicalFieldCardProps {
  config: ClinicalFieldConfig;
  value: string;
  onChange: (value: string) => void;
  onInsertPhrase: (text: string) => void;
  onInsertScaffold?: (text: string) => void;
  onClear: () => void;
  onSaveAsPhrase?: (titulo: string, texto: string) => Promise<boolean> | boolean;
  savingPhrase?: boolean;
  textareaRef?: (node: HTMLTextAreaElement | null) => void;
  onTextareaKeyDown?: (event: ReactKeyboardEvent<HTMLTextAreaElement>) => void;
  className?: string;
}

const toneClasses: Record<ClinicalFieldConfig["tone"], { shell: string; badge: string; icon: string }> = {
  teal: {
    shell: "border-teal-200 bg-teal-50/60",
    badge: "bg-teal-100 text-teal-700",
    icon: "bg-teal-100 text-teal-700",
  },
  sky: {
    shell: "border-sky-200 bg-sky-50/60",
    badge: "bg-sky-100 text-sky-700",
    icon: "bg-sky-100 text-sky-700",
  },
  rose: {
    shell: "border-rose-200 bg-rose-50/60",
    badge: "bg-rose-100 text-rose-700",
    icon: "bg-rose-100 text-rose-700",
  },
  violet: {
    shell: "border-violet-200 bg-violet-50/60",
    badge: "bg-violet-100 text-violet-700",
    icon: "bg-violet-100 text-violet-700",
  },
  amber: {
    shell: "border-amber-200 bg-amber-50/70",
    badge: "bg-amber-100 text-amber-700",
    icon: "bg-amber-100 text-amber-700",
  },
  slate: {
    shell: "border-slate-200 bg-slate-50/80",
    badge: "bg-slate-100 text-slate-700",
    icon: "bg-slate-100 text-slate-700",
  },
};

export default function ClinicalFieldCard({
  config,
  value,
  onChange,
  onInsertPhrase,
  onInsertScaffold,
  onClear,
  onSaveAsPhrase,
  savingPhrase = false,
  textareaRef,
  onTextareaKeyDown,
  className = "",
}: ClinicalFieldCardProps) {
  const tone = toneClasses[config.tone];
  const hasValue = value.trim().length > 0;
  const lineCount = value.trim() ? value.split("\n").length : 0;
  const titleId = `clinical-field-title-${config.key}`;

  const [showQuickSaveForm, setShowQuickSaveForm] = useState(false);
  const [quickTitulo, setQuickTitulo] = useState("");
  const [quickTexto, setQuickTexto] = useState("");

  const openQuickSaveForm = () => {
    setQuickTitulo("");
    setQuickTexto(value.trim());
    setShowQuickSaveForm(true);
  };

  const closeQuickSaveForm = () => {
    setShowQuickSaveForm(false);
    setQuickTitulo("");
    setQuickTexto("");
  };

  const handleQuickSave = async () => {
    if (!onSaveAsPhrase) return;
    const saved = await onSaveAsPhrase(quickTitulo, quickTexto);
    if (saved) closeQuickSaveForm();
  };

  return (
    <article className={`overflow-hidden rounded-[24px] border p-4 shadow-sm ${tone.shell} ${className}`.trim()}>
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className={`rounded-2xl p-2 ${tone.icon}`}>
              <ClipboardList className="h-4 w-4" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 id={titleId} className="text-sm font-semibold text-slate-900">{config.title}</h3>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${tone.badge}`}>
                  {hasValue ? `${lineCount} linha(s)` : "Em aberto"}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-600">{config.subtitle}</p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {onSaveAsPhrase ? (
              <button
                type="button"
                onClick={() => (showQuickSaveForm ? closeQuickSaveForm() : openQuickSaveForm())}
                disabled={!hasValue}
                className="rounded-xl border border-white/60 bg-white/80 px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="inline-flex items-center gap-2">
                  <BookmarkPlus className="h-3.5 w-3.5" />
                  Salvar como frase
                </span>
              </button>
            ) : null}

            <button
              type="button"
              onClick={onClear}
              className="rounded-xl border border-white/60 bg-white/80 px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-white"
            >
              <span className="inline-flex items-center gap-2">
                <Eraser className="h-3.5 w-3.5" />
                Limpar
              </span>
            </button>
          </div>
        </div>

        {showQuickSaveForm ? (
          <div className="space-y-2 rounded-2xl border border-white/70 bg-white/90 p-3">
            <p className="text-xs text-slate-600">
              Salva este texto como atalho reutilizavel em <strong>{config.title}</strong>.
            </p>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-[0.2em] text-slate-500">
                Titulo do atalho
              </label>
              <input
                value={quickTitulo}
                onChange={(event) => setQuickTitulo(event.target.value)}
                placeholder="Ex.: Sopro apical"
                autoFocus
                className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-300 focus:ring-2 focus:ring-slate-200"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-[0.2em] text-slate-500">
                Texto do atalho
              </label>
              <textarea
                value={quickTexto}
                onChange={(event) => setQuickTexto(event.target.value)}
                rows={4}
                className="w-full resize-y rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-300 focus:ring-2 focus:ring-slate-200"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleQuickSave}
                disabled={savingPhrase || !quickTitulo.trim() || !quickTexto.trim()}
                className="rounded-xl bg-teal-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {savingPhrase ? "Salvando..." : "Salvar atalho"}
              </button>
              <button
                type="button"
                onClick={closeQuickSaveForm}
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-slate-100"
              >
                Cancelar
              </button>
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {config.scaffold ? (
            <button
              type="button"
              onClick={() => onInsertScaffold?.(config.scaffold?.text || "")}
              className="max-w-full rounded-xl bg-white px-3 py-2 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-100"
            >
              <span className="inline-flex max-w-full items-center gap-2">
                <Wand2 className="h-3.5 w-3.5" />
                <span className="truncate">{config.scaffold.label}</span>
              </span>
            </button>
          ) : null}

          {config.quickPhrases.map((phrase) => (
            <button
              key={`${config.key}-${phrase.label}`}
              type="button"
              onClick={() => onInsertPhrase(phrase.text)}
              className="max-w-full rounded-xl border border-white/70 bg-white/80 px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-white"
            >
              <span className="inline-flex max-w-full items-center gap-2">
                <Sparkles className="h-3.5 w-3.5" />
                <span className="truncate">{phrase.label}</span>
              </span>
            </button>
          ))}
        </div>

        <textarea
          ref={textareaRef}
          aria-labelledby={titleId}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onTextareaKeyDown}
          placeholder={config.placeholder}
          rows={config.rows}
          className="min-h-[120px] max-h-[320px] w-full resize-y rounded-[22px] border border-white/70 bg-white px-4 py-3 text-sm leading-6 text-slate-900 shadow-inner outline-none transition focus:border-slate-300 focus:ring-2 focus:ring-slate-200"
        />
      </div>
    </article>
  );
}
