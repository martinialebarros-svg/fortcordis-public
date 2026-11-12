"use client";

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

interface ModalProps {
  /** id do elemento que serve de titulo acessivel do dialog (aria-labelledby). */
  titleId: string;
  onClose: () => void;
  children: ReactNode;
  /** Classes completas do overlay (posicionamento, cor de fundo, z-index). */
  overlayClassName: string;
  /** Classes completas do container do conteudo do modal. */
  contentClassName: string;
  closeOnEscape?: boolean;
  closeOnOverlayClick?: boolean;
  overlayCloseLabel?: string;
}

/**
 * Wrapper de acessibilidade compartilhado pelos modais do atendimento:
 * role="dialog" + aria-modal + aria-labelledby, fechar com Escape, clique
 * fora fecha, e autoFocus no primeiro elemento interativo do conteudo.
 */
export default function Modal({
  titleId,
  onClose,
  children,
  overlayClassName,
  contentClassName,
  closeOnEscape = true,
  closeOnOverlayClick = true,
  overlayCloseLabel = "Fechar",
}: ModalProps) {
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!closeOnEscape) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [closeOnEscape, onClose]);

  useEffect(() => {
    const focusable = contentRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    focusable?.focus();
  }, []);

  return (
    <div data-fortcordis-overlay-safe="1" className={overlayClassName}>
      {closeOnOverlayClick ? (
        <button
          type="button"
          aria-label={overlayCloseLabel}
          onClick={onClose}
          className="absolute inset-0 cursor-default"
        />
      ) : null}
      <div
        ref={contentRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-fortcordis-overlay-safe="1"
        className={contentClassName}
      >
        {children}
      </div>
    </div>
  );
}
