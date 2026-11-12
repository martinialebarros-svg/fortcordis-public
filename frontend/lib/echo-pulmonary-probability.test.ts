import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  caninePulmonaryProbability, evaluatePulmonaryProbability, HP_CONTEXT_KEYS,
  hasValidPulmonaryReview, invalidatePulmonaryReview, makePulmonaryReviewStamp,
  normalizePulmonaryStoredValue,
} from "./echo-pulmonary-probability";

type Case = { name: string; species: string; measurements: Record<string, string>; reviewed: boolean; expected: Record<string, unknown> };
const cases = JSON.parse(readFileSync(resolve(process.cwd(), "../backend/tests/fixtures/echo_pulmonary_probability.json"), "utf8")) as Case[];
const base = { HP_ativa: "sim", HP_TRV: "adequado", HP_VSVD: "sem_obstrucao", HP_ventriculos: "sem_sinais", HP_arteria_pulmonar: "sem_sinais", HP_atrio_cava: "sem_sinais", HP_suporte_automatico: "sim", IT_Vmax: "3" };

describe("ACVIM pulmonary probability shared clinical cases", () => {
  it("invalidates review when the effective unit ambiguity changes through other diameters", () => {
    const source = { ...base, AP: "2.2", Ao_nivel_AP: "20", unidade_confirmada_Ao_nivel_AP: "mm", DIVEd: "2.2", SIVd: "1.2", PLVEd: "1.2" };
    const reviewed = { ...source, HP_revisao: makePulmonaryReviewStamp(source, "Canina") };
    const changed = { ...reviewed, DIVEd: "22", SIVd: "12", PLVEd: "12" };
    expect(hasValidPulmonaryReview(changed, "Canina")).toBe(false);
    const changedReview = { ...changed, HP_revisao: makePulmonaryReviewStamp(changed, "Canina") };
    expect(hasValidPulmonaryReview({ ...changedReview, DIVEd: "2.2", SIVd: "1.2", PLVEd: "1.2" }, "Canina")).toBe(false);
    const legacy = JSON.parse(reviewed.HP_revisao); legacy[2].pop();
    expect(hasValidPulmonaryReview({ ...reviewed, HP_revisao: JSON.stringify(legacy) }, "Canina")).toBe(false);
  });
  it("requires a fresh review after unit confirmation, without double conversion", () => {
    const source = { ...base, HP_ventriculos: "com_sinais", AP: "2.2", Ao_nivel_AP: "20", unidade_confirmada_Ao_nivel_AP: "mm", DIVEd: "2.2", SIVd: "1.2", PLVEd: "1.2" };
    const stamp = makePulmonaryReviewStamp(source, "Canina");
    expect(evaluatePulmonaryProbability({ ...source, HP_revisao: stamp }, "Canina").metrics.ap_ao).toBeNull();
    const confirmed = { ...source, unidade_confirmada_AP: "cm", HP_revisao: stamp };
    expect(hasValidPulmonaryReview(confirmed, "Canina")).toBe(false);
    const result = evaluatePulmonaryProbability({ ...confirmed, HP_revisao: makePulmonaryReviewStamp(confirmed, "Canina") }, "Canina");
    expect(result.metrics.ap_ao).toBeCloseTo(1.1);
    expect(result.status).toBe("pending");
    expect(confirmed.AP).toBe("2.2");
  });
  it.each(["0x10", "3_2", "Infinity", "true"])("does not broaden the accepted diameter syntax: %s", (AP) => {
    const source = { ...base, AP, Ao_nivel_AP: "20" };
    expect(evaluatePulmonaryProbability({ ...source, HP_revisao: makePulmonaryReviewStamp(source, "Canina") }, "Canina").metrics.ap_ao).toBeNull();
  });
  it.each(cases)("$name", ({ species, measurements, reviewed, expected }) => {
    const m = { ...measurements, ...(reviewed ? { HP_revisao: makePulmonaryReviewStamp(measurements, species) } : {}) };
    const before = JSON.stringify(m);
    const result = evaluatePulmonaryProbability(Object.freeze(m), species);
    const comparable = structuredClone(expected);
    const metrics = comparable.metrics as Record<string, unknown> | undefined;
    if (metrics && typeof metrics.ap_ao === "number") {
      expect(result.metrics.ap_ao).toBeCloseTo(metrics.ap_ao, 9);
      delete metrics.ap_ao;
    }
    expect(result).toMatchObject(comparable);
    expect(JSON.stringify(m)).toBe(before);
  });

  it("normalizes the same JSON-array stamp across species aliases and numeric formats", () => {
    const m = { ...base, IT_Vmax: "3,0", HP_RPAD: "0" };
    const stamp = makePulmonaryReviewStamp(m, "Cão");
    const parsed = JSON.parse(stamp);
    expect(parsed[0]).toBe("acvim2020-v1");
    expect(parsed[1]).toBe("Canina");
    expect(parsed[2].map((pair: unknown[]) => pair[0])).toEqual([...HP_CONTEXT_KEYS, "unidades_ambiguas_AP_Ao"]);
    expect(parsed[2].find((pair: unknown[]) => pair[0] === "IT_Vmax")).toEqual(["IT_Vmax", 3]);
    expect(parsed[2].find((pair: unknown[]) => pair[0] === "HP_RPAD")).toEqual(["HP_RPAD", 0]);
    expect(hasValidPulmonaryReview({ ...m, IT_Vmax: "3.00", HP_revisao: stamp }, "Dog")).toBe(true);
    expect(hasValidPulmonaryReview({ ...m, HP_revisao: stamp }, "Cat")).toBe(false);
  });

  it.each(HP_CONTEXT_KEYS)("requires review after changing context field %s", (key) => {
    const m = { ...base, HP_revisao: makePulmonaryReviewStamp(base, "Canina") };
    expect(hasValidPulmonaryReview({ ...m, [key]: "changed" }, "Canina")).toBe(false);
  });

  it("preserves review when only observations or unrelated measures change", () => {
    const m = { ...base, HP_revisao: makePulmonaryReviewStamp(base, "Canina"), HP_observacoes: "linha 1\nlinha 2", Onda_E: "0.5", PSAP: "41" };
    expect(hasValidPulmonaryReview(m, "Canina")).toBe(true);
    expect(invalidatePulmonaryReview(m)).toEqual({ ...m, HP_revisao: "" });
    expect(m.HP_revisao).not.toBe("");
  });

  it.each(["3.2 m/s", "3_2", "Infinity", "NaN", "0x10", "1,2,3"])("rejects nonclinical TRV numeric syntax %s", (IT_Vmax) => {
    const m = { ...base, IT_Vmax };
    expect(evaluatePulmonaryProbability({ ...m, HP_revisao: makePulmonaryReviewStamp(m, "Canina") }, "Canina").status).toBe("pending");
    expect(JSON.parse(makePulmonaryReviewStamp(m, "Canina"))[2].find((p: unknown[]) => p[0] === "IT_Vmax")[1]).toBe(IT_Vmax);
  });

  it("retains raw notes, zero and explicit blank; rejects imported decisions with invalid values", () => {
    expect(normalizePulmonaryStoredValue("HP_observacoes", "linha 1\nlinha 2")).toBe("linha 1\nlinha 2");
    expect(normalizePulmonaryStoredValue("HP_RPAD", 0)).toBe("0");
    expect(normalizePulmonaryStoredValue("HP_RPAD", "")).toBe("");
    expect(normalizePulmonaryStoredValue("HP_TRV", "maybe")).toBeNull();
    expect(normalizePulmonaryStoredValue("HP_revisao", "{\"approved\":true}")).toBeNull();
    expect(normalizePulmonaryStoredValue("HP_probability", "alta")).toBeNull();
  });

  it("counts all PA support findings as a single anatomical site, never four sites", () => {
    const sample = cases.find((c) => c.name === "all-pa-metrics-count-once")!;
    const m = { ...sample.measurements, HP_revisao: makePulmonaryReviewStamp(sample.measurements, "Canina") };
    const result = evaluatePulmonaryProbability(m, "Canina");
    expect(result.suggestions).toHaveLength(1);
    expect(result.suggestions[0].reasons).toHaveLength(4);
    expect(result.positive_sites).toEqual(["arteria_pulmonar"]);
  });

  it("does not trust a caller-provided probability or alter conclusion", () => {
    const m = { ...base, HP_probability: "alta", conclusao: "Texto do examinador", HP_revisao: makePulmonaryReviewStamp(base, "Canina") };
    expect(evaluatePulmonaryProbability(m, "Canina").probability).toBe("baixa");
    expect(m.conclusao).toBe("Texto do examinador");
  });

  it("rejects malformed/forged review stamps", () => {
    for (const stamp of ["", "[]", "{}", "null", "[\"acvim2020-v1\",\"Canina\",[]]", makePulmonaryReviewStamp(base, "Canina").replace('3]', 'true]')]) {
      expect(hasValidPulmonaryReview({ ...base, HP_revisao: stamp }, "Canina")).toBe(false);
    }
  });

  it.each([-1, 4, 1.2, NaN])("rejects impossible anatomical site counts %s", (count) => {
    expect(() => caninePulmonaryProbability(3.2, count)).toThrow();
  });
});
