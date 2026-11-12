import type { Metadata } from "next";
import PortalClinicaPageShell from "@/components/portal/PortalClinicaPageShell";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Portal da clínica parceira | Fort Cordis",
  description:
    "Sua clinica acompanha exames e laudos liberados com mais agilidade, seguranca e continuidade no cuidado dos pacientes atendidos com a Fort Cordis.",
  path: "/clinica-parceira",
});

export default function ClinicaParceiraPage() {
  return <PortalClinicaPageShell />;
}
