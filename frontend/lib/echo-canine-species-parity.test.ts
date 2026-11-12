import { describe, expect, it } from "vitest";
import type { ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { calculateCanine2DNormalizedLVIDd } from "./echo-2d-reference";
import { buildEchoReportGroups, canineAeAoClinicalReference, prepareEchoReportMeasurements } from "./echo-report-presentation";
import { resolveEchoReferenceForMeasurements } from "./echo-reference-policy";

// Contract copied independently from backend normalizar_especie_referencia;
// patient/catalog labels themselves must stay unchanged.
const canineAliases = ["Canina", "canino", "CANINOS", "Canine", " Cão ", "cães", "cachorro", "cachorros", "Dog", "DOGS"];
const nonCanine = ["CaninaXYZ", "caniniforme", "canino/gato", "caninos extras", "Dogfish", "Cattle", "Felina", "Gato", "Cat", "Equina", ""];
const mMode = Object.freeze({ DIVEd: "47.19", DIVEd_normalizado: "1.964", VE_tecnica_relatorio: "modo_m" });
const twoD = Object.freeze({ DIVEd_2D: "30", DIVES_2D: "18", DeltaD_FS_2D: "40", VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_curto" });
const aeAo = Object.freeze({ AE_Ao: "1.41", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" });

describe("paridade canina exata entre projeção e contrato do PDF", () => {
  it.each(canineAliases)("recalcula Cornell M para o alias %s sem alterar o registro", (species) => {
    const result = prepareEchoReportMeasurements(mMode, 13.9, species, "2 anos");
    expect(result.measurements.DIVEd_normalizado).toBe("2.18");
    expect(result.alerts).toEqual([{ key: "DIVEd_normalizado", recorded: 1.964, calculated: 2.18 }]);
    expect(mMode).toEqual({ DIVEd: "47.19", DIVEd_normalizado: "1.964", VE_tecnica_relatorio: "modo_m" });
  });

  it.each(canineAliases)("preserva confirmação e independência ponderal de AE/Ao em %s", (species) => {
    for (const method of ["2d_eixo_curto_diastole_inicial", "2d_eixo_curto_diastole_inicial_sueco"]) {
      const measurements = { ...aeAo, AE_Ao_metodo: method };
      expect(canineAeAoClinicalReference(measurements, species)).toBe("<1,60 (2D, eixo curto)");
      const row = buildEchoReportGroups(measurements, null, new Set(), undefined, species)
        .flatMap((group) => group.rows).find((item) => item.key === "AE_Ao");
      expect(row).toMatchObject({ value: "1.41", reference: "<1,60 (2D, eixo curto)" });
    }
    expect(canineAeAoClinicalReference({ ...aeAo, AE_Ao_metodo: "" }, species)).toBeNull();
    expect(canineAeAoClinicalReference({ ...aeAo, AE_Ao_metodo: "outro" }, species)).toBeNull();
    expect(canineAeAoClinicalReference(aeAo, species, new Set(["Aorta"]))).toBeNull();
    expect(aeAo).toEqual({ AE_Ao: "1.41", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" });
  });

  it.each(canineAliases)("mantém Visser 2D e suas guardas para %s", (species) => {
    expect(calculateCanine2DNormalizedLVIDd(30, 10, "eixo_curto", species, "2 anos")).toBe(1.45);
    expect(prepareEchoReportMeasurements(twoD, 10, species, "2 anos").measurements.DIVEd_normalizado_2D).toBe("1.45");
    expect(calculateCanine2DNormalizedLVIDd(30, 10, "eixo_curto", species, "7m")).toBeNull();
    expect(calculateCanine2DNormalizedLVIDd(30, 2.59, "eixo_curto", species, "2 anos")).toBeNull();
    expect(calculateCanine2DNormalizedLVIDd(30, 67.81, "eixo_curto", species, "2 anos")).toBeNull();
    expect(calculateCanine2DNormalizedLVIDd(30, 10, "", species, "2 anos")).toBeNull();
    const reference = { id: 1, especie: species, peso_kg: 10 } as ReferenciaEco;
    const original = structuredClone(reference);
    const rows = buildEchoReportGroups(twoD, reference, new Set(), 10, species, "2 anos").flatMap((group) => group.rows);
    const canonical = buildEchoReportGroups(twoD, { ...reference, especie: "Canina" }, new Set(), 10, "Canina", "2 anos").flatMap((group) => group.rows);
    for (const key of ["DIVEd_2D", "DIVES_2D", "DeltaD_FS_2D"]) {
      expect(rows.find((row) => row.key === key)?.reference).toBe(canonical.find((row) => row.key === key)?.reference);
      expect(rows.find((row) => row.key === key)?.reference).not.toBe("—");
    }
    expect(reference).toEqual(original);
    expect(buildEchoReportGroups(twoD, reference, new Set(), 10, species, "7m").flatMap((group) => group.rows)
      .find((row) => row.key === "DIVEd_2D")?.reference).toBe("—");
    expect(buildEchoReportGroups(twoD, reference, new Set(["DIVEd_2D"]), 10, species, "2 anos").flatMap((group) => group.rows)
      .find((row) => row.key === "DIVEd_2D")?.reference).toBe("—");
  });

  it.each(canineAliases)("aplica a mesma política de assinatura legada ao catálogo %s", (species) => {
    const reference = { id: 1, especie: species, peso_kg: 10,
      mv_e_min: 0.5, mv_e_max: 1.09, mv_a_min: 0.3, mv_a_max: 0.8, mv_dt_min: 0, mv_dt_max: 160,
      lvid_d_min: 20, lvid_d_max: 40 } as ReferenciaEco;
    const before = structuredClone(reference);
    const result = resolveEchoReferenceForMeasurements(reference, {}, 10)!;
    expect(result).toMatchObject({ especie: species, mv_e_min: null, mv_e_max: null, mv_a_min: null,
      mv_a_max: null, mv_dt_min: null, mv_dt_max: null, lvid_d_min: 20, lvid_d_max: 40 });
    expect(resolveEchoReferenceForMeasurements({ ...reference, mv_e_min: 0.6, mv_e_max: 1.3 }, {}, 10)?.mv_e_min).toBe(0.6);
    expect(reference).toEqual(before);
  });

  it.each(nonCanine)("não empresta fórmulas/limiar caninos a %s", (species) => {
    expect(prepareEchoReportMeasurements(mMode, 13.9, species, "2 anos").measurements.DIVEd_normalizado).toBeUndefined();
    expect(canineAeAoClinicalReference(aeAo, species)).toBeNull();
    expect(calculateCanine2DNormalizedLVIDd(30, 10, "eixo_curto", species, "2 anos")).toBeNull();
    const rows = buildEchoReportGroups({ ...twoD, ...aeAo }, { id: 1, especie: species, peso_kg: 10 } as ReferenciaEco,
      new Set(), 10, species, "2 anos").flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "AE_Ao")?.reference).toBe("—");
    expect(rows.find((row) => row.key === "DIVEd_2D")?.reference).toBe("—");
  });
});
