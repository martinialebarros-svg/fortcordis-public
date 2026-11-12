import { describe, expect, it } from "vitest";
import {
  criarEcocardiogramaEstruturadoInicial,
  criarQualitativaEcoLegadaVazia,
  resolverTextoClinicoNaEdicao,
} from "./ecocardiograma-estruturado";

describe("resolverTextoClinicoNaEdicao", () => {
  const qualitativaSalva = {
    ...criarQualitativaEcoLegadaVazia(),
    funcao: "Funcao revisada pelo veterinario.",
  };
  const estruturado = {
    ...criarEcocardiogramaEstruturadoInicial(),
    usar_no_laudo: true,
    textos: {
      funcao_diastolica: "Texto estruturado anterior.",
      conclusao: "Conclusao estruturada anterior.",
    },
  };

  it("preserva a analise revisada ao salvar apenas medidas ou referencias", () => {
    expect(
      resolverTextoClinicoNaEdicao(
        estruturado,
        qualitativaSalva,
        "Conclusao revisada pelo veterinario.",
        { qualitativa: false, conclusao: false }
      )
    ).toEqual({
      qualitativa: qualitativaSalva,
      conclusao: "Conclusao revisada pelo veterinario.",
    });
  });

  it("usa os campos estruturados quando a analise e aplicada explicitamente", () => {
    const resultado = resolverTextoClinicoNaEdicao(
      estruturado,
      qualitativaSalva,
      "Conclusao revisada pelo veterinario.",
      { qualitativa: true, conclusao: true }
    );
    expect(resultado.qualitativa.funcao).toBe("Texto estruturado anterior.");
    expect(resultado.conclusao).toBe("Conclusao estruturada anterior.");
  });

  it("nao substitui a conclusao revisada ao editar apenas um achado", () => {
    const resultado = resolverTextoClinicoNaEdicao(
      estruturado,
      qualitativaSalva,
      "Conclusao revisada pelo veterinario.",
      { qualitativa: true, conclusao: false }
    );
    expect(resultado.qualitativa.funcao).toBe("Texto estruturado anterior.");
    expect(resultado.conclusao).toBe("Conclusao revisada pelo veterinario.");
  });
});
