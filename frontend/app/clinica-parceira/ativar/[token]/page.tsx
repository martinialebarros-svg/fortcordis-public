import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import { ArrowLeft, ShieldCheck } from "lucide-react";

import PortalClinicActivationWorkspace from "@/components/portal/PortalClinicActivationWorkspace";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Ative o portal da sua clínica | Fort Cordis",
  description:
    "Conclua o cadastro da unidade e passe a consultar exames e laudos liberados no Portal Fort Cordis, com acesso seguro para a equipe responsavel.",
  path: "/clinica-parceira/ativar",
});

type ClinicaParceiraAtivarPageProps = {
  params: Promise<{
    token: string;
  }>;
};

export default async function ClinicaParceiraAtivarPage({
  params,
}: ClinicaParceiraAtivarPageProps) {
  const { token } = await params;

  return (
    <main className="fc-portal-auth-page">
      <div className="fc-portal-auth-shell">
        <Link
          href="/clinica-parceira"
          className="fc-portal-auth-back"
        >
          <ArrowLeft className="h-4 w-4" />
          Voltar para o portal da clínica
        </Link>

        <section className="fc-portal-auth-grid">
          <div className="fc-portal-auth-intro">
            <Image src="/brand/fortcordis-logo-oficial.png" alt="Fort Cordis" width={56} height={56} priority />
            <ShieldCheck className="h-8 w-8 text-teal-700" />
            <h1 className="mt-5 text-3xl font-bold text-slate-950">
              Ativação segura da unidade parceira
            </h1>
            <p className="mt-4 text-sm leading-7 text-slate-600">
              Este link apenas autoriza o cadastro inicial. O acesso aos exames continua protegido por e-mail institucional, senha e verificação adicional em ações sensíveis.
            </p>
            <div className="mt-6 space-y-3 text-sm leading-6 text-slate-600">
              <p>1. Confira o e-mail institucional definido para a unidade.</p>
              <p>2. Cadastre o responsável e uma senha forte para o portal.</p>
              <p>3. Ao concluir, a unidade já entra no portal da clínica.</p>
            </div>
          </div>

          <PortalClinicActivationWorkspace inviteToken={token} />
        </section>
      </div>
    </main>
  );
}
