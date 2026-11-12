import { describe, expect, it } from "vitest";
import { extrairQualitativaEcoDaDescricao, montarDescricaoEcocardiograma } from "./ecocardiograma-estruturado";
import { parseStoredEchoMeasurements } from "./echo-derived-measurements";

describe("leitura da avaliação qualitativa", () => {
  it("serializa a presença canônica diastólica limpa sem perder os aliases históricos", () => {
    const aliases = { Onda_E: "MV_E", Onda_A: "MV_A", E_A: "MV_E_A", TD: "MV_DT", TRIV: "IVRT",
      E_TRIV: "MV_E_TRIV", e_doppler: "TDI_e", a_doppler: "TDI_a", E_E_linha: "EEp", doppler_tecidual_relacao: "historico_tdi" };
    const qualitative = { valvas: "", camaras: "", funcao: "Texto preservado", pericardio: "", vasos: "", ad_vd: "" };
    for (const [key, alias] of Object.entries(aliases)) {
      for (const value of ["", null, undefined, 0, "0", "NaN"]) {
        for (const canonicalFirst of [true, false]) {
          const entries: Array<[string, unknown]> = [[key, value], [alias, "1.80"]];
          const measurements = Object.fromEntries(canonicalFirst ? entries : entries.toReversed()) as Record<string, string>;
          const before = { ...measurements };
          const description = montarDescricaoEcocardiograma(measurements, qualitative);
          expect(description).toContain(`- ${key}: ${String(value ?? "")}\n`);
          expect(description).toContain(`- ${alias}: 1.80\n`);
          expect(parseStoredEchoMeasurements(null, description)).toHaveProperty(key, String(value ?? ""));
          expect(extrairQualitativaEcoDaDescricao(description).funcao).toBe("Texto preservado");
          expect(measurements).toEqual(before);
        }
      }
    }
    expect(montarDescricaoEcocardiograma({ DIVEd: "" }, qualitative)).not.toContain("- DIVEd:");
  });

  it("preserva vários itens no mesmo grupo sem confundir bullets com novos campos", () => {
    const descricao = montarDescricaoEcocardiograma({}, {
      valvas: "- Valva mitral: espessamento discreto.\n- Valva tricúspide: refluxo discreto.",
      camaras: "- Átrio esquerdo: sem aumento.",
      funcao: "",
      pericardio: "Sem derrame pericárdico.",
      vasos: "",
      ad_vd: "",
    });
    const parsed = extrairQualitativaEcoDaDescricao(`${descricao}\n## Outra seção\n- vasos: conteúdo externo`);
    expect(parsed.valvas).toBe("- Valva mitral: espessamento discreto.\n- Valva tricúspide: refluxo discreto.");
    expect(parsed.camaras).toBe("- Átrio esquerdo: sem aumento.");
    expect(parsed.pericardio).toBe("Sem derrame pericárdico.");
    expect(parsed.vasos).toBe("");
  });

  it("aceita o título acentuado e não inventa achados quando a seção falta", () => {
    expect(extrairQualitativaEcoDaDescricao("## Avaliação Qualitativa\n- valvas: Sem alteração descrita.").valvas)
      .toBe("Sem alteração descrita.");
    expect(extrairQualitativaEcoDaDescricao("## Medidas Ecocardiograficas\n- valvas: texto fora de seção").valvas)
      .toBe("");
  });
});
