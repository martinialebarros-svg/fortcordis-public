import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, KeyRound } from "lucide-react";

import PortalPartnerResetPasswordWorkspace from "@/components/portal/PortalPartnerResetPasswordWorkspace";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Recupere o acesso do parceiro | Fort Cordis",
  description:
    "Redefina a senha do portal do veterinário parceiro e volte a consultar exames e laudos liberados com segurança.",
  path: "/veterinario-parceiro/redefinir-senha",
});

type VeterinarioParceiroResetPageProps = {
  searchParams: Promise<{
    token?: string;
  }>;
};

export default async function VeterinarioParceiroResetPage({
  searchParams,
}: VeterinarioParceiroResetPageProps) {
  const params = await searchParams;
  const resetToken = params.token || "";

  return (
    <main className="fc-portal-auth-page">
      <div className="fc-portal-auth-shell">
        <Link href="/veterinario-parceiro" className="fc-portal-auth-back">
          <ArrowLeft className="h-4 w-4" />
          Voltar para o portal do parceiro
        </Link>

        <section className="fc-portal-auth-grid">
          <div className="fc-portal-auth-intro">
            <Image src="/brand/fortcordis-logo-oficial.png" alt="Fort Cordis" width={56} height={56} priority />
            <KeyRound className="h-8 w-8 text-teal-700" />
            <h1 className="mt-5 text-3xl font-bold text-slate-950">Recuperação segura da conta</h1>
            <p className="mt-4 text-sm leading-7 text-slate-600">
              Este passo atualiza a senha do parceiro sem expor exames por e-mail. Depois da troca, o portal invalida
              as sessões anteriores e pode pedir confirmação adicional no próximo login.
            </p>
          </div>

          <PortalPartnerResetPasswordWorkspace resetToken={resetToken} />
        </section>
      </div>
    </main>
  );
}
