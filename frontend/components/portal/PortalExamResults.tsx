"use client";

import { Download, FileCheck2, Loader2 } from "lucide-react";

import { formatPortalDateTime } from "@/lib/portal-datetime";
import { formatCalendarDate } from "@/lib/calendar-date";
import type { PortalExamItem } from "@/lib/portal-api";

function formatFileSize(value: number | null): string {
  if (!value || value <= 0) {
    return "-";
  }
  if (value >= 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${value} B`;
}

type PortalExamResultsProps = {
  emptyMessage: string;
  exams: PortalExamItem[];
  downloadingAttachmentId: number | null;
  onDownload: (examId: number, attachmentId: number) => void;
};

export default function PortalExamResults({
  emptyMessage,
  exams,
  downloadingAttachmentId,
  onDownload,
}: PortalExamResultsProps) {
  if (exams.length === 0) {
    return (
      <div className="fc-portal-exams-empty rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm leading-6 text-slate-600">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="fc-portal-exams space-y-4">
      {exams.map((exam) => (
        <article key={exam.id} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-4 border-b border-slate-200 pb-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
                Exame #{exam.id}
              </p>
              <h3 className="mt-2 text-xl font-bold text-slate-950">{exam.tipo_exame}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                {exam.categoria_exame || "Categoria não informada"} · {exam.status || "Status não informado"}
              </p>
            </div>
            <dl className="grid gap-3 text-sm text-slate-600 sm:grid-cols-2">
              <div>
                <dt className="font-semibold text-slate-900">Data de realização</dt>
                <dd>{formatCalendarDate(exam.data_exame || exam.data_solicitacao)}</dd>
              </div>
              <div>
                <dt className="font-semibold text-slate-900">Data de liberação</dt>
                <dd>{formatPortalDateTime(exam.data_resultado)}</dd>
              </div>
            </dl>
          </div>

          {exam.observacoes ? (
            <p className="mt-4 text-sm leading-6 text-slate-600">{exam.observacoes}</p>
          ) : null}

          <div className="mt-4 space-y-3">
            {exam.anexos.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">
                Nenhum anexo liberado para este exame.
              </div>
            ) : (
              exam.anexos.map((attachment) => {
                const isDownloading = downloadingAttachmentId === attachment.anexo_id;
                return (
                  <div
                    key={attachment.anexo_id}
                    className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <span className="mt-0.5 rounded-lg bg-slate-100 p-2 text-slate-700">
                        <FileCheck2 className="h-5 w-5" />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-slate-950">
                          {attachment.nome_original}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {attachment.mime_type} · {formatFileSize(attachment.tamanho)}
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onDownload(exam.id, attachment.anexo_id)}
                      disabled={!attachment.download_available || isDownloading}
                      className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      {isDownloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                      {isDownloading ? "Baixando..." : "Baixar"}
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
