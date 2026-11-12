import { describe, expect, it } from "vitest";
import { canineDiastolicReferences } from "./echo-canine-diastolic-reference";
import { echoDiastolicReferences } from "./echo-diastolic-reference";
import parityFixture from "../../backend/tests/fixtures/echo_canine_diastolic_parity.json";

type Evidence = { kind: string; statistic: string; doi: string; numeric_text: string; min?: number; max?: number };
const evidence: Record<string, Evidence> = parityFixture.evidence;
const raw = parityFixture.measurements;
const protocol = { Diastolica_metodo: "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo", Diastolica_ondas: "separadas", TDI_metodo: "canino_pw_anel_septal_choi", TDI_ondas: "separadas" };

describe("method-specific canine diastolic publication evidence", () => {
  it.each(parityFixture.cases)("shares the numerical/statistical PDF contract: $id", ({ species, protocol: acquisition, expected }) => {
    const measured = { ...raw, ...acquisition } as Record<string, string>;
    const before = { ...measured };
    const refs = canineDiastolicReferences(measured, species);
    const actual = Object.fromEntries(Object.entries(refs).map(([key, ref]) => [key, {
      kind: ref.kind, statistic: ref.statistic,
      doi: ["descriptive", "reference_interval"].includes(ref.kind) ? ref.doi : "",
      numeric_text: ["descriptive", "reference_interval"].includes(ref.kind) ? ref.text.replace(/^IR95%:\s*/, "") : "",
      ...(ref.kind === "reference_interval" ? { min: ref.min, max: ref.max } : {}),
    }]));
    expect(actual).toEqual(Object.fromEntries(Object.entries(expected).map(([key, id]) => [key, evidence[id!]])));
    expect(measured).toEqual(before);
  });

  it.each(["Canina", "canino", "CANINOS", " Canine ", "Cão", "cães", "cachorro", "Dog", "dogs"])
    ("uses exact aliases and preserves stored values: %s", (species) => {
      const measured = Object.freeze({ ...raw, ...protocol });
      expect(echoDiastolicReferences(measured, species)).toEqual(canineDiastolicReferences(measured, "Canina"));
      expect(measured.E_A).toBe("0.70");
    });
  it.each(["Caniformia", "Dogfish", "Cattle", "Caniniforme", ""])("does not use prefix inference: %s", (species) => {
    expect(canineDiastolicReferences({ ...raw, ...protocol }, species)).toEqual({});
  });
  it("only E has individual bounds and never calculates a mean ± 2SD interval", () => {
    const refs = canineDiastolicReferences({ ...raw, ...protocol }, "Canina");
    expect(refs.Onda_E).toMatchObject({ kind: "reference_interval", statistic: "reference_interval_95", min: .51, max: 1.10 });
    expect(refs.Onda_E.note).toContain("55–171 bpm");
    for (const [key, ref] of Object.entries(refs)) {
      if (key === "Onda_E") continue;
      expect(ref).not.toHaveProperty("min");
      expect(ref).not.toHaveProperty("max");
      if (ref.kind === "descriptive") expect(ref.note).toContain("não é intervalo individual");
    }
    expect(refs.E_TRIV).toMatchObject({ kind: "unconfirmed", source: "", doi: "" });
  });
  it("does not use generic annular or color TDI values as basal PW", () => {
    const refs = canineDiastolicReferences({ ...raw, ...protocol, TDI_metodo: "canino_pw_basal_lateral_wess" }, "Canina");
    expect(refs.e_doppler.text).toBe("0,1041 ± 0,0294 m/s");
    expect(refs.a_doppler.text).toBe("0,0906 ± 0,0247 m/s");
    expect(refs.e_doppler.note).toContain("amostra de 5 mm");
    expect(refs.e_doppler.note).toContain("segmento basal lateral");
    expect(refs.E_E_linha.kind).toBe("unconfirmed");
    expect(refs.doppler_tecidual_relacao.kind).toBe("unconfirmed");
    expect(canineDiastolicReferences({ ...raw, ...protocol, TDI_metodo: "color_lateral" }, "Canina").e_doppler.kind).toBe("unconfirmed");
  });
  it("leaves no-value, invalid and conflicting species cases unresolved", () => {
    expect(canineDiastolicReferences({ ...protocol, Onda_E: "Infinity", Onda_A: "-1", TD: "not numeric" }, "Canina")).toEqual({});
    const refs = canineDiastolicReferences({ ...protocol, MV_E: "0,8", Onda_E: "0.47", IVRT: "85", TDI_a: "0.12" }, "Cão");
    expect(refs.Onda_E.kind).toBe("reference_interval");
    expect(refs.TRIV.kind).toBe("descriptive");
    expect(refs.a_doppler.kind).toBe("descriptive");
    expect(echoDiastolicReferences({ Onda_E: "0.8", ...protocol }, "Felina").Onda_E.kind).toBe("unconfirmed");
  });
});
