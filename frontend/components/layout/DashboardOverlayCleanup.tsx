"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

function elementoVisivelNoViewport(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || "1") === 0) {
    return false;
  }
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  if (rect.bottom <= 0 || rect.right <= 0) return false;
  if (rect.top >= window.innerHeight || rect.left >= window.innerWidth) return false;
  return true;
}

function limparBackdropsOrfaos(): void {
  if (typeof document === "undefined") return;

  const viewportArea = window.innerWidth * window.innerHeight;
  const candidatos = Array.from(
    document.body.querySelectorAll(
      "div.fixed, button.fixed, [data-fortcordis-orphan-overlay-hidden='1']"
    )
  ) as HTMLElement[];

  candidatos.forEach((elemento) => {
    if (!elemento.isConnected) return;
    if (elemento.dataset.fortcordisOverlaySafe === "1") return;
    if (elemento.closest("[data-fortcordis-overlay-safe='1']")) return;
    if (elemento === document.body || elemento === document.documentElement) return;

    const className = typeof elemento.className === "string" ? elemento.className : "";
    const style = window.getComputedStyle(elemento);
    const rect = elemento.getBoundingClientRect();
    const coversViewport =
      rect.width * rect.height >= viewportArea * 0.9 &&
      rect.top <= 0 &&
      rect.left <= 0;
    const candidatosDialogo = Array.from(
      elemento.querySelectorAll(
        "[role='dialog'], iframe, img, form, section, article, textarea, input, select, button, [data-modal-content]"
      )
    );
    const hasDialogContentVisivel = candidatosDialogo.some((item) => elementoVisivelNoViewport(item));
    const hasMeaningfulTextVisivel = Array.from(
      elemento.querySelectorAll("h1, h2, h3, h4, h5, h6, p, span, strong, small, label, button")
    ).some((item) => {
      if (!elementoVisivelNoViewport(item)) return false;
      return Boolean((item.textContent || "").trim());
    });
    const backgroundColor = style.backgroundColor || "";
    const isDarkBackdrop =
      className.includes("bg-black/50") ||
      className.includes("bg-black bg-opacity-50") ||
      className.includes("bg-slate-950/70") ||
      /^rgba?\((\s*\d+\s*,){2}\s*\d+,\s*0\.[1-9]/.test(backgroundColor);
    const looksLikeOverlay =
      style.position === "fixed" &&
      Number(style.zIndex || "0") >= 40 &&
      coversViewport &&
      (
        className.includes("inset-0") ||
        isDarkBackdrop
      );

    if (looksLikeOverlay && !hasDialogContentVisivel && !hasMeaningfulTextVisivel) {
      elemento.style.display = "none";
      elemento.style.pointerEvents = "none";
      elemento.setAttribute("data-fortcordis-orphan-overlay-hidden", "1");
    }
  });
}

export default function DashboardOverlayCleanup() {
  const pathname = usePathname();
  const overlayCleanupRafRef = useRef<number | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const handle = window.setTimeout(() => {
      limparBackdropsOrfaos();
    }, 120);

    const observer = new MutationObserver(() => {
      if (overlayCleanupRafRef.current !== null) return;
      overlayCleanupRafRef.current = window.requestAnimationFrame(() => {
        overlayCleanupRafRef.current = null;
        limparBackdropsOrfaos();
      });
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    return () => {
      window.clearTimeout(handle);
      if (overlayCleanupRafRef.current !== null) {
        window.cancelAnimationFrame(overlayCleanupRafRef.current);
        overlayCleanupRafRef.current = null;
      }
      observer.disconnect();
    };
  }, [pathname]);

  return null;
}
