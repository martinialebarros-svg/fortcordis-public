import type { Metadata } from "next";
import Image from "next/image";
import { ShieldCheck } from "lucide-react";

import AgendaFormalizacaoWorkspace from "@/components/agenda/AgendaFormalizacaoWorkspace";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Confirme os dados do agendamento | Fort Cordis",
  description:
    "Preencha o nome do paciente e do tutor para formalizar o atendimento reservado com a Fort Cordis.",
  path: "/agenda/formalizar",
});

type AgendaFormalizarPageProps = {
  params: Promise<{
    token: string;
  }>;
};

export default async function AgendaFormalizarPage({ params }: AgendaFormalizarPageProps) {
  const { token } = await params;

  return (
    <main className="fc-portal-auth-page">
      <div className="fc-portal-auth-shell">
        <section className="fc-portal-auth-grid">
          <div className="fc-portal-auth-intro">
            <Image src="/brand/fortcordis-logo-oficial.png" alt="Fort Cordis" width={56} height={56} priority />
            <ShieldCheck className="h-8 w-8 text-teal-700" />
            <h1 className="mt-5 text-3xl font-bold text-slate-950">
              Confirme os dados do agendamento
            </h1>
            <p className="mt-4 text-sm leading-7 text-slate-600">
              Preencha o nome do paciente e do tutor responsável para formalizar o horário reservado.
              Assim que os dados forem enviados, o atendimento é atualizado automaticamente no sistema
              da Fort Cordis.
            </p>
          </div>

          <AgendaFormalizacaoWorkspace token={token} />
        </section>
      </div>
    </main>
  );
}
