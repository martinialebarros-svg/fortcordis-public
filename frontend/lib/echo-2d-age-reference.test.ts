import { describe, expect, it } from "vitest";
import { calculateCanine2DNormalizedLVIDd, getCanine2DReference, type Echo2DView } from "./echo-2d-reference";
import { deriveAutomaticEchoMeasurements } from "./echo-derived-measurements";
import { buildEchoReportGroups, prepareEchoReportMeasurements } from "./echo-report-presentation";
import { selectEchoReferenceFromCatalog } from "./echo-reference-policy";
import { compararMedidasComReferencia } from "@/app/laudos/hooks/useReferenciaEco";

const views: Echo2DView[] = ["eixo_curto", "eixo_longo"];
const recorded = (view: Echo2DView) => ({ VE_tecnica_relatorio: "2d", VE_vista_2D: view,
  DIVEd_2D: "20", DIVES_2D: "12", DeltaD_FS_2D: "40", DIVEd_normalizado_2D: "9.99" });

describe("referência 2D adulta não prevalece sobre idade juvenil conhecida", () => {
  it.each(views)("bloqueia todos os limites/índice na vista %s, inclusive com carrier de baixo peso", (view) => {
    for (const weight of [2.6, 2.7, 2.99, 3, 10]) {
      for (const key of ["DIVEd_2D", "DIVES_2D", "DeltaD_FS_2D", "DIVEd_normalizado_2D"]) {
        expect(getCanine2DReference(key, weight, view, "7m")).toBeNull();
        expect(getCanine2DReference(key, weight, view, "2 anos")).toEqual(getCanine2DReference(key, weight, view));
      }
      expect(calculateCanine2DNormalizedLVIDd(20, weight, view, "Canina", "7m")).toBeNull();
      expect(calculateCanine2DNormalizedLVIDd(20, weight, view, "Canina", "2 anos")).not.toBeNull();
    }
  });

  it.each(views)("preserva histórico e Cornell M sem derivar/mostrar índice adulto 2D em %s", (view) => {
    const raw = { ...recorded(view), DIVEd: "20" };
    const before = structuredClone(raw);
    const derived = deriveAutomaticEchoMeasurements(raw, 2.7, "Canina", "7m");
    expect(derived).not.toHaveProperty("DIVEd_normalizado_2D");
    expect(derived.DIVEd_normalizado).toBeDefined();
    const prepared = prepareEchoReportMeasurements(raw, 2.7, "Canina", "7m");
    expect(prepared.measurements).not.toHaveProperty("DIVEd_normalizado_2D");
    const rows = buildEchoReportGroups(raw, null, new Set(), 2.7, "Canina", "7m").flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "DIVEd_normalizado_2D")).toBeUndefined();
    expect(rows.find((row) => row.key === "DIVEd_2D")?.reference).toBe("—");
    expect(raw).toEqual(before);
  });

  it.each(views)("comparação %s não classifica juvenil contra Visser e mantém controle adulto", (view) => {
    const raw = recorded(view);
    const juvenile = selectEchoReferenceFromCatalog([], 2.7, "Canina", "7m")!;
    const adult = selectEchoReferenceFromCatalog([], 2.7, "Canina", "2 anos")!;
    const comparisons = compararMedidasComReferencia(raw, juvenile, view, 2.7);
    for (const key of ["DIVEd_2D", "DIVES_2D", "DeltaD_FS_2D"]) {
      expect(comparisons[key]).toMatchObject({ status: "nao_avaliado", referencia_min: null, referencia_max: null });
      expect(comparisons[key].interpretacao).toMatch(/adult|crescimento/i);
    }
    expect(compararMedidasComReferencia(raw, adult, view, 2.7).DIVEd_2D.referencia_min).not.toBeNull();
  });

  it("mantém os limites de peso e a confirmação explícita de vista/adulto quando a idade não foi informada", () => {
    expect(getCanine2DReference("DIVEd_2D", 2.59, "eixo_curto", "2 anos")).toBeNull();
    expect(getCanine2DReference("DIVEd_2D", 2.7, "", "2 anos")).toBeNull();
    expect(getCanine2DReference("DIVEd_2D", 2.7, "eixo_curto", undefined)).not.toBeNull();
  });
});
