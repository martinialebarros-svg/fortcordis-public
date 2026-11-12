import type { PortalPartnerClinicLink, PortalPartnerClinicLinkPayload } from "@/lib/portal-api";

/**
 * Regras do vinculo do veterinario parceiro com as clinicas em que atende.
 *
 * Marcar a clinica cria o vinculo desligado: o veterinario passa a aparecer no
 * topo do seletor de laudo daquela clinica, mas so recebe o laudo em que for
 * nomeado. Ligar "receber todos os laudos" e o que difunde — a partir dai todo
 * laudo da clinica libera e avisa esse veterinario.
 */

export function toggleClinicLink(
  links: PortalPartnerClinicLinkPayload[],
  clinicaId: number,
): PortalPartnerClinicLinkPayload[] {
  const jaVinculada = links.some((link) => link.clinica_id === clinicaId);
  if (jaVinculada) {
    return links.filter((link) => link.clinica_id !== clinicaId);
  }
  return [...links, { clinica_id: clinicaId, receber_todos_laudos: false }];
}

export function toggleClinicBroadcast(
  links: PortalPartnerClinicLinkPayload[],
  clinicaId: number,
): PortalPartnerClinicLinkPayload[] {
  return links.map((link) =>
    link.clinica_id === clinicaId
      ? { ...link, receber_todos_laudos: !link.receber_todos_laudos }
      : link,
  );
}

export function clinicLinksFromPartner(
  links: PortalPartnerClinicLink[] | null | undefined,
): PortalPartnerClinicLinkPayload[] {
  return (links || []).map((link) => ({
    clinica_id: link.clinica_id,
    receber_todos_laudos: Boolean(link.receber_todos_laudos),
  }));
}

/**
 * Payload de `clinicas_vinculadas`. `undefined` para parceiro do tipo clinica,
 * que nao tem esse vinculo — e o que faz o backend deixar os vinculos intactos.
 */
export function buildClinicLinksPayload(
  tipo: string,
  links: PortalPartnerClinicLinkPayload[],
): PortalPartnerClinicLinkPayload[] | undefined {
  if (tipo !== "veterinario") {
    return undefined;
  }
  return links.map((link) => ({
    clinica_id: link.clinica_id,
    receber_todos_laudos: Boolean(link.receber_todos_laudos),
  }));
}

export function resumoDoVinculo(link: PortalPartnerClinicLink): string {
  return link.receber_todos_laudos
    ? "Recebe todo laudo desta clínica por WhatsApp e email."
    : "Atende nesta clínica, mas só recebe o laudo em que for nomeado.";
}
