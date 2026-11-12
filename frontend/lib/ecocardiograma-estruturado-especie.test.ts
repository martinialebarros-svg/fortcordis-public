import { describe, expect, it } from "vitest";

import {
  criarEcocardiogramaEstruturadoInicial,
  removerPresetDiastolicoFelino,
  temPresetDiastolicoFelinoAplicado,
} from "./ecocardiograma-estruturado";

describe("troca de espécie após preset diastólico felino", () => {
  it("remove somente a descrição felina e preserva os demais achados", () => {
    const estado = {
      ...criarEcocardiogramaEstruturadoInicial(),
      usar_no_laudo: true,
      preset_id: 81,
      preset_label: "Função diastólica felina: padrão restritivo",
      preset_textos: { funcao_diastolica: "Padrão restritivo." },
      textos: { funcao_diastolica: "Padrão restritivo.", ventriculo_esquerdo: "Hipertrofia." },
    };

    expect(temPresetDiastolicoFelinoAplicado(estado)).toBe(true);
    const proximo = removerPresetDiastolicoFelino(estado);
    expect(proximo.textos).toEqual({ ventriculo_esquerdo: "Hipertrofia." });
    expect(proximo.preset_textos).toEqual({});
    expect(proximo.preset_id).toBeNull();
    expect(proximo.preset_label).toBe("");
    expect(proximo.usar_no_laudo).toBe(true);
  });
});
