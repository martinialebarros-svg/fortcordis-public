import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";

import PortalPartnerActivationWorkspace from "@/components/portal/PortalPartnerActivationWorkspace";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Ative seu acesso de parceiro | Fort Cordis",
  description:
    "Conclua a ativação do portal do veterinário parceiro e passe a consultar exames e laudos liberados com acesso seguro.",
  path: "/veterinario-parceiro/ativar",
});

type VeterinarioParceiroAtivarPageProps = {
  params: Promise<{
    token: string;
  }>;
};

export default async function VeterinarioParceiroAtivarPage({
  params,
}: VeterinarioParceiroAtivarPageProps) {
  const { token } = await params;

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
            <ShieldCheck className="h-8 w-8 text-teal-700" />
            <h1 className="mt-5 text-3xl font-bold text-slate-950">Ativação segura do parceiro</h1>
            <p className="mt-4 text-sm leading-7 text-slate-600">
              Este link autoriza apenas o cadastro inicial. Depois disso, o acesso passa a ser feito com e-mail,
              senha e confirmação adicional apenas quando necessário.
            </p>
            <div className="mt-6 space-y-3 text-sm leading-6 text-slate-600">
              <p>1. Confira se este convite realmente pertence ao seu acesso profissional.</p>
              <p>2. Cadastre o responsável e crie a senha do portal.</p>
              <p>3. Ao concluir, você já entra no ambiente do parceiro.</p>
            </div>
          </div>

          <PortalPartnerActivationWorkspace inviteToken={token} />
        </section>
      </div>
    </main>
  );
}
