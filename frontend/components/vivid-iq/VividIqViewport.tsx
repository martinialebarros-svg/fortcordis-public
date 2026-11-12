"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, RotateCcw } from "lucide-react";

const ZOOM_LEVELS = [1, 1.5, 2, 3, 4];

export interface VividIqViewportProps {
  aspectRatio: number;
  expanded: boolean;
  children: ReactNode;
}

export function VividIqViewport({ aspectRatio, expanded, children }: VividIqViewportProps) {
  const [zoom, setZoom] = useState(1);
  const [isDragging, setIsDragging] = useState(false);
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    x: number;
    y: number;
    scrollLeft: number;
    scrollTop: number;
  } | null>(null);
  const safeAspectRatio = Number.isFinite(aspectRatio) && aspectRatio > 0 ? aspectRatio : 1;
  const fitHeight = Math.max(1, Math.floor(Math.min(viewportSize.height, viewportSize.width / safeAspectRatio)));
  const imageWidth = fitHeight * safeAspectRatio * zoom;
  const imageHeight = fitHeight * zoom;

  const centerImage = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollLeft = Math.max(0, (viewport.scrollWidth - viewport.clientWidth) / 2);
    viewport.scrollTop = Math.max(0, (viewport.scrollHeight - viewport.clientHeight) / 2);
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const measure = () => {
      const width = viewport.clientWidth;
      const height = viewport.clientHeight;
      setViewportSize((current) => current.width === width && current.height === height
        ? current
        : { width, height });
    };
    measure();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(measure);
      observer.observe(viewport);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [expanded]);

  useLayoutEffect(() => {
    centerImage();
  }, [centerImage, imageWidth, imageHeight, viewportSize.width, viewportSize.height]);

  const resetImage = () => {
    setZoom(1);
    centerImage();
  };

  const beginDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (zoom <= 1 || event.pointerType !== "mouse" || event.button !== 0) return;
    const viewport = event.currentTarget;
    dragRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.setPointerCapture(event.pointerId);
    setIsDragging(true);
    event.preventDefault();
  };

  const moveDrag = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.currentTarget.scrollLeft = drag.scrollLeft - (event.clientX - drag.x);
    event.currentTarget.scrollTop = drag.scrollTop - (event.clientY - drag.y);
    event.preventDefault();
  };

  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setIsDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const moveImage = (horizontal: number, vertical: number) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollLeft += horizontal * Math.max(48, viewport.clientWidth / 4);
    viewport.scrollTop += vertical * Math.max(48, viewport.clientHeight / 4);
  };

  const directionButtonClass = "inline-flex min-h-10 min-w-10 items-center justify-center rounded-lg border border-white/25 p-2 text-white hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-vital-300 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";

  return (
    <div className={`flex min-h-0 flex-col bg-black ${expanded ? "flex-1" : ""}`}>
      <div className="shrink-0 space-y-2 border-b border-white/15 bg-ink-900 px-3 py-2 text-xs text-white">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 font-semibold">
              Ampliação
              <select
                value={zoom}
                onChange={(event) => setZoom(Number(event.target.value))}
                className="rounded-lg border border-white/25 bg-ink-900 px-2 py-2 text-sm text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-vital-300"
              >
                {ZOOM_LEVELS.map((level) => <option key={level} value={level}>{level.toLocaleString("pt-BR")}x</option>)}
              </select>
            </label>
            <button type="button" onClick={resetImage} className="inline-flex items-center gap-1.5 rounded-lg border border-white/25 px-3 py-2 font-semibold hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-vital-300">
              <RotateCcw className="h-4 w-4" aria-hidden="true" /> Ajustar imagem
            </button>
          </div>
          {zoom > 1 && <div className="flex gap-1" role="group" aria-label="Mover imagem ampliada">
            <button type="button" disabled={zoom <= 1} onClick={() => moveImage(-1, 0)} aria-label="Mover imagem para esquerda" title="Mover imagem para esquerda" className={directionButtonClass}><ArrowLeft className="h-4 w-4" aria-hidden="true" /></button>
            <button type="button" disabled={zoom <= 1} onClick={() => moveImage(1, 0)} aria-label="Mover imagem para direita" title="Mover imagem para direita" className={directionButtonClass}><ArrowRight className="h-4 w-4" aria-hidden="true" /></button>
            <button type="button" disabled={zoom <= 1} onClick={() => moveImage(0, -1)} aria-label="Mover imagem para cima" title="Mover imagem para cima" className={directionButtonClass}><ArrowUp className="h-4 w-4" aria-hidden="true" /></button>
            <button type="button" disabled={zoom <= 1} onClick={() => moveImage(0, 1)} aria-label="Mover imagem para baixo" title="Mover imagem para baixo" className={directionButtonClass}><ArrowDown className="h-4 w-4" aria-hidden="true" /></button>
          </div>}
        </div>
        {zoom > 1 && <p className="text-white/65">Arraste ou use as setas para mover. O PNG mantém o quadro inteiro.</p>}
      </div>
      <div
        ref={viewportRef}
        role="region"
        aria-label="Área de visualização"
        tabIndex={0}
        onPointerDown={beginDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onLostPointerCapture={endDrag}
        className={`relative overflow-auto overscroll-contain bg-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-vital-300 ${expanded ? "min-h-[16dvh] flex-1" : "h-[min(58dvh,640px)] min-h-64"} ${zoom > 1 ? isDragging ? "cursor-grabbing" : "cursor-grab" : ""}`}
        style={{ touchAction: "pan-x pan-y pinch-zoom", userSelect: zoom > 1 ? "none" : undefined }}
      >
        <div className="flex items-center justify-center" style={{ width: Math.max(viewportSize.width, imageWidth), height: Math.max(viewportSize.height, imageHeight) }}>
          <div className="shrink-0 [&>canvas]:block [&>canvas]:h-full [&>canvas]:w-full" style={{ width: imageWidth, height: imageHeight }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

export default VividIqViewport;
