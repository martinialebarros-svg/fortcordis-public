"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Move, RotateCcw, X, ZoomIn, ZoomOut } from "lucide-react";

export interface PreviewImage {
  id: string | number;
  nome: string;
  src: string;
}

interface ImagePreviewModalProps {
  images: PreviewImage[];
  selectedIndex: number | null;
  onSelectedIndexChange: (index: number | null) => void;
}

export default function ImagePreviewModal({ images, selectedIndex, onSelectedIndexChange }: ImagePreviewModalProps) {
  const isOpen = selectedIndex !== null && Boolean(images[selectedIndex]);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragOrigin, setDragOrigin] = useState<{ x: number; y: number; offsetX: number; offsetY: number } | null>(null);

  useEffect(() => {
    setZoom(1);
    setOffset({ x: 0, y: 0 });
    setDragOrigin(null);
  }, [isOpen, selectedIndex]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onSelectedIndexChange(null);
      if (event.key === "ArrowLeft" && images.length > 1) {
        onSelectedIndexChange((selectedIndex! - 1 + images.length) % images.length);
      }
      if (event.key === "ArrowRight" && images.length > 1) {
        onSelectedIndexChange((selectedIndex! + 1) % images.length);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [images.length, isOpen, onSelectedIndexChange, selectedIndex]);

  if (!isOpen) return null;
  const image = images[selectedIndex!];
  const previous = () => onSelectedIndexChange((selectedIndex! - 1 + images.length) % images.length);
  const next = () => onSelectedIndexChange((selectedIndex! + 1) % images.length);
  const resetView = () => {
    setZoom(1);
    setOffset({ x: 0, y: 0 });
  };
  const changeZoom = (nextZoom: number) => {
    const boundedZoom = Math.min(4, Math.max(1, nextZoom));
    setZoom(boundedZoom);
    if (boundedZoom === 1) setOffset({ x: 0, y: 0 });
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={`Visualização ampliada de ${image.nome}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onSelectedIndexChange(null);
      }}
    >
      <div className="relative flex h-full w-full max-w-7xl flex-col items-center justify-center">
        <button type="button" onClick={() => onSelectedIndexChange(null)} className="absolute right-0 top-0 z-10 rounded-full bg-white/95 p-2 text-gray-800 shadow hover:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400" aria-label="Fechar visualização">
          <X className="h-6 w-6" />
        </button>
        {images.length > 1 && (
          <button type="button" onClick={previous} className="absolute left-0 z-10 rounded-full bg-white/95 p-2 text-gray-800 shadow hover:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400" aria-label="Imagem anterior">
            <ChevronLeft className="h-7 w-7" />
          </button>
        )}
        <div
          className={`flex h-[calc(100vh-8rem)] w-full items-center justify-center overflow-hidden ${
            zoom > 1 ? "cursor-grab active:cursor-grabbing" : ""
          }`}
          onPointerDown={(event) => {
            if (zoom === 1) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            setDragOrigin({ x: event.clientX, y: event.clientY, offsetX: offset.x, offsetY: offset.y });
          }}
          onPointerMove={(event) => {
            if (!dragOrigin) return;
            setOffset({
              x: dragOrigin.offsetX + event.clientX - dragOrigin.x,
              y: dragOrigin.offsetY + event.clientY - dragOrigin.y,
            });
          }}
          onPointerUp={() => setDragOrigin(null)}
          onPointerCancel={() => setDragOrigin(null)}
        >
          <img
            src={image.src}
            alt={image.nome}
            draggable={false}
            className="max-h-full max-w-full select-none object-contain transition-transform duration-100"
            style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})` }}
          />
        </div>
        {images.length > 1 && (
          <button type="button" onClick={next} className="absolute right-0 z-10 rounded-full bg-white/95 p-2 text-gray-800 shadow hover:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400" aria-label="Próxima imagem">
            <ChevronRight className="h-7 w-7" />
          </button>
        )}
        <div className="absolute bottom-0 flex max-w-full items-center gap-2 rounded-lg bg-black/75 px-3 py-2 text-sm text-white">
          <button type="button" onClick={() => changeZoom(zoom - 0.5)} disabled={zoom === 1} className="rounded p-1 hover:bg-white/20 disabled:opacity-40" aria-label="Diminuir zoom">
            <ZoomOut className="h-5 w-5" />
          </button>
          <span className="w-12 text-center text-xs font-medium">{Math.round(zoom * 100)}%</span>
          <button type="button" onClick={() => changeZoom(zoom + 0.5)} disabled={zoom === 4} className="rounded p-1 hover:bg-white/20 disabled:opacity-40" aria-label="Aumentar zoom">
            <ZoomIn className="h-5 w-5" />
          </button>
          <button type="button" onClick={resetView} className="rounded p-1 hover:bg-white/20" aria-label="Ajustar imagem à tela">
            <RotateCcw className="h-5 w-5" />
          </button>
          {zoom > 1 && <Move className="h-4 w-4 text-gray-300" aria-label="Arraste para mover" />}
          <div className="ml-2 max-w-48 text-left">
          <p className="truncate font-medium">{image.nome}</p>
          <p className="text-xs text-gray-300">Imagem {selectedIndex! + 1} de {images.length}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
