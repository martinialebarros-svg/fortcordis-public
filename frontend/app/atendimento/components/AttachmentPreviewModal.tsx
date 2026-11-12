"use client";

import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Download,
  Minus,
  Plus,
  RefreshCw,
  X,
} from "lucide-react";
import Modal from "./Modal";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AttachmentPreviewModalProps = LooseAtendimentoComponentProps;

export default function AttachmentPreviewModal(props: AttachmentPreviewModalProps) {
  const {
    attachmentImageDragging,
    attachmentImageOffset,
    attachmentImageZoom,
    attachmentPdfPage,
    attachmentPdfZoom,
    attachmentPreview,
    abrirAnexo,
    buildPdfPreviewUrl,
    closeAttachmentPreview,
    formatDate,
    handleAttachmentImagePointerDown,
    handleAttachmentImagePointerMove,
    handleAttachmentImagePointerUp,
    resetAttachmentImageView,
    setAttachmentImageOffset,
    setAttachmentPdfPage,
    setAttachmentPdfZoom,
    zoomInAttachmentImage,
    zoomOutAttachmentImage,
  } = props;

  if (!attachmentPreview) {
    return null;
  }

  return (
    <Modal
      titleId="attachment-preview-modal-titulo"
      onClose={closeAttachmentPreview}
      overlayClassName="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/70 px-4 py-6"
      contentClassName="relative z-[121] flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-2xl"
      overlayCloseLabel="Fechar preview"
    >
        <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Preview do anexo</p>
            <h3 id="attachment-preview-modal-titulo" className="mt-1 text-lg font-semibold text-slate-900">{attachmentPreview.title}</h3>
            <p className="mt-1 text-sm text-slate-500">
              {attachmentPreview.anexo.descricao || attachmentPreview.anexo.tipo}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => abrirAnexo(attachmentPreview.anexo, "download")}
              className="inline-flex items-center gap-2 rounded-xl bg-blue-100 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-200"
            >
              <Download className="h-4 w-4" />
              Baixar
            </button>
            {attachmentPreview.url ? (
              <button
                type="button"
                onClick={() => window.open(attachmentPreview.url, "_blank", "noopener,noreferrer")}
                className="inline-flex items-center gap-2 rounded-xl bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
              >
                <ArrowRight className="h-4 w-4" />
                Nova aba
              </button>
            ) : null}
            <button
              type="button"
              onClick={closeAttachmentPreview}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
            >
              <X className="h-4 w-4" />
              Fechar
            </button>
          </div>
        </div>
        <div className="border-b border-slate-200 bg-slate-50 px-5 py-3">
          {attachmentPreview.kind === "image" ? (
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-white px-3 py-1 text-xs font-medium uppercase tracking-[0.2em] text-slate-500">
                  Imagem
                </span>
                <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                  Zoom {Math.round(attachmentImageZoom * 100)}%
                </span>
                {attachmentPreview.anexo.created_at ? (
                  <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                    {formatDate(attachmentPreview.anexo.created_at)}
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={zoomOutAttachmentImage}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  <Minus className="h-4 w-4" />
                  Reduzir
                </button>
                <button
                  type="button"
                  onClick={resetAttachmentImageView}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  <RefreshCw className="h-4 w-4" />
                  Ajustar
                </button>
                <button
                  type="button"
                  onClick={zoomInAttachmentImage}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  <Plus className="h-4 w-4" />
                  Ampliar
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-white px-3 py-1 text-xs font-medium uppercase tracking-[0.2em] text-slate-500">
                  PDF
                </span>
                <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                  Pagina {attachmentPdfPage}
                </span>
                <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                  Zoom {attachmentPdfZoom}%
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setAttachmentPdfPage((current: number) => Math.max(1, current - 1))}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Anterior
                </button>
                <input
                  type="number"
                  min={1}
                  value={attachmentPdfPage}
                  onChange={(event) => {
                    const nextPage = Number(event.target.value);
                    setAttachmentPdfPage(Number.isFinite(nextPage) && nextPage > 0 ? nextPage : 1);
                  }}
                  className="w-20 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                />
                <button
                  type="button"
                  onClick={() => setAttachmentPdfPage((current: number) => current + 1)}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  Proxima
                  <ChevronRight className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setAttachmentPdfZoom((current: number) => Math.max(60, current - 10))}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  <Minus className="h-4 w-4" />
                  Zoom
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAttachmentPdfPage(1);
                    setAttachmentPdfZoom(110);
                  }}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  <RefreshCw className="h-4 w-4" />
                  Resetar
                </button>
                <button
                  type="button"
                  onClick={() => setAttachmentPdfZoom((current: number) => Math.min(220, current + 10))}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                >
                  <Plus className="h-4 w-4" />
                  Zoom
                </button>
              </div>
            </div>
          )}
        </div>
        <div className="overflow-auto bg-slate-100 p-4 md:p-6">
          {attachmentPreview.kind === "image" ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 px-1 text-xs font-medium text-slate-500">
                <span className="rounded-full bg-white px-3 py-1">
                  {attachmentImageZoom > 1
                    ? "Arraste a imagem para explorar o detalhe."
                    : "Amplie para habilitar o arraste."}
                </span>
                {attachmentImageZoom > 1 ? (
                  <button
                    type="button"
                    onClick={() => setAttachmentImageOffset({ x: 0, y: 0 })}
                    className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-slate-600 hover:bg-slate-200"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    Centralizar
                  </button>
                ) : null}
              </div>
              <div
                onPointerDown={handleAttachmentImagePointerDown}
                onPointerMove={handleAttachmentImagePointerMove}
                onPointerUp={handleAttachmentImagePointerUp}
                onPointerCancel={handleAttachmentImagePointerUp}
                className={`flex min-h-[60vh] items-center justify-center overflow-hidden rounded-[24px] border border-slate-200 bg-white p-4 select-none touch-none ${
                  attachmentImageZoom > 1 ? (attachmentImageDragging ? "cursor-grabbing" : "cursor-grab") : "cursor-default"
                }`}
              >
                <img
                  src={attachmentPreview.url}
                  alt={attachmentPreview.title}
                  draggable={false}
                  className="max-h-none w-auto max-w-none rounded-2xl object-contain transition-transform duration-150"
                  style={{
                    transform: `translate(${attachmentImageOffset.x}px, ${attachmentImageOffset.y}px) scale(${attachmentImageZoom})`,
                    transformOrigin: "center center",
                  }}
                />
              </div>
            </div>
          ) : (
            <div className="overflow-auto rounded-[24px] border border-slate-200 bg-slate-100 p-3">
              <div
                className="min-w-full overflow-hidden rounded-[18px] border border-slate-200 bg-white shadow-sm"
                style={{
                  width: `${Math.max(attachmentPdfZoom, 60)}%`,
                }}
              >
                <iframe
                  key={`${attachmentPreview.url}-${attachmentPdfPage}`}
                  src={buildPdfPreviewUrl(attachmentPreview)}
                  title={attachmentPreview.title}
                  className="h-[72vh] w-full"
                />
              </div>
            </div>
          )}
        </div>
    </Modal>
  );
}
