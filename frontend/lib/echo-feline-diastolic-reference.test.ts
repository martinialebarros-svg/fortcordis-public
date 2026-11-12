import { describe, expect, it } from "vitest";
import { felineDiastolicReferences } from "./echo-feline-diastolic-reference";
import parityFixture from "../../backend/tests/fixtures/echo_feline_diastolic_parity.json";

type ContractEvidence = { kind: string; statistic: string; doi: string; numeric_text: string };
const parityCases = parityFixture.cases as Array<{
  id: string; species: string; protocol: Record<string, string>; expected: Record<string, string>;
}>;
const parityEvidence: Record<string, ContractEvidence> = parityFixture.evidence;

const skar = { Onda_E: "1.08", Onda_A: "0.95", E_A: "1.14", TD: "51", TRIV: "40", e_doppler: "0.16", a_doppler: "0.1", E_E_linha: "6.75", E_TRIV: "2.7", doppler_tecidual_relacao: "1.6" };
const protocol = { Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "separadas", TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas" };

describe("evidência descritiva diastólica felina", () => {
  it.each(["felino_adulto_nao_sedado_pw_clique_aortico", "felino_adulto_nao_sedado_pw_fim_fluxo"])
    ("não reatribui confirmação antiga à vista apical: %s", (method) => {
      const raw = { ...skar, ...protocol, Diastolica_metodo: method };
      const before = { ...raw };
      const references = felineDiastolicReferences(raw, "Gato");
      for (const key of ["Onda_E", "Onda_A", "E_A", "TD", "E_E_linha"]) {
        expect(references[key]).toMatchObject({ kind: "unconfirmed", source: "", doi: "" });
        expect(references[key].note).toContain("vista apical");
      }
      expect(references.TRIV.kind).toBe("descriptive");
      expect(references.e_doppler.kind).toBe("descriptive");
      expect(raw).toEqual(before);
    });

  it.each(["Felina", "felino", "FELINOS", "Feline", " Gato ", "gatos", "Cat", "CATS"])
    ("mantém fontes, ausência de confirmação e fusões independentes para %s", (species) => {
      const states = [
        skar,
        { ...skar, ...protocol },
        { ...skar, ...protocol, Diastolica_ondas: "fundidas" },
        { ...skar, ...protocol, TDI_ondas: "fundidas" },
        { ...skar, ...protocol, Diastolica_ondas: "", TDI_ondas: "" },
      ];
      for (const recorded of states) {
        const before = { ...recorded };
        expect(felineDiastolicReferences(recorded, species)).toEqual(felineDiastolicReferences(recorded, "Felina"));
        expect(recorded).toEqual(before);
      }
    });

  it.each(parityCases)("mantém a mesma evidência clínica da consulta e do PDF: $id", (testCase) => {
    const recorded: Record<string, string> = { ...parityFixture.measurements, ...testCase.protocol };
    const before = { ...recorded };
    const refs = felineDiastolicReferences(recorded, testCase.species);
    // Fusion bibliography/wording belongs to the view. Clinical numerical
    // descriptions, statistics, and publication identifiers are shared.
    const actual = Object.fromEntries(Object.entries(refs).map(([key, ref]) => [key, {
      kind: ref.kind,
      statistic: ref.statistic,
      doi: ref.kind === "descriptive" ? ref.doi : "",
      numeric_text: ref.kind === "descriptive" ? ref.text : "",
    }]));
    const expected = Object.fromEntries(Object.entries(testCase.expected).map(([key, id]) => [key, parityEvidence[id]]));
    expect(actual).toEqual(expected);
    expect(recorded).toEqual(before);
    for (const ref of Object.values(refs)) {
      expect(ref).not.toHaveProperty("min");
      expect(ref).not.toHaveProperty("max");
      if (ref.kind === "descriptive") {
        expect(ref.text).toContain("±");
        expect(ref.doi).not.toBe("");
      } else {
        expect(ref.text).not.toContain("±");
        expect(ref.statistic).not.toBe("mean_sd");
      }
    }
  });
  it("não transfere fontes felinas a cães ou espécies desconhecidas", () => {
    expect(felineDiastolicReferences({ ...skar, ...protocol }, "Canina")).toEqual({});
    expect(felineDiastolicReferences({ ...skar, ...protocol }, "Cattle")).toEqual({});
    expect(felineDiastolicReferences({ ...skar, ...protocol }, "Catfish")).toEqual({});
    expect(felineDiastolicReferences({ ...skar, ...protocol }, "feliniforme")).toEqual({});
  });
  it("exige confirmação e não fabrica limites individuais a partir de média/DP", () => {
    const unknown = felineDiastolicReferences(skar, "Felina");
    expect(unknown.Onda_E).toMatchObject({ kind: "unconfirmed", text: "—" });
    const refs = felineDiastolicReferences({ ...skar, ...protocol }, "Felina");
    expect(refs.Onda_E).toMatchObject({ text: "0,70 ± 0,14 m/s", statistic: "mean_sd", kind: "descriptive" });
    expect(refs.Onda_E).not.toHaveProperty("min");
    expect(refs.E_A.text).toBe("1,12 ± 0,22");
    expect(refs.TRIV.text).toBe("46,2 ± 7,6 ms");
    expect(refs.TD).toMatchObject({ text: "72,29 ± 9,56 ms", kind: "descriptive", source: "Soares et al. (2005)" });
    expect(refs.E_TRIV.kind).toBe("unconfirmed");
  });
  it("usa TRIV e TD da fonte correspondente ao fim do fluxo aórtico", () => {
    const refs = felineDiastolicReferences({ ...skar, ...protocol, Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_fim_fluxo" }, "Felina");
    expect(refs.TRIV).toMatchObject({ text: "68,75 ± 19,14 ms", source: "Soares et al. (2005)" });
    expect(refs.TD.text).toBe("72,29 ± 9,56 ms");
  });
  it("distingue fusão E/A de e'/a' e preserva velocidades e medidas originais", () => {
    const recorded = { ...skar, ...protocol, Diastolica_ondas: "fundidas" };
    const before = { ...recorded };
    const refs = felineDiastolicReferences(recorded, "Felina");
    for (const key of ["Onda_E", "Onda_A", "E_A", "TD", "E_E_linha", "E_TRIV"]) expect(refs[key].kind).toBe("uninterpretable");
    expect(refs.TRIV.kind).toBe("descriptive");
    expect(refs.e_doppler).toMatchObject({ text: "0,11 ± 0,03 m/s", kind: "descriptive" });
    expect(recorded).toEqual(before);
  });
  it("distingue TDI lateral/septal, mantém m/s e bloqueia E/e' sem separação transmitral", () => {
    const lateral = felineDiastolicReferences({ ...skar, ...protocol }, "Felina");
    expect(lateral.E_E_linha.text).toBe("7,8 ± 2,92");
    expect(lateral.e_doppler.note).toContain("20 gatos saudáveis, não sedados");
    expect(lateral.e_doppler.doi).toBe("10.1186/s12917-020-02557-3");
    expect(lateral.a_doppler.text).toBe("0,08 ± 0,03 m/s");
    expect(lateral.doppler_tecidual_relacao.text).toBe("1,33 ± 0,31");
    const septal = felineDiastolicReferences({ ...skar, ...protocol, TDI_metodo: "felino_pw_anel_septal" }, "Felina");
    expect(septal.e_doppler.text).toBe("0,075 ± 0,026 m/s");
    expect(septal.doppler_tecidual_relacao).toMatchObject({ text: "—", kind: "unconfirmed", statistic: "", source: "", doi: "" });
    expect(septal.doppler_tecidual_relacao.note).toContain("Sem comparador septal reconciliado");
    expect(septal.E_E_linha.text).toBe("8,7 ± 1,7");
    expect(septal.e_doppler.note).toContain("1–3 anos");
    expect(septal.e_doppler.source).toBe("Ward et al. (2012)");
    expect(felineDiastolicReferences({ ...skar, ...protocol, Diastolica_ondas: "" }, "Felina").E_E_linha.kind).toBe("unconfirmed");
    expect(felineDiastolicReferences({ ...skar, ...protocol, Diastolica_metodo: "outro" }, "Felina").E_E_linha.kind).toBe("unconfirmed");
    const fusedTDI = felineDiastolicReferences({ ...skar, ...protocol, TDI_ondas: "fundidas" }, "Felina");
    expect(fusedTDI.Onda_E.kind).toBe("descriptive");
    expect(fusedTDI.e_doppler.kind).toBe("uninterpretable");
    expect(fusedTDI.E_E_linha.kind).toBe("uninterpretable");
  });
  it("suporta aliases antigos e rejeita valores ausentes e não finitos", () => {
    const refs = felineDiastolicReferences({ MV_E: "0,8", IVRT: "40", ...protocol }, "Felina");
    expect(refs.Onda_E.kind).toBe("descriptive");
    expect(refs.TRIV.kind).toBe("descriptive");
    expect(felineDiastolicReferences({ Onda_E: "Infinity", Onda_A: "", TD: "-1", ...protocol }, "Felina")).toEqual({});
    const fusedWithoutValues = felineDiastolicReferences({ Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" }, "Felina");
    expect(Object.keys(fusedWithoutValues)).toHaveLength(9);
    expect(Object.values(fusedWithoutValues).every((ref) => ref.kind === "uninterpretable")).toBe(true);
  });
});
