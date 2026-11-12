import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { compararMedidasComReferencia, compararMedidasDiastolicas, compararMedidasDiastolicasFelinas, useReferenciaEco, useReferenciaEcoLegacy } from "./useReferenciaEco";
import { deriveLeftVentricularFunctionForReference } from "@/lib/echo-derived-measurements";
import type { ReferenciaEco } from "../types/referencia-eco";

const mockGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/axios", () => ({ default: { get: mockGet } }));

beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockResolvedValue({ data: null });
});

describe("useReferenciaEco", () => {
  it.each(["Gato", "Cat", "Felino", " Feline "])("consulta aliases felinos pelo catálogo canônico: %s", async (species) => {
    const { result } = renderHook(() => useReferenciaEco());
    await act(async () => { await result.current.buscarReferencia(species, 5.6); });
    expect(mockGet).toHaveBeenCalledWith("/referencias-eco/buscar/Felina/5.6");
  });

  it("fallback consulta Felina e encontra a linha sem alterar a espécie recebida", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    mockGet.mockRejectedValueOnce(new Error("synthetic direct failure"))
      .mockResolvedValueOnce({ data: { items: [{ id: 3, especie: "Felina", peso_kg: 5.5 }] } });
    const { result } = renderHook(() => useReferenciaEco());
    await act(async () => {
      expect(await result.current.buscarReferencia(" Cat ", 5.5)).toMatchObject({ especie: "Felina", peso_kg: 5.5 });
    });
    expect(mockGet).toHaveBeenLastCalledWith("/referencias-eco?especie=Felina");
  });

  it("envia especie sem transforma-la em referencia felina por substring", async () => {
    const { result } = renderHook(() => useReferenciaEco());
    await act(async () => {
      await result.current.buscarReferencia("Cattle", 5);
    });
    expect(mockGet).toHaveBeenCalledWith("/referencias-eco/buscar/Cattle/5");
  });

  it("nao busca referencia sem especie", async () => {
    const { result } = renderHook(() => useReferenciaEco());
    await act(async () => {
      expect(await result.current.buscarReferencia(" ", 5)).toBeNull();
    });
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("fallback de listagem mantém comparação suspensa fora da cobertura cadastrada", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    mockGet.mockRejectedValueOnce(new Error("synthetic buscar failure")).mockResolvedValueOnce({ data: { items: [
      { id: 1, especie: "Canina", peso_kg: 5, lvid_d_min: 20, lvid_d_max: 30 },
      { id: 2, especie: "Canina", peso_kg: 10, lvid_d_min: 25, lvid_d_max: 40 },
    ] } });
    const { result } = renderHook(() => useReferenciaEco());
    await act(async () => {
      expect(await result.current.buscarReferencia("Canina", 15))
        .toMatchObject({ peso_kg: 10, lvid_d_min: null, lvid_d_max: null, catalog_weight_min: 5, catalog_weight_max: 10 });
    });
  });

  it("gera carrier de baixo peso mesmo após falha de API e catálogo vazio", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    mockGet.mockRejectedValueOnce(new Error("synthetic direct failure")).mockResolvedValueOnce({ data: { items: [] } });
    const { result } = renderHook(() => useReferenciaEco());
    await act(async () => {
      expect(await result.current.buscarReferencia("Dog", 2, "2 anos"))
        .toMatchObject({ id: 0, especie: "Canina", reference_origin: "computed", patient_age: "2 anos" });
    });
  });

  it("gera carrier neutro se as duas consultas falham sem exigir confirmação adicional", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockGet.mockRejectedValue(new Error("synthetic unavailable API"));
    const { result } = renderHook(() => useReferenciaEco());
    await act(async () => {
      expect(await result.current.buscarReferencia("Canina", 1))
        .toMatchObject({ id: 0, especie: "Canina", reference_origin: "computed" });
    });
  });

  it("hook legado também bloqueia fluxos antigos e não trata null como limite zero", async () => {
    mockGet.mockResolvedValue({ data: { id: 1, especie: "Canina", peso_kg: 10, vmax_ao_min: 0, vmax_ao_max: 2.2, lvid_d_min: 20, lvid_d_max: 40 } });
    const { result } = renderHook(() => useReferenciaEcoLegacy("Canina", 10));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.getFaixaReferencia("vmax_ao")).toBe("-");
    expect(result.current.interpretarMedida(1.2, "vmax_ao").status).toBe("nao_avaliado");
    expect(result.current.interpretarMedida(30, "lvid_d").mensagem).toBe("Dentro da faixa");
  });
});

const referenciaCanina: ReferenciaEco = {
  id: 1,
  especie: "Canina",
  peso_kg: 10,
  ef_min: 55,
  ef_max: 80,
  fs_min: 28,
  fs_max: 42,
  fs_source: "Visser et al. 2019; modo M",
};

describe("compararMedidasComReferencia", () => {
  it.each(["Gato", "Cat", "Felino", " Feline "])("não classifica faixas diastólicas legadas com ondas fundidas para %s", (species) => {
    const reference: ReferenciaEco = { id: 3, especie: species as ReferenciaEco["especie"], peso_kg: 5.5,
      mv_e_min: .5, mv_e_max: 1.1, mv_ea_min: .8, mv_ea_max: 2,
      tdi_e_min: .1, tdi_e_max: .2, e_e_linha_min: 4, e_e_linha_max: 10 };
    const comparisons = compararMedidasComReferencia({ Onda_E: "1.08", E_A: "1.13", e_doppler: "0.16", E_E_linha: "6.95",
      Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "fundidas",
      TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "fundidas" }, reference, "", 5.6);
    for (const key of ["Onda_E", "E_A", "e_doppler", "E_E_linha"]) {
      expect(comparisons[key]).toMatchObject({ status: "nao_avaliado", referencia_min: null, referencia_max: null });
    }
  });

  it("suspende cores de faixas diastólicas felinas legadas e mantém estatísticas em m/s", () => {
    const legacy: ReferenciaEco = { id: 1, especie: "Felina", peso_kg: 5.5, mv_e_min: .5, mv_e_max: 1.1, tdi_e_min: 1, tdi_e_max: 20 };
    const measurements = { Onda_E: "1.08", e_doppler: "0.16", Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "separadas", TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas" };
    const comparisons = compararMedidasComReferencia(measurements, legacy, "", 5.6);
    expect(comparisons.Onda_E).toMatchObject({ status: "nao_avaliado", referencia_min: null, referencia_texto: "0,70 ± 0,14 m/s" });
    expect(comparisons.e_doppler).toMatchObject({ status: "nao_avaliado", valor_medido: "0.16", referencia_texto: "0,11 ± 0,03 m/s" });
    expect(compararMedidasComReferencia({ Onda_E: "1.08" }, legacy, "", 5.6).Onda_E.status).toBe("nao_avaliado");
    const legacyComparison = compararMedidasDiastolicasFelinas({ MV_E: "0.8", ...measurements }, "Felina");
    expect(legacyComparison.Onda_E).toMatchObject({ valor_medido: "1.08", referencia_texto: "0,70 ± 0,14 m/s" });
    expect(legacyComparison).not.toHaveProperty("MV_E");
  });
  it("compara AE/Ao felino com intervalo por peso apenas após confirmar aquisição", () => {
    const feline: ReferenciaEco = {
      id: 2, especie: "Felina", peso_kg: 4,
      range_metadata: { la_ao: {
        status: "requires_method", source: "Häggström et al. 2016", statistic: "PI95",
        candidate_min: 0.89, candidate_max: 1.42, min_weight_kg: 1.5, max_weight_kg: 11,
        required_measurement_key: "AE_Ao_metodo", required_measurement_value: "2d_eixo_curto_diastole_inicial",
        clinical_threshold: { operator: "<", value: 1.5 },
      } },
    };
    expect(compararMedidasComReferencia({ AE_Ao: "1.45" }, feline, "", 4).AE_Ao.status).toBe("nao_avaliado");
    const confirmed = compararMedidasComReferencia({ AE_Ao: "1.45", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" }, feline, "", 4).AE_Ao;
    expect(confirmed).toMatchObject({ status: "aumentado", referencia_max: 1.42, fonte: "Häggström et al. 2016" });
    expect(confirmed.interpretacao).toBe("Acima da faixa publicada (> 1.42)");
    expect(compararMedidasComReferencia({ AE_Ao: "1.45", AE_Ao_metodo: "outro" }, feline, "", 4).AE_Ao.status).toBe("nao_avaliado");
  });

  it("não interpreta limites legados de fluxo como intervalo individual", () => {
    const reference = { ...referenciaCanina, vmax_ao_min: 0, vmax_ao_max: 2.2, vmax_pulm_min: 0.65, vmax_pulm_max: 1.21 };
    const comparisons = compararMedidasComReferencia({ Vmax_aorta: "1.2", Vmax_pulmonar: "1" }, reference);
    expect(comparisons.Vmax_aorta.status).toBe("nao_avaliado");
    expect(comparisons.Vmax_pulmonar.status).toBe("nao_avaliado");
  });

  it("descreve a posição numérica sem chamar a faixa cadastrada de normalidade clínica", () => {
    const abaixo = compararMedidasComReferencia({ DeltaD_FS: "25" }, referenciaCanina).DeltaD_FS;
    const dentro = compararMedidasComReferencia({ DeltaD_FS: "35" }, referenciaCanina).DeltaD_FS;
    const acima = compararMedidasComReferencia({ DeltaD_FS: "50" }, referenciaCanina).DeltaD_FS;
    const semFaixa = compararMedidasComReferencia({ SIVd: "8" }, referenciaCanina).SIVd;

    expect(abaixo).toMatchObject({ status: "diminuido", interpretacao: "Abaixo da faixa cadastrada (< 28)" });
    expect(dentro).toMatchObject({ status: "normal", interpretacao: "Dentro da faixa cadastrada" });
    expect(acima).toMatchObject({ status: "aumentado", interpretacao: "Acima da faixa cadastrada (> 42)" });
    expect(semFaixa).toMatchObject({ status: "nao_avaliado", interpretacao: "Faixa não cadastrada" });
  });

  it("não classifica FE Teichholz nem FS sem fonte compatível", () => {
    const comparison = compararMedidasComReferencia(
      { FE_Teicholz: "40", DeltaD_FS: "20" },
      { ...referenciaCanina, fs_source: undefined },
    );
    expect(comparison.FE_Teicholz.status).toBe("nao_avaliado");
    expect(comparison.DeltaD_FS.status).toBe("nao_avaliado");
  });

  it("mantém FE, encurtamento e dimensões 2D visíveis sem aplicar faixas de Modo M", () => {
    const medidas2D = {
      VDF_2D: "82",
      VSF_2D: "47",
      DIVEd_2D: "42.78",
      DIVES_2D: "33.81",
    };
    const comparacoes = compararMedidasComReferencia(
      {
        ...medidas2D,
        ...deriveLeftVentricularFunctionForReference(medidas2D),
      },
      referenciaCanina
    );

    for (const key of ["DIVEd_2D", "DIVES_2D", "VDF_2D", "VSF_2D", "FE_Teicholz_2D", "DeltaD_FS_2D"]) {
      expect(comparacoes[key]).toMatchObject({
        referencia_min: null,
        referencia_max: null,
        status: "nao_avaliado",
      });
    }
    expect(comparacoes.DIVEd_2D.interpretacao).toBe("Confirme cão adulto e vista 2D para comparar");
    expect(comparacoes.FE_Teicholz_2D.interpretacao).toBe("Teichholz: intervalos 2D de Simpson não são aplicáveis");
  });

  it("usa faixas 2D publicadas apenas para diâmetros e FEC caninos com vista confirmada", () => {
    const medidas = {
      DIVEd_2D: "33.53",
      DIVEd_normalizado_2D: "1.47",
      DIVES_2D: "22.87",
      SIVd_2D: "8.36",
      PLVEd_2D: "10.29",
      FE_Teicholz_2D: "60",
      DeltaD_FS_2D: "31.8",
    };
    const referencia = {
      ...referenciaCanina,
      peso_kg: 15,
      lvid_d_min: 21,
      lvid_d_max: 30,
      lvid_s_min: 12,
      lvid_s_max: 20,
      ivs_d_min: 5,
      ivs_d_max: 8,
    };
    const result = compararMedidasComReferencia(medidas, referencia, "eixo_curto", 13.6);

    for (const key of ["DIVEd_2D", "DIVEd_normalizado_2D", "DIVES_2D", "DeltaD_FS_2D"]) {
      expect(result[key]).toMatchObject({ status: "normal", interpretacao: "Dentro da faixa 2D publicada" });
      expect(result[key].fonte).toContain("Visser et al. 2019; 2D, eixo curto");
    }
    expect([result.DIVEd_2D.referencia_min, result.DIVEd_2D.referencia_max]).toEqual([26.01, 36.73]);
    expect([result.DIVEd_normalizado_2D.referencia_min, result.DIVEd_normalizado_2D.referencia_max]).toEqual([1.14, 1.61]);
    expect([result.DIVES_2D.referencia_min, result.DIVES_2D.referencia_max]).toEqual([15.58, 25.87]);
    expect([result.DeltaD_FS_2D.referencia_min, result.DeltaD_FS_2D.referencia_max]).toEqual([21.9, 49.3]);
    for (const key of ["SIVd_2D", "PLVEd_2D", "FE_Teicholz_2D"]) {
      expect(result[key]).toMatchObject({ status: "nao_avaliado", referencia_min: null, referencia_max: null });
    }
    expect(result.SIVd_2D.interpretacao).toBe("Sem intervalo 2D por peso para esta espessura nas fontes adotadas");
    expect(result.PLVEd_2D.interpretacao).toBe("Sem intervalo 2D por peso para esta espessura nas fontes adotadas");
    expect(result.FE_Teicholz_2D.interpretacao).toBe("Teichholz: intervalos 2D de Simpson não são aplicáveis");
    expect(result.FE_Teicholz_2D.nome).toBe("FE 2D (Teichholz)");
    expect(compararMedidasComReferencia(
      { ...medidas, DeltaD_FS_2D: "45" }, referencia, "eixo_curto", 13.6,
    ).DeltaD_FS_2D.status).toBe("nao_avaliado");
  });

  it("não transfere faixas 2D entre planos, espécies ou pesos fora da amostra", () => {
    const medidas = { DIVEd_2D: "47.27", DIVES_2D: "26", DeltaD_FS_2D: "45" };
    const curto = compararMedidasComReferencia(medidas, referenciaCanina, "eixo_curto", 13.6);
    const longo = compararMedidasComReferencia(medidas, referenciaCanina, "eixo_longo", 13.6);
    expect(curto.DIVES_2D.referencia_max).not.toBe(longo.DIVES_2D.referencia_max);
    expect(curto.DeltaD_FS_2D.status).toBe("normal");
    expect(longo.DeltaD_FS_2D.status).toBe("aumentado");

    for (const [referencia, peso] of [
      [{ ...referenciaCanina, especie: "Felina" as const }, 13.6],
      [referenciaCanina, 2.5],
      [referenciaCanina, 67.9],
    ] as const) {
      expect(compararMedidasComReferencia(medidas, referencia, "eixo_curto", peso).DIVES_2D.status).toBe("nao_avaliado");
    }
    expect(compararMedidasComReferencia(medidas, referenciaCanina, "eixo_curto", 2.5).DIVEd_2D.interpretacao)
      .toBe("Peso fora da população estudada (2,6 a 67,8 kg)");
    expect(compararMedidasComReferencia({ ...medidas, DeltaD_FS_2D: "20" }, referenciaCanina, "eixo_curto", 13.6).DeltaD_FS_2D.interpretacao)
      .toBe("Encurtamento exige DIVEd e DIVEs 2D compatíveis");
  });

  it("preserva FE e encurtamento 2D informados pelo equipamento", () => {
    expect(
      deriveLeftVentricularFunctionForReference({
        VDF_2D: "82",
        VSF_2D: "47",
        DIVEd_2D: "42.78",
        DIVES_2D: "33.81",
        FE_Teicholz_2D: "44",
        DeltaD_FS_2D: "22",
      })
    ).toEqual({});
  });
});


describe("canine diastolic statistical comparison", () => {
  const protocol = { Diastolica_metodo: "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo", Diastolica_ondas: "separadas", TDI_metodo: "canino_pw_anel_septal_choi", TDI_ondas: "separadas" };
  it.each([["0.50", "diminuido"], ["0.51", "normal"], ["1.10", "normal"], ["1.11", "aumentado"]])
    ("compares only the actual E interval with inclusive boundaries: %s", (E, status) => {
      const comparisons = compararMedidasDiastolicas({ Onda_E: E, ...protocol }, "Dog");
      expect(comparisons.Onda_E).toMatchObject({ status, referencia_min: .51, referencia_max: 1.1, referencia_tipo: "reference_interval", estatistica: "reference_interval_95" });
      expect(comparisons.Onda_E.interpretacao).not.toMatch(/disfunção|anormal|normalidade clínica/);
    });
  it("keeps descriptive populations neutral even for values far from the mean", () => {
    const raw = { Onda_E: ".8", Onda_A: "5", E_A: "15", TD: "300", TRIV: "5", e_doppler: "1", a_doppler: "2", E_E_linha: "50", doppler_tecidual_relacao: "8", ...protocol };
    const comparisons = compararMedidasDiastolicas(raw, "Cão");
    for (const [key, comparison] of Object.entries(comparisons)) {
      if (key === "Onda_E") continue;
      expect(comparison).toMatchObject({ status: "nao_avaliado", referencia_min: null, referencia_max: null, referencia_tipo: "descriptive", estatistica: "mean_sd" });
    }
    expect(raw.Onda_A).toBe("5");
  });
  it("requires explicit confirmations and overrides generic catalogue values", () => {
    const reference = { id: 1, especie: "Canina", peso_kg: 10, mv_e_min: .2, mv_e_max: 2, mv_a_min: .1, mv_a_max: 1 } as ReferenciaEco;
    const measurements = { Onda_E: ".8", Onda_A: ".5" };
    expect(compararMedidasComReferencia(measurements, reference).Onda_E).toMatchObject({ status: "nao_avaliado", referencia_tipo: "unconfirmed", referencia_min: null });
    expect(compararMedidasComReferencia({ ...measurements, ...protocol }, reference).Onda_E.referencia_min).toBe(.51);
    expect(compararMedidasDiastolicas({ ...measurements, ...protocol, Diastolica_ondas: "fundidas" }, "Cão").Onda_E)
      .toMatchObject({ valor_medido: "Não mensurável", referencia_tipo: "uninterpretable", status: "nao_avaliado" });
    expect(compararMedidasDiastolicasFelinas(measurements, "Canina")).toEqual({});
  });
});

describe("compatibilidade dos aliases nos cartões diastólicos", () => {
  const aliases = { MV_E: "Onda_E", MV_A: "Onda_A", MV_E_A: "E_A", MV_DT: "TD", IVRT: "TRIV",
    MV_E_TRIV: "E_TRIV", TDI_e: "e_doppler", TDI_a: "a_doppler", EEp: "E_E_linha" };
  const values = { Onda_E: "0.70", Onda_A: "0.50", E_A: "1.40", TD: "90", TRIV: "70",
    E_TRIV: "1.00", e_doppler: "0.09", a_doppler: "0.11", E_E_linha: "7.78", doppler_tecidual_relacao: "0.82" };
  function protocol(species: string) {
    return { Diastolica_metodo: species === "Canina" ? "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo"
      : "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "separadas",
      TDI_metodo: species === "Canina" ? "canino_pw_anel_septal_choi" : "felino_pw_anel_lateral", TDI_ondas: "separadas" };
  }
  function catalog(species: string): ReferenciaEco {
    return { ...referenciaCanina, especie: species as ReferenciaEco["especie"], mv_e_min: .1, mv_e_max: 3,
      mv_a_min: .1, mv_a_max: 3, mv_ea_min: .1, mv_ea_max: 3, mv_dt_min: 1, mv_dt_max: 200,
      ivrt_min: 1, ivrt_max: 200, tdi_e_min: 1, tdi_e_max: 30, tdi_a_min: 1, tdi_a_max: 30 };
  }

  it.each(["Canina", "Felina"])("retorna uma chave canônica e o mesmo valor para cada alias de %s", (species) => {
    const legacy = Object.fromEntries(Object.entries(values).map(([canonical, value]) =>
      [Object.entries(aliases).find(([, target]) => target === canonical)?.[0] ?? canonical, value]));
    const measurements = { ...legacy, ...protocol(species) };
    const before = { ...measurements };
    const expected = compararMedidasDiastolicas({ ...values, ...protocol(species) }, species);
    expect(compararMedidasDiastolicas(measurements, species)).toEqual(expected);
    expect(compararMedidasComReferencia(measurements, catalog(species))).toEqual(expected);
    expect(Object.keys(expected).sort()).toEqual(Object.keys(values).sort());
    expect(measurements).toEqual(before);
  });

  it.each(["Canina", "Felina"])("prioriza a canônica explícita, inclusive inválida, nas duas ordens em %s", (species) => {
    for (const [alias, canonical] of Object.entries(aliases)) {
      for (const value of ["0.70", 0, "0", "", "NaN", NaN, null, undefined]) {
        for (const canonicalFirst of [true, false]) {
          const pairs: Array<[string, unknown]> = [[canonical, value], [alias, "1.80"]];
          const measurements = { ...Object.fromEntries(canonicalFirst ? pairs : pairs.toReversed()),
            ...protocol(species) } as Record<string, string>;
          const before = { ...measurements };
          const expected = compararMedidasDiastolicas({ [canonical]: value, ...protocol(species) } as Record<string, string>, species);
          expect(compararMedidasDiastolicas(measurements, species)).toEqual(expected);
          expect(compararMedidasComReferencia(measurements, catalog(species))).toEqual(expected);
          expect(measurements).toEqual(before);
        }
      }
    }
  });

  it.each(["Canina", "Felina"])("não reintroduz alias pelo catálogo com fusão ou revisão pendente em %s", (species) => {
    for (const flow of ["separadas", "fundidas", "nao_confirmadas"]) {
      for (const tissue of ["separadas", "fundidas", "nao_confirmadas"]) {
        const canonical = { ...values, ...protocol(species), Diastolica_ondas: flow, TDI_ondas: tissue };
        const measurements = { MV_E: "1.80", MV_A: "1.90", TDI_e: "0.80", ...canonical };
        const before = { ...measurements };
        const expected = compararMedidasDiastolicas(canonical, species);
        const actual = compararMedidasComReferencia(measurements, catalog(species));
        expect(actual).toEqual(expected);
        if (flow !== "separadas") expect(actual.Onda_E.status).toBe("nao_avaliado");
        if (tissue !== "separadas") expect(actual.e_doppler.status).toBe("nao_avaliado");
        expect(measurements).toEqual(before);
      }
    }
    const fusionOnly = { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" };
    expect(compararMedidasComReferencia(fusionOnly, catalog(species)))
      .toEqual(compararMedidasDiastolicas(fusionOnly, species));
  });
});
