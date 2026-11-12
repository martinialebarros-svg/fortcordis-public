import { describe, expect, it } from "vitest";

import {
  getClinicaDoLaudo,
  getConfirmacaoRevogarVeterinario,
  getRotuloOrigemVeterinario,
  getVeterinariosDoLaudo,
  temDestinosNoPortal,
} from "./laudo-portal-destinos";

const laudo = {
  status: "Liberado no portal",
  clinica: "Clinica Veterinária São Jose",
  clinic_id: 39,
  portal_clinica_liberado: true,
  veterinario_parceiro_id: 4,
  veterinario_parceiro_nome: "Dra Isadora Bastos",
  portal_veterinario_liberado: true,
  portal_veterinarios_destinos: [
    { partner_id: 4, nome: "Dra Isadora Bastos", origem: "nomeado", liberado: true },
    { partner_id: 144, nome: "Dra Camila Rebouças", origem: "vinculo_clinica", liberado: false },
  ],
};

describe("destinos do laudo no portal", () => {
  it("traz os veterinarios liberados e os que ainda faltam, com a origem de cada um", () => {
    expect(getVeterinariosDoLaudo(laudo)).toEqual([
      { partner_id: 4, nome: "Dra Isadora Bastos", origem: "nomeado", liberado: true },
      { partner_id: 144, nome: "Dra Camila Rebouças", origem: "vinculo_clinica", liberado: false },
    ]);
  });

  it("descreve a clinica e o estado dela", () => {
    expect(getClinicaDoLaudo(laudo)).toEqual({
      nome: "Clinica Veterinária São Jose",
      liberada: true,
    });
    expect(getClinicaDoLaudo({ ...laudo, clinic_id: null })).toBeNull();
  });

  it("laudo do contrato antigo cai no veterinario nomeado", () => {
    const antigo = {
      status: "Liberado no portal",
      clinica: "Animal Care",
      clinic_id: 8,
      portal_clinica_liberado: true,
      veterinario_parceiro_id: 4,
      veterinario_parceiro_nome: "Dra Isadora Bastos",
      portal_veterinario_liberado: false,
    };

    expect(getVeterinariosDoLaudo(antigo)).toEqual([
      { partner_id: 4, nome: "Dra Isadora Bastos", origem: "nomeado", liberado: false },
    ]);
  });

  it("laudo sem clinica e sem veterinario nao tem o que mostrar", () => {
    expect(
      temDestinosNoPortal({ status: "Finalizado", clinic_id: null, portal_veterinarios_destinos: [] })
    ).toBe(false);
    expect(temDestinosNoPortal(laudo)).toBe(true);
  });

  it("nomeia de onde o veterinario veio", () => {
    expect(getRotuloOrigemVeterinario("nomeado")).toBe("Encaminhou o caso");
    expect(getRotuloOrigemVeterinario("vinculo_clinica")).toBe("Por vínculo com a clínica");
    expect(getRotuloOrigemVeterinario(null)).toBe("Veterinário parceiro");
  });

  it("a confirmacao avisa que revogar nao e definitivo", () => {
    const texto = getConfirmacaoRevogarVeterinario("Dra Camila Rebouças");
    expect(texto).toContain("Dra Camila Rebouças");
    expect(texto).toContain("Liberar o laudo de novo devolve o acesso");
  });
});
