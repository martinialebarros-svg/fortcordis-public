import { Loader2 } from "lucide-react";

import FortCordisStateShell from "@/components/system/FortCordisStateShell";

export default function Loading() {
  return (
    <FortCordisStateShell
      eyebrow="Preparando ambiente"
      title="Carregando Fort Cordis"
      description="Organizando os dados clínicos para exibir a próxima tela."
      icon={<Loader2 className="h-7 w-7 animate-spin" />}
    />
  );
}
