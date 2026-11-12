import Link from "next/link";
import { ArrowLeft, SearchX } from "lucide-react";

import FortCordisStateShell from "@/components/system/FortCordisStateShell";

export default function NotFound() {
  return (
    <FortCordisStateShell
      eyebrow="Página não encontrada"
      title="Este caminho não está disponível"
      description="Verifique o endereço informado ou retorne para uma área conhecida do sistema."
      icon={<SearchX className="h-7 w-7" />}
    >
      <Link href="/" className="fc-system-state-primary">
        <ArrowLeft className="h-4 w-4" />
        Voltar ao início
      </Link>
      <Link href="/dashboard" className="fc-system-state-secondary">Abrir dashboard</Link>
    </FortCordisStateShell>
  );
}
