/**
 * Quem recebe este laudo no portal, liberado ou ainda pendente.
 *
 * O aviso por WhatsApp (`laudo-whatsapp-aviso`) so olha para quem ja esta
 * liberado, porque so esses podem ser avisados. A tela de "liberado para"
 * precisa do quadro inteiro: quem tem acesso, quem falta liberar, e por onde
 * cada veterinario entrou no laudo.
 */
import {
  PORTAL_RELEASE_STATUS,
  type DestinoVeterinarioLaudo,
  type LaudoAvisoWhatsApp,
} from "./laudo-whatsapp-aviso";

export interface VeterinarioDoLaudo {
  partner_id: number;
  nome: string;
  origem: "nomeado" | "vinculo_clinica" | null;
  liberado: boolean;
}

export interface ClinicaDoLaudo {
  nome: string;
  liberada: boolean;
}

export function getClinicaDoLaudo(laudo: LaudoAvisoWhatsApp): ClinicaDoLaudo | null {
  if (!laudo.clinic_id) {
    return null;
  }
  return {
    nome: laudo.clinica?.trim() || "Clínica parceira",
    liberada: Boolean(laudo.portal_clinica_liberado || laudo.status === PORTAL_RELEASE_STATUS),
  };
}

export function getVeterinariosDoLaudo(laudo: LaudoAvisoWhatsApp): VeterinarioDoLaudo[] {
  const destinos: DestinoVeterinarioLaudo[] | undefined = laudo.portal_veterinarios_destinos;
  if (Array.isArray(destinos)) {
    return destinos.map((item) => ({
      partner_id: item.partner_id,
      nome: item.nome?.trim() || "Veterinário parceiro",
      origem: normalizarOrigem(item.origem),
      liberado: Boolean(item.liberado),
    }));
  }

  // Contrato antigo, de antes da difusao por vinculo: so o nomeado no laudo.
  if (laudo.veterinario_parceiro_id) {
    return [
      {
        partner_id: laudo.veterinario_parceiro_id,
        nome: laudo.veterinario_parceiro_nome?.trim() || "Veterinário parceiro",
        origem: "nomeado",
        liberado: Boolean(laudo.portal_veterinario_liberado),
      },
    ];
  }
  return [];
}

export function temDestinosNoPortal(laudo: LaudoAvisoWhatsApp): boolean {
  return Boolean(getClinicaDoLaudo(laudo)) || getVeterinariosDoLaudo(laudo).length > 0;
}

export function getRotuloOrigemVeterinario(origem: VeterinarioDoLaudo["origem"]): string {
  if (origem === "vinculo_clinica") {
    return "Por vínculo com a clínica";
  }
  if (origem === "nomeado") {
    return "Encaminhou o caso";
  }
  return "Veterinário parceiro";
}

export function getConfirmacaoRevogarVeterinario(nome: string): string {
  return `Tirar o acesso de ${nome} a este laudo no portal? Liberar o laudo de novo devolve o acesso.`;
}

function normalizarOrigem(origem: string | null | undefined): VeterinarioDoLaudo["origem"] {
  if (origem === "nomeado" || origem === "vinculo_clinica") {
    return origem;
  }
  return null;
}
