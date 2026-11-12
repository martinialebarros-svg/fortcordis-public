import { describe, expect, it } from "vitest";
import type { ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { resolveEchoReferenceForMeasurements, selectEchoReferenceFromCatalog } from "./echo-reference-policy";
import { buildEchoReportGroups } from "./echo-report-presentation";
import { compararMedidasComReferencia } from "@/app/laudos/hooks/useReferenciaEco";

const row = (weight = 3): ReferenciaEco => ({ id: 7, especie: "Canina", peso_kg: weight,
  lvid_d_min: 20, lvid_d_max: 30, catalog_ranges: { lvid_d: { min: 20, max: 30 } },
  catalog_weight_min: weight, catalog_weight_max: weight });
const resolve = (reference: ReferenciaEco | null, weight: number, age?: string, mode = "modo_m") =>
  resolveEchoReferenceForMeasurements(reference, { VE_tecnica_relatorio: mode }, weight, age);

describe("referências calculadas para baixo peso sem catálogo suficiente", () => {
  it("cria carrier calculado no catálogo vazio e calcula seis M para cão adulto", () => {
    const selected = selectEchoReferenceFromCatalog([], 2, "Canina", "2 anos");
    expect(selected).toMatchObject({ id: 0, especie: "Canina", reference_origin: "computed", catalog_ranges: {} });
    const resolved = resolve(selected, 2, "2 anos")!;
    expect(resolved.lvid_d_min).toBeCloseTo(10 * 1.02 * 2 ** .332, 2);
    expect(resolved.lvid_d_max).toBeCloseTo(10 * 1.57 * 2 ** .332, 2);
    for (const prefix of ["lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s"]) {
      expect(resolved.range_metadata?.[prefix]).toMatchObject({ status: "published", model_weight_kg: 2 });
    }
    expect(resolved.ao_min ?? null).toBeNull();
    expect(resolved.tapse_min ?? null).toBeNull();
  });

  it("preenche só faixas M ausentes por cobertura sem alterar catálogo original", () => {
    const raw = row(); const before = structuredClone(raw);
    const selected = selectEchoReferenceFromCatalog([raw], 2, "Canina", "2 anos");
    const resolved = resolve(selected, 2, "2 anos")!;
    expect(resolved.lvid_d_min).toBeCloseTo(12.84, 2);
    expect(resolved.catalog_ranges?.lvid_d).toEqual({ min: 20, max: 30 });
    expect(raw).toEqual(before);
  });

  it("preserva intervalo customizado já elegível", () => {
    const custom = { ...row(2.5), lvid_d_min: 11, lvid_d_max: 22, catalog_ranges: { lvid_d: { min: 11, max: 22 } } };
    const resolved = resolve(selectEchoReferenceFromCatalog([custom], 2.5, "Canina", "2 anos"), 2.5, "2 anos")!;
    expect([resolved.lvid_d_min, resolved.lvid_d_max]).toEqual([11, 22]);
  });

  it("trata placeholder 0/0 como ausente sem substituir um intervalo customizado 0/10", () => {
    const placeholder = { ...row(2.5), lvid_d_min: 0, lvid_d_max: 0, catalog_ranges: { lvid_d: { min: 0, max: 0 } } };
    const resolved = resolve(selectEchoReferenceFromCatalog([placeholder], 2.5, "Canina", "2 anos"), 2.5, "2 anos")!;
    expect(resolved.lvid_d_min).toBeGreaterThan(0);
    const custom = { ...placeholder, lvid_d_max: 10, catalog_ranges: { lvid_d: { min: 0, max: 10 } } };
    expect(resolve(selectEchoReferenceFromCatalog([custom], 2.5, "Canina", "2 anos"), 2.5, "2 anos"))
      .toMatchObject({ lvid_d_min: 0, lvid_d_max: 10 });
  });

  it("mantém estimativa de peso abaixo de 1,5 fora dos limites comparáveis", () => {
    const resolved = resolve(selectEchoReferenceFromCatalog([], 1, "Dog", "2 anos"), 1, "2 anos")!;
    expect(resolved).not.toBeNull();
    expect(resolved.lvid_d_min).toBeNull();
    expect(resolved.lvid_d_max).toBeNull();
    expect(resolved.range_metadata?.lvid_d).toMatchObject({ status: "estimated", estimate_min: 10.2,
      estimate_max: 15.7, estimate_context: "weight_extrapolation", model_weight_kg: 1 });
  });

  it("sem idade usa estimativa adulta neutra e não cria comparação automática", () => {
    const resolved = resolve(selectEchoReferenceFromCatalog([], 2, "Canina"), 2)!;
    expect(resolved).not.toBeNull();
    expect(resolved.lvid_d_min).toBeNull();
    expect(resolved.range_metadata?.lvid_d).toMatchObject({ status: "estimated", estimate_context: "age_unconfirmed" });
    const comp = compararMedidasComReferencia({ DIVEd: "30", VE_tecnica_relatorio: "modo_m" }, resolved, "", 2).DIVEd;
    expect(comp).toMatchObject({ status: "nao_avaliado", referencia_min: null, referencia_max: null });
    expect(comp.referencia_texto).toContain("estimativa");
  });

  it.each(["7m", "10 meses", "juvenil", "filhote"])("paciente em crescimento %s não recebe faixa adulta nem estimativa", (age) => {
    const resolved = resolve(selectEchoReferenceFromCatalog([], 2, "Canina", age), 2, age)!;
    expect(resolved).not.toBeNull();
    expect(resolved.lvid_d_min).toBeNull();
    expect(resolved.range_metadata?.lvid_d).toMatchObject({ status: "unavailable" });
    expect(resolved.range_metadata?.lvid_d).not.toHaveProperty("estimate_min");
  });

  it("recalcula no peso atual e não recupera modelo após voltar para 3 kg", () => {
    const initial = resolve(selectEchoReferenceFromCatalog([], 2, "Canina", "2 anos"), 2, "2 anos")!;
    const changed = resolve(initial, 2.5, "2 anos")!;
    expect(changed).not.toBeNull();
    expect(changed.range_metadata?.lvid_d.model_weight_kg).toBe(2.5);
    expect(changed.patient_weight_kg).toBe(2.5);
    expect(changed.lvid_d_min).not.toBe(initial.lvid_d_min);
    const outside = resolve(changed, 3, "2 anos")!;
    expect(outside.lvid_d_min).toBeNull();
    expect(outside.range_metadata?.lvid_d).not.toHaveProperty("estimate_min");
  });

  it("arredonda a interpolação felina pelo mesmo half-up de duas casas do backend", () => {
    const result = resolve(selectEchoReferenceFromCatalog([], 1.5625, "Cat", "2 anos"), 1.5625, "2 anos")!;
    expect(result.lvid_d_max).toBe(15.13);
    expect(result.range_metadata?.lvid_d).toMatchObject({ calculation: "interpolated", statistic: "interpolated_prediction_limits_95" });
  });

  it("não aplica as faixas M na técnica 2D nem estende a fonte 2D abaixo de 2,6", () => {
    const reference = selectEchoReferenceFromCatalog([], 2.7, "Canina", "2 anos")!;
    const resolved = resolve(reference, 2.7, "2 anos", "2d")!;
    expect(resolved).not.toBeNull();
    expect(resolved.lvid_d_min).toBeNull();
    const rows = buildEchoReportGroups({ DIVEd_2D: "20", VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_curto" }, null, new Set(), 2.7, "Canina", "2 anos")
      .flatMap((group) => group.rows);
    expect(rows.find((item) => item.key === "DIVEd_2D")?.reference).not.toBe("—");
    const below = buildEchoReportGroups({ DIVEd_2D: "20", VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_curto" }, null, new Set(), 2.5, "Canina", "2 anos")
      .flatMap((group) => group.rows);
    expect(below.find((item) => item.key === "DIVEd_2D")?.reference).toBe("—");
  });

  it("prévia salva com referência null exibe a estimativa sem tratar como faixa normal", () => {
    const rows = buildEchoReportGroups({ DIVEd: "20", VE_tecnica_relatorio: "modo_m" }, null, new Set(), 1, "Canina", "2 anos")
      .flatMap((group) => group.rows);
    expect(rows.find((item) => item.key === "DIVEd")?.reference).toContain("estimativa");
  });

  it.each([0, -1, NaN, Infinity, 3])( "não cria referência calculada para peso inválido/fora %s", (weight) => {
    expect(selectEchoReferenceFromCatalog([], weight, "Canina", "2 anos")).toBeNull();
  });

  it.each(["Catfish", "Cattle", "Outra"])("não classifica espécie por substring %s", (species) => {
    expect(selectEchoReferenceFromCatalog([], 2, species, "2 anos")).toBeNull();
  });
});
