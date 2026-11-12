import { describe, expect, it } from "vitest";
import type { ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { buildEchoReferenceCatalogForm, resolveEchoReferenceForMeasurements, selectEchoReferenceFromCatalog } from "./echo-reference-policy";

const canine = {
  id: 1, especie: "Canina", peso_kg: 10, lvid_d_min: 20, lvid_d_max: 40,
  tapse_min: undefined, tapse_max: undefined,
  catalog_ranges: { tapse: { min: 7, max: 14 }, fs: { min: 25, max: 45 }, ef: { min: 50, max: 85 } },
  range_metadata: { tapse: {
    status: "requires_method", source: "Visser et al. 2015", candidate_min: 8, candidate_max: 15,
    required_measurement_key: "TAPSE_metodo", required_measurement_value: "modo_m_apical",
    min_weight_kg: 3, max_weight_kg: 45,
  } },
} as ReferenciaEco;

describe("política clínica compartilhada das faixas", () => {
  it.each(["Felina", "felino", "FELINOS", "Feline", " Gato ", "gatos", "Cat", "CATS"])
    ("seleciona somente catálogo felino e respeita seus limites para %s", (species) => {
      const feline = { id: 2, especie: "Felina", peso_kg: 5.5, lvid_d_min: 13, lvid_d_max: 21 } as ReferenciaEco;
      const rows = [canine, feline];
      expect(selectEchoReferenceFromCatalog(rows, 5.6, species)).toMatchObject({ id: 2, especie: "Felina", lvid_d_min: null });
      expect(selectEchoReferenceFromCatalog([canine], 5.6, species)).toBeNull();
      // Runtime legacy rows can carry aliases despite the canonical API type.
      const legacy = { ...feline, especie: species, la_ao_min: 0.5, la_ao_max: 1.4 } as ReferenciaEco;
      expect(resolveEchoReferenceForMeasurements(legacy, {}, 5.6)).toMatchObject({
        especie: species, la_ao_min: null, la_ao_max: null, lvid_d_min: 13, lvid_d_max: 21,
      });
      expect(resolveEchoReferenceForMeasurements(legacy, {}, 11.1)?.lvid_d_min).toBeNull();
      expect(legacy).toMatchObject({ especie: species, la_ao_min: 0.5, la_ao_max: 1.4 });
    });

  it("exige método exato e domínio do paciente sem alterar catálogo ou metadados originais", () => {
    for (const [method, weight] of [["", 10], ["2d", 10], ["modo_m_apical", 2.9], ["modo_m_apical", 45.1], ["modo_m_apical", undefined]] as const) {
      const safe = resolveEchoReferenceForMeasurements(canine, { TAPSE_metodo: method }, weight)!;
      expect(safe.tapse_min).toBeNull();
      expect(safe.tapse_max).toBeNull();
    }
    for (const weight of [3, 10, 45]) {
      expect(resolveEchoReferenceForMeasurements({ ...canine, patient_weight_kg: weight }, { TAPSE_metodo: "modo_m_apical" }, weight))
        .toMatchObject({ tapse_min: 8, tapse_max: 15, range_metadata: { tapse: { status: "published" } } });
    }
    expect(canine.range_metadata?.tapse.status).toBe("requires_method");
    expect(canine.catalog_ranges?.tapse).toEqual({ min: 7, max: 14 });
  });

  it("também suspende uma resposta publicada após mudança de método ou peso", () => {
    const published = resolveEchoReferenceForMeasurements(canine, { TAPSE_metodo: "modo_m_apical" }, 10)!;
    expect(resolveEchoReferenceForMeasurements(published, { TAPSE_metodo: "2d" }, 10)?.tapse_min).toBeNull();
    expect(resolveEchoReferenceForMeasurements(published, { TAPSE_metodo: "modo_m_apical" }, 50)?.tapse_min).toBeNull();
  });

  it("não restaura faixa bloqueada pelo servidor mesmo com método informado", () => {
    const blocked = { ...canine, range_metadata: { tapse: { ...canine.range_metadata!.tapse, status: "blocked" as const } } };
    expect(resolveEchoReferenceForMeasurements(blocked, { TAPSE_metodo: "modo_m_apical" }, 10)?.tapse_min).toBeNull();
  });

  it("protege respostas antigas sem eliminar outras faixas de catálogo", () => {
    const legacy = { ...canine, catalog_ranges: undefined, range_metadata: undefined,
      tapse_min: 7, tapse_max: 14, la_ao_min: 0.8, la_ao_max: 1.6,
      vmax_ao_min: 0, vmax_ao_max: 2.2, vmax_pulm_min: 0.4, vmax_pulm_max: 1.4,
      mv_e_min: 0.5, mv_e_max: 1.09, mv_a_min: 0.3, mv_a_max: 0.8, mv_dt_min: 0, mv_dt_max: 160,
      ivs_d_min: 4, ivs_d_max: 8,
    };
    const safe = resolveEchoReferenceForMeasurements(legacy, {}, 10)!;
    for (const prefix of ["tapse", "la_ao", "vmax_ao", "vmax_pulm", "mv_e", "mv_a", "mv_dt"]) {
      expect((safe as unknown as Record<string, unknown>)[`${prefix}_min`]).toBeNull();
    }
    expect(safe).toMatchObject({ ivs_d_min: 4, ivs_d_max: 8, lvid_d_min: 20, lvid_d_max: 40 });
    expect(resolveEchoReferenceForMeasurements({ ...legacy, mv_e_min: 0.6, mv_e_max: 1.3 }, {}, 10)?.mv_e_min).toBe(0.6);
  });

  it("edita somente números originais, sem devolver faixas substituídas ou fonte gerenciada", () => {
    const resolved = resolveEchoReferenceForMeasurements(canine, { TAPSE_metodo: "modo_m_apical" }, 10)!;
    expect(buildEchoReferenceCatalogForm(resolved, ["tapse", "lvid_d"]))
      .toEqual({ especie: "Canina", peso_kg: 10, tapse_min: 7, tapse_max: 14, lvid_d_min: 20, lvid_d_max: 40 });
  });

  it("fallback ignora linhas fora do estudo e não extrapola os extremos cadastrados", () => {
    const rows = [
      { ...canine, id: 1, peso_kg: 0.9 },
      { ...canine, id: 2, peso_kg: 5 },
      { ...canine, id: 3, peso_kg: 10 },
    ];
    expect(selectEchoReferenceFromCatalog(rows, 3, "Canina"))
      .toMatchObject({ id: 2, lvid_d_min: null, catalog_weight_min: 5, catalog_weight_max: 10 });
    expect(selectEchoReferenceFromCatalog(rows, 7.5, "Canina"))
      .toMatchObject({ id: 2, lvid_d_min: 20 });
    expect(selectEchoReferenceFromCatalog(rows, 11, "Canina")?.lvid_d_min).toBeNull();
    expect(selectEchoReferenceFromCatalog(rows, 0.9, "Canina")?.lvid_d_min).toBeNull();
    expect(selectEchoReferenceFromCatalog(rows, 7, "Felina")).toBeNull();
  });

  it("fallback não promove TAPSE resolvido no peso da linha para outro peso do paciente", () => {
    const rows: ReferenciaEco[] = [5, 15].map((weight) => ({
      ...canine, peso_kg: weight, patient_weight_kg: weight,
      range_metadata: { tapse: { ...canine.range_metadata!.tapse,
        candidate_min: weight === 5 ? 7.7 : 10.4, candidate_max: weight === 5 ? 12.3 : 16.5,
      } },
    }));
    const fallback = selectEchoReferenceFromCatalog(rows, 10, "Canina")!;
    const confirmedFallback = resolveEchoReferenceForMeasurements(fallback, { TAPSE_metodo: "modo_m_apical" }, 10)!;
    expect(confirmedFallback).toMatchObject({ tapse_min: null, tapse_max: null,
      range_metadata: { tapse: { status: "unavailable", candidate_weight_kg: 5 } } });
    expect(confirmedFallback.range_metadata!.tapse.reason).toContain("outro peso");

    const directApi = { ...rows[0], patient_weight_kg: 10,
      range_metadata: { tapse: { ...rows[0].range_metadata!.tapse, candidate_min: 9.2, candidate_max: 14.7 } },
    };
    expect(resolveEchoReferenceForMeasurements(directApi, { TAPSE_metodo: "modo_m_apical" }, 10))
      .toMatchObject({ tapse_min: 9.2, tapse_max: 14.7 });
    expect(resolveEchoReferenceForMeasurements(selectEchoReferenceFromCatalog(rows, 5, "Canina"), { TAPSE_metodo: "modo_m_apical" }, 5))
      .toMatchObject({ tapse_min: 7.7, tapse_max: 12.3 });
    expect(rows[0].range_metadata!.tapse).not.toHaveProperty("candidate_weight_kg");
  });
});
