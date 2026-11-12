import type { Metadata } from "next";

import PortalPartnerPageShell from "@/components/portal/PortalPartnerPageShell";
import { buildPortalMetadata } from "@/lib/portal-metadata";

export const metadata: Metadata = buildPortalMetadata({
  title: "Portal do veterinário parceiro | Fort Cordis",
  description:
    "Acesse exames e laudos liberados para sua atuação como veterinário parceiro da Fort Cordis, com segurança e contexto clínico organizado.",
  path: "/veterinario-parceiro",
});

export default function VeterinarioParceiroPage() {
  return <PortalPartnerPageShell />;
}
