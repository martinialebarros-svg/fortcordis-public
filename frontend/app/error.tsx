"use client";

import Link from "next/link";
import { AlertTriangle, RotateCcw } from "lucide-react";

import FortCordisStateShell from "@/components/system/FortCordisStateShell";

type ErrorPageProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function ErrorPage({ reset }: ErrorPageProps) {
  return (
    <FortCordisStateShell
      eyebrow="Interrupção temporária"
      title="Não foi possível abrir esta tela"
      description="O sistema encontrou uma falha inesperada. Tente novamente ou retorne ao início."
      icon={<AlertTriangle className="h-7 w-7" />}
    >
      <button type="button" onClick={reset} className="fc-system-state-primary">
        <RotateCcw className="h-4 w-4" />
        Tentar novamente
      </button>
      <Link href="/" className="fc-system-state-secondary">Voltar ao início</Link>
    </FortCordisStateShell>
  );
}
