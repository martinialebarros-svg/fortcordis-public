import { describe, expect, it } from "vitest";
import type { ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { compararMedidasComReferencia } from "@/app/laudos/hooks/useReferenciaEco";
import { canonicalPediatricMeasurement, felinePediatricAgeWeeks, felinePediatricReference, FELINE_PEDIATRIC_PROTOCOL } from "./echo-feline-pediatric-reference";
import { resolveEchoReferenceForMeasurements, selectEchoReferenceFromCatalog } from "./echo-reference-policy";
import { buildEchoReportGroups } from "./echo-report-presentation";
import { parseStoredEchoMeasurements } from "./echo-derived-measurements";

const protocol = { Pediatria_protocolo: FELINE_PEDIATRIC_PROTOCOL, VE_tecnica_relatorio: "modo_m", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" };
const adultCatalog: ReferenciaEco = { id: 7, especie: "Felina", peso_kg: 2, lvid_d_min: 10.2, lvid_d_max: 16,
  fs_min: 28, fs_max: 62, fs_source: "Häggström et al. 2016", la_ao_min: 0.85, la_ao_max: 1.4,
  range_metadata: { fs: { status: "published", candidate_min: 28, candidate_max: 62, source: "Häggström et al. 2016" },
    la_ao: { status: "published", candidate_min: 0.85, candidate_max: 1.4, required_measurement_key: "AE_Ao_metodo", required_measurement_value: "2d_eixo_curto_diastole_inicial" } } };
const resolve = (reference: ReferenciaEco = adultCatalog, age = "3 meses", weight = 2, measurements = protocol) =>
  resolveEchoReferenceForMeasurements(reference, measurements, weight, age)!;

describe("coorte pediátrica felina sem limites automáticos", () => {
  it("usa as colunas RI do suplemento, com cm convertidos em mm e fonte correta", () => {
    const reference = felinePediatricReference("Gato", 1.2, "3 meses", protocol)!;
    expect(reference).toMatchObject({ doi: "10.1177/1098612X20946461", min_age_weeks: 6, max_age_weeks: 16 });
    expect(Object.keys(reference.ranges)).toHaveLength(18);
    const expected = { DIVEd: [8.6, 15.3], DIVES: [2.8, 8.4], SIVd: [2.1, 4.5], SIVs: [3.7, 7.2],
      PLVEd: [2, 4.5], PLVES: [3.8, 7.4], DeltaD_FS: [36.6, 68.6], Aorta: [4.7, 7.8],
      Atrio_esquerdo: [6.3, 10.6], AE_Ao: [1.12, 1.63], Vmax_aorta: [0.72, 1.39], Vmax_pulmonar: [0.53, 1.35] };
    for (const [key, bounds] of Object.entries(expected)) {
      expect(reference.ranges[key]).toMatchObject({ lower: bounds[0], upper: bounds[1], status: "descriptive", statistic: "published_cohort_reference_interval" });
    }
    expect(reference.ranges.DIVEd.text).toBe("8,60–15,30 mm (coorte pediátrica)");
    expect(reference.ranges.AE_Ao.text).toBe("1,12–1,63 (coorte pediátrica)");
    expect(reference.reason).toMatch(/não ajustados ao peso.*sem classificação automática/);
  });

  it("bloqueia catálogo adulto completo e suas fontes, preservando originais", () => {
    const before = structuredClone(adultCatalog);
    const result = resolve();
    for (const prefix of ["lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s", "fs", "ef", "tapse", "mapse", "ao", "la", "la_ao", "ap", "ap_ao", "vmax_ao", "vmax_pulm", "mv_e", "mv_a", "mv_ea", "mv_dt", "ivrt", "tdi_e", "tdi_a", "e_e_linha", "edv", "esv", "sv"]) {
      expect((result as unknown as Record<string, unknown>)[`${prefix}_min`]).toBeNull();
      expect(result.range_metadata?.[prefix]).toMatchObject({ status: "unavailable", candidate_min: null, candidate_max: null });
    }
    expect(result.fs_source).toBeUndefined();
    expect(result.catalog_ranges?.lvid_d).toEqual({ min: 10.2, max: 16 });
    expect(adultCatalog).toEqual(before);
    expect(resolve(result)).toEqual(result);
    expect(resolve(adultCatalog, "3 meses", 1).catalog_ranges?.lvid_d).toEqual({ min: 10.2, max: 16 });
  });

  it("catálogo vazio cria carrier pediátrico mesmo acima de 3 kg sem inventar domínio de peso", () => {
    for (const weight of [0.5, 1.2, 3, 4]) {
      const selected = selectEchoReferenceFromCatalog([], weight, "Felina", "3 meses")!;
      expect(selected).not.toBeNull();
      const result = resolve(selected, "3 meses", weight);
      expect(result.pediatric_reference?.ranges.DIVEd).toMatchObject({ lower: 8.6, upper: 15.3 });
      expect(result.lvid_d_min).toBeNull();
      expect(result.pediatric_reference).not.toHaveProperty("min_weight_kg");
    }
    expect(selectEchoReferenceFromCatalog([], 3, "Canina", "3 meses")).toBeNull();
  });

  it("mesmo valores fora do intervalo de coorte permanecem neutros na comparação e na prévia", () => {
    const m = { ...protocol, DIVEd: "99", DeltaD_FS: "99", Aorta: "9", Ao_nivel_AP: "9", Vmax_aorta: "9" };
    const reference = resolve();
    const comparisons = compararMedidasComReferencia(m, reference, "", 2);
    for (const key of ["DIVEd", "DeltaD_FS", "Aorta", "Vmax_aorta"]) {
      expect(comparisons[key]).toMatchObject({ status: "nao_avaliado", referencia_min: null, referencia_max: null, referencia_tipo: "descriptive" });
      expect(comparisons[key].referencia_texto).toContain("coorte pediátrica");
    }
    const rows = buildEchoReportGroups(m, null, new Set(), 2, "Felina", "3 meses").flatMap((group) => group.rows);
    expect(rows.find((r) => r.key === "DIVEd")?.reference).toContain("8,60–15,30");
    expect(rows.find((r) => r.key === "Ao_nivel_AP")?.reference).toBe("—");
    expect(rows.find((r) => r.key === "DIVEd")?.referenceMetadata?.kind).toBe("descriptive");
    const ambiguous = buildEchoReportGroups(m, reference, new Set(["DIVEd"]), 2, "Felina", "3 meses").flatMap((group) => group.rows);
    expect(ambiguous.find((r) => r.key === "DIVEd")?.reference).toBe("—");
  });

  it("exige protocolo e técnica explícitos, sem converter limites M para 2D", () => {
    const missing = felinePediatricReference("Felina", 1, "3 meses", {})!;
    for (const range of Object.values(missing.ranges)) expect(range).toMatchObject({ status: "requires_method", lower: null, upper: null, text: "—" });
    const twoD = felinePediatricReference("Felina", 1, "3 meses", { ...protocol, VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_longo" })!;
    expect(twoD.ranges.DIVEd.lower).toBeNull();
    const expected = { DIVEd_2D: [8.3, 14], DIVES_2D: [3.4, 8.8], SIVd_2D: [2.3, 4.4], SIVs_2D: [3.3, 7.1], PLVEd_2D: [2, 4.5], PLVES_2D: [3.4, 6.5] };
    for (const [key, bounds] of Object.entries(expected)) expect(twoD.ranges[key]).toMatchObject({ lower: bounds[0], upper: bounds[1], status: "descriptive" });
    expect(felinePediatricReference("Felina", 1, "3 meses", { ...protocol, VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_curto" })!.ranges.DIVEd_2D.lower).toBeNull();
    expect(felinePediatricReference("Felina", 1, "3 meses", { ...protocol, AE_Ao_metodo: "outro" })!.ranges.Aorta.lower).toBeNull();
  });

  it("não reutiliza coorte ao mudar idade, peso ou protocolo e nova resposta adulta restaura catálogo", () => {
    const initial = resolve();
    for (const age of ["5 semanas", "17 semanas", "filhote", "0–11 meses (estimada pelo ano)"]) {
      const result = resolve(initial, age);
      expect(result.pediatric_reference?.ranges.DIVEd).toMatchObject({ status: "unavailable", lower: null, upper: null });
      expect(result.lvid_d_min).toBeNull();
    }
    for (const weight of [0, -1, NaN, Infinity]) expect(resolve(initial, "3 meses", weight).pediatric_reference?.ranges.DIVEd.lower).toBeNull();
    expect(resolve(initial, "3 meses", 2, { ...protocol, Pediatria_protocolo: "outro" }).pediatric_reference?.ranges.DIVEd.lower).toBeNull();
    expect(resolve(initial, "2 anos", 4).pediatric_reference).toBeUndefined();
    // A context change never fabricates published adult metadata from raw bounds.
    expect(resolve(initial, "2 anos", 4).lvid_d_min).toBeNull();
    expect(resolve(adultCatalog, "2 anos").lvid_d_min).toBe(10.2);
    expect(resolve(adultCatalog, "2 anos").fs_source).toContain("Häggström");
  });

  it("preserva confirmação em descrição salva e não confunde aliases com outra vista aórtica", () => {
    const stored = parseStoredEchoMeasurements(null, `## Medidas Ecocardiograficas\n- Pediatria_protocolo: ${FELINE_PEDIATRIC_PROTOCOL}\n- VE_tecnica_relatorio: modo_m\n- DIVEd: 12\n\n## Avaliacao Qualitativa`);
    expect(stored.Pediatria_protocolo).toBe(FELINE_PEDIATRIC_PROTOCOL);
    expect(canonicalPediatricMeasurement("Ao_nivel_AP")).toBe("Ao_nivel_AP");
    expect(canonicalPediatricMeasurement("LVIDd")).toBe("DIVEd");
  });
});

describe("idade pediátrica estrita", () => {
  it.each(["6 semanas", "42 dias", "6w", "16 weeks", "112 days", "3 meses", "3m (estimada)"])("aceita duração explícita %s", (age) => {
    const weeks = felinePediatricAgeWeeks(age)!;
    expect(weeks).toBeGreaterThanOrEqual(6);
    expect(weeks).toBeLessThanOrEqual(16);
  });
  it.each(["1–2 semanas", "1—2 semanas", "−3 meses", "-3 meses", "1 mes 1 mês", "1w1semana", "aproximadamente 3 meses", "0–11 meses (estimada pelo ano)", "filhote", "juvenil", "3", null, ""])("não transforma idade ambígua em número %s", (age) => {
    expect(felinePediatricAgeWeeks(age)).toBeNull();
    const resolved = resolve(adultCatalog, age as string);
    if (resolved.pediatric_reference) expect(resolved.pediatric_reference.ranges.DIVEd.lower).toBeNull();
  });
  it("as fronteiras 6 e 16 semanas são inclusivas sem arredondar idades externas", () => {
    for (const age of ["41 dias", "113 dias"]) expect(felinePediatricReference("Felina", 1, age, protocol)!.ranges.DIVEd.lower).toBeNull();
    for (const age of ["42 dias", "112 dias"]) expect(felinePediatricReference("Felina", 1, age, protocol)!.ranges.DIVEd.lower).toBe(8.6);
  });
  it.each(["1–2 meses", "1-2 meses", "1—2 meses", "6–10 semanas", "0–2 anos"])("faixa possivelmente juvenil %s bloqueia adultos sem ganhar precisão", (age) => {
    expect(felinePediatricAgeWeeks(age)).toBeNull();
    const result = resolve(adultCatalog, age);
    expect(result.pediatric_reference?.ranges.DIVEd).toMatchObject({ status: "unavailable", lower: null, upper: null });
    expect(result.lvid_d_min).toBeNull();
    const selected = selectEchoReferenceFromCatalog([], 4, "Felina", age);
    expect(selected?.pediatric_reference?.patient_age_weeks).toBeNull();
  });
  it("faixa inteiramente adulta não ativa a guarda pediátrica", () => {
    expect(resolve(adultCatalog, "1–2 anos").pediatric_reference).toBeUndefined();
    expect(resolve(adultCatalog, "1–2 anos").lvid_d_min).toBe(10.2);
  });
});
