"use client";

import { AlertTriangle, ClipboardPlus, ExternalLink, FileText, FileX, Loader2 } from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoPrescricaoPreviewProps = LooseAtendimentoComponentProps;

export default function AtendimentoPrescricaoPreview(props: AtendimentoPrescricaoPreviewProps) {
  const { form, gerarPreviewPdf, prescricaoPreviewErro, prescricaoPreviewLoading, prescricaoPreviewPdf } = props;

  return (
    <section className="overflow-hidden rounded-[24px] border border-teal-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-teal-100 bg-teal-50 px-5 py-3">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-teal-600" />
          <p className="text-sm font-semibold text-teal-700">Preview da receita</p>
        </div>
        <div className="flex items-center gap-3">
          {prescricaoPreviewLoading && (
            <div className="flex items-center gap-2 text-xs text-teal-600">
              <Loader2 className="h-3 w-3 animate-spin" />
              Gerando...
            </div>
          )}
          {prescricaoPreviewPdf ? (
            <button
              type="button"
              onClick={() => window.open(prescricaoPreviewPdf, "_blank", "noopener,noreferrer")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-teal-200 bg-white px-2.5 py-1.5 text-xs font-medium text-teal-700 transition hover:bg-teal-100"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Abrir em nova aba
            </button>
          ) : null}
        </div>
      </div>
      <div className="bg-slate-100" style={{ height: "min(60vh, 500px)" }}>
        {prescricaoPreviewPdf ? (
          <iframe src={prescricaoPreviewPdf} title="Preview da prescricao" className="h-full w-full" style={{ border: "none" }} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              {form.prescricao_itens.every((item: any) => !(item.medicamento_nome || "").trim()) ? (
                <>
                  <ClipboardPlus className="mx-auto h-10 w-10 text-slate-300" />
                  <p className="mt-3 text-sm text-slate-400">Adicione medicamentos para ver o preview</p>
                </>
              ) : prescricaoPreviewLoading ? (
                <div className="flex flex-col items-center gap-2">
                  <Loader2 className="h-8 w-8 animate-spin text-teal-500" />
                  <p className="text-sm text-slate-400">Gerando preview...</p>
                </div>
              ) : prescricaoPreviewErro ? (
                <div className="flex flex-col items-center gap-3 px-6">
                  <AlertTriangle className="h-10 w-10 text-red-400" />
                  <p className="text-sm font-medium text-red-600">{prescricaoPreviewErro}</p>
                  <button
                    type="button"
                    onClick={() => gerarPreviewPdf()}
                    className="rounded-lg border border-red-200 bg-white px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                  >
                    Tentar novamente
                  </button>
                </div>
              ) : (
                <>
                  <FileX className="mx-auto h-10 w-10 text-slate-300" />
                  <p className="mt-3 text-sm text-slate-400">Preview nao disponivel</p>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
