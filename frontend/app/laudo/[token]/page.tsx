import type { Metadata } from "next";
import Image from "next/image";

import PortalExamLinkWorkspace from "@/components/portal/PortalExamLinkWorkspace";

export const metadata: Metadata = {
  title: "Laudo Fort Cordis",
  description: "Acesso direto ao laudo liberado para a unidade parceira.",
  // A URL e credencial de acesso ao laudo: nao pode ser indexada nem virar
  // referer para terceiros.
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

type LaudoLinkPageProps = {
  params: Promise<{
    token: string;
  }>;
};

export default async function LaudoLinkPage({ params }: LaudoLinkPageProps) {
  const { token } = await params;

  return (
    <main className="fc-portal-auth-page">
      <div className="fc-portal-auth-shell max-w-xl">
        <div className="mb-6 flex items-center gap-3">
          <Image
            src="/brand/fortcordis-logo-oficial.png"
            alt="Fort Cordis"
            width={44}
            height={44}
            priority
            className="rounded-lg border border-white/20 bg-white object-contain"
          />
          <p className="text-sm font-semibold text-white/80">Laudo liberado</p>
        </div>

        <PortalExamLinkWorkspace linkToken={token} />
      </div>
    </main>
  );
}
