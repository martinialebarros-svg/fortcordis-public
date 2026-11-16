import { describe, expect, it } from "vitest";
import { buildEchoReportGroups, prepareEchoReportMeasurements, splitReportObservations } from "./echo-report-presentation";
import { deriveAutomaticEchoMeasurements, parseStoredEchoMeasurements } from "./echo-derived-measurements";
import { mergeImportedEchoMeasurements, updateEchoMeasurement } from "./echo-unit-provenance";
import type { ReferenciaEco } from "@/app/laudos/types/referencia-eco";

describe("prévia de ecocardiograma", () => {
  const diastolicKeys = ["Onda_E", "Onda_A", "E_A", "TD", "TRIV", "E_TRIV",
    "e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"];

  it.each(["Canina", "Felina"])("omite os dez diastólicos não positivos ou não finitos sem recuperar aliases em %s", (species) => {
    for (const value of ["-1", "-0", "0", 0, "NaN", NaN, "Infinity", Infinity, null, "", "1e-400"]) {
      const raw = { ...Object.fromEntries(diastolicKeys.map((key) => [key, value])), MV_E: "1.80",
        Diastolica_ondas: "nao_confirmadas", TDI_ondas: "nao_confirmadas", Outro_valor_registrado: "-2" } as Record<string, string>;
      const before = { ...raw };
      const rows = buildEchoReportGroups(raw, null, new Set(), 10, species).flatMap((group) => group.rows);
      expect(rows).toEqual([{ key: "Outro_valor_registrado", label: "Outro_valor_registrado", value: "-2.00", reference: "—" }]);
      expect(raw).toEqual(before);
    }
  });

  it.each(["Canina", "Felina"])("mantém os nove placeholders fundidos mesmo com valores inválidos em %s", (species) => {
    for (const value of ["-1", "0", "NaN", null]) {
      const raw = { ...Object.fromEntries(diastolicKeys.map((key) => [key, value])), MV_E: "1.80",
        Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" } as Record<string, string>;
      const rows = buildEchoReportGroups(raw, null, new Set(), 10, species).flatMap((group) => group.rows);
      expect(rows).toHaveLength(9);
      expect(rows.every((row) => row.value === "Não mensurável")).toBe(true);
      expect(rows.some((row) => row.key === "TRIV" || row.key === "MV_E")).toBe(false);
    }
  });

  it.each(["Canina", "Felina"])("marca a reconfirmação somente dos índices numéricos positivos em %s", (species) => {
    const raw = { ...Object.fromEntries(diastolicKeys.map((key) => [key, "0.70"])),
      E_TRIV: "-1", E_E_linha: "NaN", Diastolica_ondas: "nao_confirmadas", TDI_ondas: "nao_confirmadas" };
    const rows = buildEchoReportGroups(raw, null, new Set(), 10, species).flatMap((group) => group.rows);
    expect(rows.filter((row) => row.value.includes("valor a confirmar")).map((row) => row.key).sort())
      .toEqual(["E_A", "doppler_tecidual_relacao"]);
    expect(rows.some((row) => ["E_TRIV", "E_E_linha"].includes(row.key))).toBe(false);
    expect(rows.find((row) => row.key === "TRIV")?.value).toBe("0.70 ms");
  });

  it.each(["Canina", "Felina"])("exibe aliases somente na linha canônica, com unidade e fonte coerentes em %s", (species) => {
    const aliases = { MV_E: "Onda_E", MV_A: "Onda_A", MV_E_A: "E_A", MV_DT: "TD", IVRT: "TRIV",
      MV_E_TRIV: "E_TRIV", TDI_e: "e_doppler", TDI_a: "a_doppler", EEp: "E_E_linha" };
    const values = { Onda_E: "0.70", Onda_A: "0.50", E_A: "1.40", TD: "90", TRIV: "70",
      E_TRIV: "1.00", e_doppler: "0.09", a_doppler: "0.11", E_E_linha: "7.78", doppler_tecidual_relacao: "0.82" };
    const protocol = { Diastolica_metodo: species === "Canina" ? "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo"
      : "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "separadas",
      TDI_metodo: species === "Canina" ? "canino_pw_anel_septal_choi" : "felino_pw_anel_lateral", TDI_ondas: "separadas" };
    const legacy = Object.fromEntries(Object.entries(values).map(([key, value]) =>
      [Object.entries(aliases).find(([, target]) => target === key)?.[0] ?? key, value]));
    for (const raw of [{ ...legacy, ...protocol }, { ...legacy, ...values, ...protocol }]) {
      const before = { ...raw };
      const expected = buildEchoReportGroups({ ...values, ...protocol }, null, new Set(), 10, species);
      expect(buildEchoReportGroups(raw, null, new Set(), 10, species)).toEqual(expected);
      const prepared = prepareEchoReportMeasurements(raw, 10, species);
      expect(buildEchoReportGroups(prepared.measurements, null, prepared.ambiguousKeys, 10, species)).toEqual(expected);
      expect(raw).toEqual(before);
    }
  });

  it.each(["Canina", "Felina"])("não recupera o alias em Outras medidas após zerar ou limpar a canônica em %s", (species) => {
    for (const value of ["0.47", "0", 0, "", null, NaN, "NaN"]) {
      for (const canonicalFirst of [true, false]) {
        const entries: Array<[string, unknown]> = [["Onda_E", value], ["MV_E", "1.80"]];
        const raw = { ...Object.fromEntries(canonicalFirst ? entries : entries.toReversed()),
          Diastolica_ondas: "nao_confirmadas" } as Record<string, string>;
        const before = { ...raw };
        for (const input of [raw, parseStoredEchoMeasurements(raw)]) {
          const rows = buildEchoReportGroups(input, null, new Set(), 10, species).flatMap((group) => group.rows);
          expect(rows.some((row) => row.key === "MV_E")).toBe(false);
          expect(rows.filter((row) => row.key === "Onda_E")).toHaveLength(value === "0.47" ? 1 : 0);
          if (value === "0.47") expect(rows[0].value).toBe("0.47 m/s");
          expect(rows.some((row) => /NaN|1\.80/.test(row.value))).toBe(false);
        }
        expect(raw).toEqual(before);
      }
    }
  });

  it.each(["Canina", "Felina"])("mantém fusão e reconfirmação dos aliases em uma única linha diastólica em %s", (species) => {
    for (const wave of ["fundidas", "nao_confirmadas"]) {
      const raw = { MV_E: "1.80", Onda_E: "0.70", MV_E_A: "2.20", E_A: "1.40",
        IVRT: "70", TDI_e: "0.90", e_doppler: "0.09", Diastolica_ondas: wave,
        TDI_ondas: "separadas", TDI_metodo: species === "Canina" ? "canino_pw_anel_septal_choi" : "felino_pw_anel_lateral" };
      const rows = buildEchoReportGroups(raw, null, new Set(), 10, species).flatMap((group) => group.rows);
      expect(rows.filter((row) => row.key === "Onda_E")).toHaveLength(1);
      expect(rows.filter((row) => row.key === "E_A")).toHaveLength(1);
      expect(rows.find((row) => row.key === "E_A")).toMatchObject({
        value: wave === "fundidas" ? "Não mensurável" : "1.40 (valor a confirmar)",
      });
      expect(rows.find((row) => row.key === "e_doppler")).toMatchObject({ value: "0.09 m/s", referenceMetadata: { kind: "descriptive" } });
      expect(rows.some((row) => ["MV_E", "MV_E_A", "IVRT", "TDI_e"].includes(row.key))).toBe(false);
    }
  });

  it("preserva fonte, estatística e condições junto à referência descritiva sem alterar o valor", () => {
    const raw = { Onda_E: "1.08", TD: "51", TRIV: "40", e_doppler: "0.16", E_E_linha: "6.95",
      Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "separadas",
      TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas" };
    const before = { ...raw };
    const rows = buildEchoReportGroups(raw, null, new Set(), undefined, "Gato").flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "Onda_E")).toMatchObject({
      value: "1.08 m/s", reference: "0,70 ± 0,14 m/s",
      referenceMetadata: { source: "Disatian et al. (2008)", doi: "10.1111/j.1939-1676.2008.0066.x",
        statistic: "mean_sd", kind: "descriptive", note: expect.stringContaining("66 gatos saudáveis, não sedados") },
    });
    expect(rows.find((row) => row.key === "TD")?.referenceMetadata).toMatchObject({ source: "Soares et al. (2005)", note: expect.stringContaining("24 gatos adultos saudáveis, não sedados") });
    expect(rows.find((row) => row.key === "e_doppler")?.referenceMetadata).toMatchObject({
      source: "Kiatsilapanan & Surachetpong (2020)", doi: "10.1186/s12917-020-02557-3",
      statistic: "mean_sd", note: expect.stringContaining("anel lateral"),
    });
    expect(rows.find((row) => row.key === "E_E_linha")?.referenceMetadata?.note).toContain("não é intervalo individual de normalidade");
    expect(raw).toEqual(before);
  });

  it.each(["fundidas", ""])("mantém o motivo e não atribui publicação a ondas %s", (waves) => {
    const rows = buildEchoReportGroups({ Onda_E: "1.08", Diastolica_ondas: waves }, null, new Set(), undefined, "Felina")
      .flatMap((group) => group.rows);
    expect(rows[0]).toMatchObject({ value: waves ? "Não mensurável" : "1.08 m/s", referenceMetadata: {
      source: "", doi: "", statistic: "", kind: waves ? "uninterpretable" : "unconfirmed",
      note: expect.stringMatching(waves ? /não são separadamente mensuráveis/ : /Confirme/),
    } });
  });

  it("não apresenta números inválidos como resultados mesmo após limpar as origens", () => {
    const raw = { Onda_E: "0", Onda_A: "0", E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.95",
      TRIV: "40", e_doppler: "0.16", Diastolica_ondas: "fundidas", TDI_ondas: "separadas",
      TDI_metodo: "felino_pw_anel_lateral" };
    const rows = buildEchoReportGroups(raw, null, new Set(), undefined, "Gato").flatMap((group) => group.rows);
    const blocked = ["Onda_E", "Onda_A", "E_A", "TD", "E_TRIV", "E_E_linha"];
    for (const key of blocked) expect(rows.find((row) => row.key === key)).toMatchObject({ value: "Não mensurável", reference: "Ondas E/A fundidas" });
    expect(rows.find((row) => row.key === "TRIV")?.value).toBe("40.00 ms");
    expect(rows.find((row) => row.key === "e_doppler")?.value).toBe("0.16 m/s");
    expect(raw.E_A).toBe("1.14");
    const cleared = buildEchoReportGroups({ Diastolica_ondas: "fundidas" }, null, new Set(), undefined, "Cat");
    expect(cleared.flatMap((group) => group.rows)).toHaveLength(6);
    expect(cleared.flatMap((group) => group.rows).every((row) => row.value === "Não mensurável")).toBe(true);
  });

  it("fusão tecidual oculta apenas e', a', e'/a' e E/e'", () => {
    const raw = { Onda_E: "1.08", Onda_A: "0.95", E_A: "1.14", TRIV: "40", E_TRIV: "2.7",
      e_doppler: "0.16", a_doppler: "0.06", doppler_tecidual_relacao: "2.67", E_E_linha: "6.75",
      Diastolica_ondas: "separadas", TDI_ondas: "fundidas" };
    const rows = buildEchoReportGroups(raw, null, new Set(), undefined, "Cat").flatMap((group) => group.rows);
    for (const key of ["e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"]) expect(rows.find((row) => row.key === key)?.value).toBe("Não mensurável");
    expect(rows.find((row) => row.key === "Onda_E")?.value).toBe("1.08 m/s");
    expect(rows.find((row) => row.key === "E_A")?.value).toBe("1.14");
  });

  it("mantém a confirmação histórica de TRIV sem pressupor confirmação apical para o Doppler transmitral", () => {
    const rows = buildEchoReportGroups({ Onda_E: "1.08", TRIV: "40", E_E_linha: "6.95",
      Diastolica_metodo: "felino_adulto_nao_sedado_pw_clique_aortico", Diastolica_ondas: "separadas",
      TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas" }, null, new Set(), undefined, "Felina")
      .flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "Onda_E")).toMatchObject({ value: "1.08 m/s", reference: "—", referenceMetadata: { kind: "unconfirmed", source: "", doi: "" } });
    expect(rows.find((row) => row.key === "TRIV")).toMatchObject({ value: "40.00 ms", reference: "46,2 ± 7,6 ms", referenceMetadata: { kind: "descriptive", source: "Disatian et al. (2008)" } });
    expect(rows.find((row) => row.key === "E_E_linha")).toMatchObject({ value: "6.95", reference: "—", referenceMetadata: { kind: "unconfirmed", source: "", doi: "" } });
  });

  it("não acrescenta metadados felinos às referências caninas ou às unidades ambíguas", () => {
    const reference = { especie: "Canina", peso_kg: 10, lvid_d_min: 20, lvid_d_max: 40 } as ReferenciaEco;
    const row = buildEchoReportGroups({ DIVEd: "30" }, reference).flatMap((group) => group.rows)[0];
    expect(row).toEqual({ key: "DIVEd", label: "DIVEd · diâmetro interno do VE em diástole", value: "30.00 mm", reference: "20.00–40.00 mm" });
    const ambiguous = buildEchoReportGroups({ Onda_E: "1.08", Diastolica_ondas: "fundidas" }, null, new Set(["Onda_E"]), undefined, "Gato")
      .flatMap((group) => group.rows)[0];
    expect(ambiguous.value).toBe("Não mensurável");
    expect(ambiguous.referenceMetadata?.kind).toBe("uninterpretable");
  });

  it.each(["Gato", "Cat", "felino", " Felina "])
    ("preserva registro bruto e oculta números de fusão para o alias %s", (species) => {
      const raw = { Onda_E: "1.08", E_A: "1.13", TRIV: "40", e_doppler: "0.16", E_E_linha: "6.95",
        Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "fundidas",
        TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas", DIVEd_normalizado: "0.9",
        AE_diametro_max: "18", AE_diametro_min: "13.5" };
      const before = { ...raw };
      const { measurements } = prepareEchoReportMeasurements(raw, 5.6, species);
      expect(measurements).toMatchObject({ E_A: "1.13", E_E_linha: "6.95", Fracao_encurtamento_AE: "25" });
      expect(measurements).not.toHaveProperty("DIVEd_normalizado");
      const reference = { id: 1, especie: species, peso_kg: 5.5, mv_e_min: 0.5, mv_e_max: 1.5 } as ReferenciaEco;
      const rows = buildEchoReportGroups(measurements, reference, new Set(), 5.6, species).flatMap((group) => group.rows);
      expect(rows.find((row) => row.key === "Onda_E")).toMatchObject({ value: "Não mensurável", reference: "Ondas E/A fundidas" });
      expect(rows.find((row) => row.key === "e_doppler")?.reference).toBe("0,11 ± 0,03 m/s");
      expect(rows.find((row) => row.key === "E_E_linha")).toMatchObject({ value: "Não mensurável", reference: "Ondas E/A fundidas" });
      expect(raw).toEqual(before);
    });

  it("mostra estatísticas felinas e fusão independente sem peso, catálogo ou metadados como medidas", () => {
    const measurements = { Onda_E: "1.08", E_A: "1.14", TRIV: "40", e_doppler: "0.16", E_E_linha: "6.75",
      Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "fundidas", TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas" };
    const groups = buildEchoReportGroups(measurements, null, new Set(), undefined, "Felina");
    const rows = groups.flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "Onda_E")).toMatchObject({ value: "Não mensurável", reference: "Ondas E/A fundidas" });
    expect(rows.find((row) => row.key === "e_doppler")).toMatchObject({ value: "0.16 m/s", reference: "0,11 ± 0,03 m/s" });
    expect(rows.find((row) => row.key === "TRIV")?.reference).toBe("46,2 ± 7,6 ms");
    expect(rows.find((row) => row.key === "E_E_linha")?.reference).toBe("Ondas E/A fundidas");
    expect(groups.some((group) => group.title === "Outras medidas registradas")).toBe(false);
  });
  it("mostra o limite clínico canino com método confirmado mesmo sem catálogo", () => {
    const raw = { AE_Ao: "1.41", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" };
    const findRatio = (species: string, measurements = raw, ambiguousKeys = new Set<string>()) =>
      buildEchoReportGroups(measurements, null, ambiguousKeys, undefined, species)
        .flatMap((group) => group.rows).find((row) => row.key === "AE_Ao");
    expect(findRatio("Canina")?.reference).toBe("<1,60 (2D, eixo curto)");
    expect(findRatio("Canina")?.value).toBe("1.41");
    expect(findRatio("Felina")?.reference).toBe("—");
    expect(findRatio("Canina", { ...raw, AE_Ao_metodo: "" })?.reference).toBe("—");
    expect(findRatio("Canina", { ...raw, AE_Ao_metodo: "outro" })?.reference).toBe("—");
    expect(findRatio("Canina", { ...raw, AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" })?.reference).toBe("<1,60 (2D, eixo curto)");
    expect(findRatio("Felina", { ...raw, AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" })?.reference).toBe("—");
    expect(findRatio("Canina", raw, new Set(["Aorta"]))?.reference).toBe("—");
  });
  it("repete os bloqueios e o método de TAPSE na prévia sem incluir metadados como medidas", () => {
    const reference: ReferenciaEco = {
      id: 1, especie: "Canina", peso_kg: 10, vmax_ao_min: 0, vmax_ao_max: 2.2,
      range_metadata: { tapse: {
        status: "requires_method", candidate_min: 8, candidate_max: 15, min_weight_kg: 3, max_weight_kg: 45,
        required_measurement_key: "TAPSE_metodo", required_measurement_value: "modo_m_apical",
      } },
    };
    const raw = { TAPSE: "10", Vmax_aorta: "1.2", TAPSE_metodo: "modo_m_apical", AE_Ao_metodo: "outro" };
    const groups = buildEchoReportGroups(raw, reference, new Set(), 10);
    expect(groups.flatMap((group) => group.rows).find((row) => row.key === "TAPSE")?.reference).toBe("8.00–15.00 mm");
    expect(groups.flatMap((group) => group.rows).find((row) => row.key === "Vmax_aorta")?.reference).toBe("—");
    expect(groups.some((group) => group.title === "Outras medidas registradas")).toBe(false);
    const notConfirmed = buildEchoReportGroups({ ...raw, TAPSE_metodo: "2d" }, reference, new Set(), 10);
    expect(notConfirmed.flatMap((group) => group.rows).find((row) => row.key === "TAPSE")?.reference).toBe("—");
  });

  it("recalcula DIVEd normalizado com o peso atual e expõe divergência sem alterar o registro", () => {
    const stored = { DIVEd: "47.19", DIVEd_normalizado: "1.964", VE_tecnica_relatorio: "modo_m" };
    const { measurements, alerts } = prepareEchoReportMeasurements(stored, 13.9, "Canina");
    expect(stored.DIVEd_normalizado).toBe("1.964");
    expect(measurements.DIVEd_normalizado).toBe("2.18");
    expect(alerts).toEqual([{ key: "DIVEd_normalizado", recorded: 1.964, calculated: 2.18 }]);
  });

  it("alerta somente sobre o DIVEd normalizado da técnica selecionada", () => {
    const stored = {
      DIVEd: "30",
      DIVEd_normalizado: "9",
      DIVEd_2D: "32",
      DIVEd_normalizado_2D: "8",
      VE_tecnica_relatorio: "2d",
      VE_vista_2D: "eixo_curto",
    };
    const selected2D = prepareEchoReportMeasurements(stored, 10, "Canina");
    expect(selected2D.measurements).toMatchObject({
      DIVEd_normalizado: "1.52",
      DIVEd_normalizado_2D: "1.55",
    });
    expect(selected2D.alerts).toEqual([{
      key: "DIVEd_normalizado_2D", recorded: 8, calculated: 1.55,
    }]);

    const selectedM = prepareEchoReportMeasurements({ ...stored, VE_tecnica_relatorio: "modo_m" }, 10, "Canina");
    expect(selectedM.alerts).toEqual([{
      key: "DIVEd_normalizado", recorded: 9, calculated: 1.52,
    }]);
  });

  it("mostra índice de Visser 2D e sua faixa somente com espécie, vista e peso aplicáveis", () => {
    const raw = { VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_curto", DIVEd_2D: "33.53", DIVEd_normalizado_2D: "1.56" };
    const { measurements, alerts, ambiguousKeys } = prepareEchoReportMeasurements(raw, 13.6, "Canina");
    expect(measurements.DIVEd_normalizado_2D).toBe("1.47");
    expect(alerts).toEqual([{ key: "DIVEd_normalizado_2D", recorded: 1.56, calculated: 1.47 }]);
    const reference = { especie: "Canina", peso_kg: 15 } as ReferenciaEco;
    expect(buildEchoReportGroups(measurements, reference, ambiguousKeys, 13.6)[0].rows
      .find((row) => row.key === "DIVEd_normalizado_2D")?.reference).toBe("1.14–1.61");
    expect(prepareEchoReportMeasurements(raw, 13.6, "Felina").measurements.DIVEd_normalizado_2D).toBeUndefined();
    expect(prepareEchoReportMeasurements({ ...raw, VE_vista_2D: "" }, 13.6, "Canina").measurements.DIVEd_normalizado_2D).toBeUndefined();
  });

  it("omite Cornell da prévia felina, mesmo se o índice antigo estiver salvo", () => {
    const raw = { VE_tecnica_relatorio: "modo_m", DIVEd: "11.46", DIVEd_normalizado: "0.90" };
    const { measurements, alerts } = prepareEchoReportMeasurements(raw, 2.3, "Felina");
    expect(raw.DIVEd_normalizado).toBe("0.90");
    expect(measurements.DIVEd_normalizado).toBeUndefined();
    expect(alerts).toEqual([]);
    expect(buildEchoReportGroups(measurements, null)[0].rows.map((row) => row.key)).not.toContain("DIVEd_normalizado");
  });

  it("deriva função atrial e gradiente da VSVE na prévia sem alterar o registro", () => {
    const raw = { AE_diametro_max: "18", AE_diametro_min: "13.5", Vmax_VSVE: "2.5" };
    const { measurements } = prepareEchoReportMeasurements(raw, 4, "Felina");
    expect(measurements.Fracao_encurtamento_AE).toBe("25");
    expect(measurements.Grad_VSVE).toBe("25");
    expect(raw).not.toHaveProperty("Fracao_encurtamento_AE");
    const groups = buildEchoReportGroups(measurements, null);
    expect(groups.find((group) => group.title === "Átrio esquerdo / aorta")?.rows
      .find((row) => row.key === "Fracao_encurtamento_AE")?.reference).toBe("—");
    expect(prepareEchoReportMeasurements({ ...raw, AE_diametro_min: "19" }, 4, "Felina")
      .measurements.Fracao_encurtamento_AE).toBeUndefined();
  });

  it("mantém medidas legadas sem unidade como ambíguas e não calcula DIVEd normalizado", () => {
    const { measurements, ambiguousKeys } = prepareEchoReportMeasurements({ DIVEd: "3", SIVd: "0.7", PLVEd: "0.8" }, 10);
    expect(measurements.DIVEd).toBe("3");
    expect(measurements.DIVEd_normalizado).toBeUndefined();
    expect(ambiguousKeys.has("SIVd")).toBe(true);
    expect(prepareEchoReportMeasurements({ DIVEd: "3", SIVd: "0.7", PLVEd: "0.8", DIVEd_normalizado: "1.52" }, null).measurements.DIVEd_normalizado).toBeUndefined();
    expect(prepareEchoReportMeasurements({ DIVEd: "3", SIVd: "7", PLVEd: "8" }, 10).measurements.DIVEd).toBe("3");
  });

  it("preserva TAPSE, MAPSE e aorta já em mm em um conjunto legado misto", () => {
    const raw = {
      DIVEd: "3", SIVd: "0.7", PLVEd: "0.8",
      DIVES: "1.5", SIVs: "1", PLVES: "1.3",
      Aorta: "13.1", TAPSE: "10", MAPSE: "8",
      VE_tecnica_relatorio: "modo_m",
    };
    const { measurements } = prepareEchoReportMeasurements(raw, 10);

    expect(measurements).toMatchObject({
      DIVEd: "3", SIVd: "0.7", PLVEd: "0.8",
      Aorta: "13.1", TAPSE: "10", MAPSE: "8",
    });
    const groups = buildEchoReportGroups(measurements, null);
    const annular = groups.find((group) => group.title === "Excursão do plano anular");
    expect(annular?.rows.find((row) => row.key === "TAPSE")?.value).toBe("10.00 mm");
    expect(annular?.rows.find((row) => row.key === "MAPSE")?.value).toBe("8.00 mm");
    expect(groups.find((group) => group.title === "Átrio esquerdo / aorta")?.rows.find((row) => row.key === "Aorta")?.value).toBe("13.10 mm");
    expect(prepareEchoReportMeasurements({ ...raw, Aorta: "1.3" }, 10).measurements.Aorta).toBe("1.3");
  });

  it("não multiplica SIVd de 3 mm em conjunto legado misto", () => {
    const raw = { DIVEd: "2.5", DIVES: "1.5", Atrio_esquerdo: "2.0", SIVd: "3.0" };
    const { measurements, ambiguousKeys } = prepareEchoReportMeasurements(raw, 10, "Canina");
    const groups = buildEchoReportGroups(measurements, null, ambiguousKeys);
    expect(measurements.SIVd).toBe("3.0");
    expect(measurements.DIVEd_normalizado).toBeUndefined();
    expect(groups[0].rows.find((row) => row.key === "SIVd")).toMatchObject({
      value: "3.00 (unidade a confirmar)", reference: "—",
    });
  });

  it("aplica somente as unidades confirmadas e mantém o restante sem comparação", () => {
    const raw = {
      DIVEd: "2.5", DIVES: "1.5", Atrio_esquerdo: "2.0", SIVd: "3.0",
      unidade_confirmada_DIVEd: "cm", unidade_confirmada_SIVd: "mm",
    };
    const reference = { id: 1, especie: "Canina", peso_kg: 10, lvid_d_min: 20, lvid_d_max: 40, ivs_d_min: 4, ivs_d_max: 10 } as ReferenciaEco;
    const { measurements, ambiguousKeys } = prepareEchoReportMeasurements(raw, 10, "Canina");
    expect(raw.DIVEd).toBe("2.5");
    expect(measurements).toMatchObject({ DIVEd: "25", SIVd: "3.0", DIVEd_normalizado: "1.27" });
    expect(ambiguousKeys).toEqual(new Set(["DIVES", "Atrio_esquerdo"]));
    const groups = buildEchoReportGroups(measurements, reference, ambiguousKeys);
    expect(groups[0].rows.find((row) => row.key === "DIVEd")).toMatchObject({ value: "25.00 mm", reference: "20.00–40.00 mm" });
    expect(groups[0].rows.find((row) => row.key === "SIVd")).toMatchObject({ value: "3.00 mm", reference: "4.00–10.00 mm" });
    expect(groups[0].rows.find((row) => row.key === "DIVES")).toMatchObject({ value: "1.50 (unidade a confirmar)", reference: "—" });
    expect(groups.some((group) => group.title === "Outras medidas registradas")).toBe(false);
  });

  it("usa apenas o modo selecionado sem atribuir a faixa Modo M à medida 2D", () => {
    const reference = { id: 1, especie: "Canina", peso_kg: 10, lvid_d_min: 20, lvid_d_max: 40 } as ReferenciaEco;
    const groups = buildEchoReportGroups({ VE_tecnica_relatorio: "2d", DIVEd: "30", DIVEd_2D: "32", FE_Teicholz_2D: "57" }, reference);
    expect(groups[0].title).toContain("2D");
    expect(groups[0].rows.map((row) => row.key)).toEqual(["DIVEd_2D", "FE_Teicholz_2D"]);
    expect(groups[0].rows[0]).toMatchObject({ value: "32.00 mm", reference: "—" });
    expect(groups[0].rows[1].reference).toBe("—");
  });

  it("repete na prévia as faixas 2D publicadas somente com vista persistida", () => {
    const reference = { id: 1, especie: "Canina", peso_kg: 15 } as ReferenciaEco;
    const measures = {
      VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_curto",
      DIVEd_2D: "33.53", DIVES_2D: "22.87", DeltaD_FS_2D: "31.8",
      SIVd_2D: "8.36", FE_Teicholz_2D: "61",
    };
    const rows = buildEchoReportGroups(measures, reference, new Set(), 13.6)[0].rows;
    expect(rows.find((row) => row.key === "DIVEd_2D")?.reference).toBe("26.01–36.73 mm");
    expect(rows.find((row) => row.key === "DIVES_2D")?.reference).toBe("15.58–25.87 mm");
    expect(rows.find((row) => row.key === "DeltaD_FS_2D")?.reference).toBe("21.90–49.30 %");
    expect(rows.find((row) => row.key === "SIVd_2D")?.reference).toBe("—");
    expect(rows.find((row) => row.key === "FE_Teicholz_2D")?.reference).toBe("—");
    expect(buildEchoReportGroups({ ...measures, VE_vista_2D: "" }, reference, new Set(), 13.6)[0].rows[0].reference).toBe("—");
  });

  it("mostra FS de modo M com fonte e FE Teichholz sem faixa", () => {
    const reference = {
      id: 1, especie: "Canina", peso_kg: 10,
      fs_min: 20.7, fs_max: 51.9, fs_source: "Visser et al. 2019",
      ef_min: 50, ef_max: 85,
    } as ReferenciaEco;
    const rows = buildEchoReportGroups({ DeltaD_FS: "30", FE_Teicholz: "70" }, reference)[0].rows;
    expect(rows.find((row) => row.key === "DeltaD_FS")?.reference).toBe("20.70–51.90 %");
    expect(rows.find((row) => row.key === "FE_Teicholz")?.reference).toBe("—");
  });

  it("mantém TAPSE e MAPSE quando o VE é exibido em modo 2D", () => {
    const groups = buildEchoReportGroups({
      VE_tecnica_relatorio: "2d",
      DIVEd_2D: "32",
      TAPSE: "10",
      MAPSE: "8",
    }, null);

    expect(groups[0].rows.map((row) => row.key)).toEqual(["DIVEd_2D"]);
    expect(groups[1]).toMatchObject({
      title: "Excursão do plano anular",
      rows: [
        { key: "TAPSE", value: "10.00 mm" },
        { key: "MAPSE", value: "8.00 mm" },
      ],
    });
  });

  it("separa apenas linhas reconhecidas como administrativas", () => {
    expect(splitReportObservations("Achado clínico.\n[Assistente agenda] Horário reservado\n[Reserva manual] confirmação"))
      .toEqual({ clinical: "Achado clínico.", operational: "[Assistente agenda] Horário reservado\n[Reserva manual] confirmação" });
  });
});


describe("canine diastolic report preview", () => {
  const protocol = { Diastolica_metodo: "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo", Diastolica_ondas: "separadas", TDI_metodo: "canino_pw_anel_septal_choi", TDI_ondas: "separadas" };
  const measured = { Onda_E: ".47", Onda_A: ".67", E_A: ".70", TD: "108", TRIV: "85", e_doppler: ".07", a_doppler: ".12", E_E_linha: "6.71", doppler_tecidual_relacao: ".58" };
  it("carries sources/statistics without catalogue, weight, or rewriting recorded numbers", () => {
    const raw = Object.freeze({ ...measured, ...protocol });
    const groups = buildEchoReportGroups(raw, null, new Set(), undefined, "Dog");
    const rows = groups.flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "Onda_E")).toMatchObject({ value: "0.47 m/s", reference: "IR95%: 0,51-1,10 m/s", referenceMetadata: { kind: "reference_interval", statistic: "reference_interval_95", doi: "10.1111/jsap.13472" } });
    expect(rows.find((row) => row.key === "Onda_A")).toMatchObject({ value: "0.67 m/s", referenceMetadata: { kind: "descriptive", statistic: "mean_sd", source: "Pereira et al. (2009)" } });
    expect(rows.find((row) => row.key === "e_doppler")?.referenceMetadata).toMatchObject({ kind: "descriptive", doi: "10.4142/jvs.2013.14.1.85" });
    expect(groups.some((group) => group.title === "Outras medidas registradas")).toBe(false);
    expect(raw.E_A).toBe(".70");
  });
  it.each(["Canina", "Cão", "Dog"])("masks fused peaks independently and preserves original values: %s", (species) => {
    const raw = Object.freeze({ ...measured, ...protocol, Diastolica_ondas: "fundidas" });
    const rows = buildEchoReportGroups(raw, null, new Set(), undefined, species).flatMap((group) => group.rows);
    for (const key of ["Onda_E", "Onda_A", "E_A", "TD", "E_TRIV", "E_E_linha"]) expect(rows.find((row) => row.key === key)?.value).toBe("Não mensurável");
    expect(rows.find((row) => row.key === "TRIV")?.reference).toBe("80 ± 9 ms");
    expect(rows.find((row) => row.key === "e_doppler")?.value).toBe("0.07 m/s");
    const tissueFused = buildEchoReportGroups({ ...raw, Diastolica_ondas: "separadas", TDI_ondas: "fundidas" }, null, new Set(), undefined, species).flatMap((group) => group.rows);
    expect(tissueFused.find((row) => row.key === "Onda_E")?.value).toBe("0.47 m/s");
    expect(tissueFused.find((row) => row.key === "e_doppler")?.value).toBe("Não mensurável");
    expect(raw).toMatchObject(measured);
  });
});


describe("preview of a canine acquisition invalidated after fusion", () => {
  const raw = { Onda_E: "1.08", Onda_A: "0.95", E_A: "1.13", E_TRIV: "2.66", TRIV: "40", e_doppler: "0.16", a_doppler: "0.08", E_E_linha: "6.95", doppler_tecidual_relacao: "1.8", Diastolica_metodo: "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo", Diastolica_ondas: "fundidas", TDI_metodo: "canino_pw_anel_septal_choi", TDI_ondas: "separadas" };
  it.each(["edit", "import"])("keeps the original ratios and withholds references after transmitral %s", (action) => {
    const changed = action === "edit" ? updateEchoMeasurement(raw, "Onda_E", "1.10") : mergeImportedEchoMeasurements(raw, { Onda_E: "1.10" });
    const stored = parseStoredEchoMeasurements(JSON.parse(JSON.stringify(changed)));
    const payload = { ...stored, ...deriveAutomaticEchoMeasurements(stored, 10, "Canina") };
    const rows = buildEchoReportGroups(payload, null, new Set(), 10, "Canina").flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "E_A")).toMatchObject({ value: "1.13 (valor a confirmar)", reference: "—", referenceMetadata: { kind: "unconfirmed", source: "", doi: "" } });
    expect(rows.find((row) => row.key === "E_E_linha")).toMatchObject({ value: "6.95 (valor a confirmar)", referenceMetadata: { kind: "unconfirmed" } });
    expect(rows.find((row) => row.key === "Onda_E")?.referenceMetadata?.kind).toBe("unconfirmed");
    expect(rows.find((row) => row.key === "e_doppler")?.referenceMetadata?.kind).toBe("descriptive");
    expect(payload.Diastolica_ondas).toBe("nao_confirmadas");
  });
  it.each(["edit", "import"])("withholds tissue references after tissue %s and retains independent transmitral evidence", (action) => {
    const prior = { ...raw, Diastolica_ondas: "separadas", TDI_ondas: "fundidas" };
    const changed = action === "edit" ? updateEchoMeasurement(prior, "e_doppler", "0.15") : mergeImportedEchoMeasurements(prior, { e_doppler: "0.15" });
    const stored = parseStoredEchoMeasurements(changed);
    const payload = { ...stored, ...deriveAutomaticEchoMeasurements(stored, 10, "Canina") };
    const rows = buildEchoReportGroups(payload, null, new Set(), 10, "Dog").flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "doppler_tecidual_relacao")).toMatchObject({ value: "1.80 (valor a confirmar)", reference: "—", referenceMetadata: { kind: "unconfirmed", source: "", doi: "" } });
    expect(rows.find((row) => row.key === "E_E_linha")?.value).toBe("6.95 (valor a confirmar)");
    expect(rows.find((row) => row.key === "Onda_E")?.referenceMetadata?.kind).toBe("reference_interval");
    expect(payload.TDI_ondas).toBe("nao_confirmadas");
  });
});


describe("pending historical diastolic indices in report preview", () => {
  const raw = { Onda_E: "0.70", Onda_A: "0.50", E_A: "0.70", E_TRIV: "0.55", TRIV: "70", e_doppler: "0.09", a_doppler: "0.11", E_E_linha: "6.71", doppler_tecidual_relacao: "0.58" };
  it.each(["Canina", "Cão", "Dog", "Felina", "Gato", "Cat"])("marks historical indices and preserves origins until reconfirmation: %s", (species) => {
    const stored = Object.freeze({ ...raw, Diastolica_ondas: "nao_confirmadas", TDI_ondas: "nao_confirmadas" });
    const rows = buildEchoReportGroups(stored, null, new Set(), undefined, species).flatMap((group) => group.rows);
    for (const key of ["E_A", "E_TRIV", "E_E_linha", "doppler_tecidual_relacao"]) {
      expect(rows.find((row) => row.key === key)).toMatchObject({ value: `${Number(raw[key as keyof typeof raw]).toFixed(2)} (valor a confirmar)`, reference: "—", referenceMetadata: { note: expect.stringContaining("Índice histórico") } });
    }
    expect(rows.find((row) => row.key === "Onda_E")?.value).toBe("0.70 m/s");
    expect(rows.find((row) => row.key === "TRIV")?.value).toBe("70.00 ms");
    expect(stored).toMatchObject(raw);
    const confirmed = buildEchoReportGroups({ ...stored, Diastolica_ondas: "separadas", TDI_ondas: "separadas" }, null, new Set(), undefined, species).flatMap((group) => group.rows);
    expect(confirmed.some((row) => row.value.includes("valor a confirmar"))).toBe(false);
  });
  it("preserves genuine legacy canine presentation and lets fusion precedence mask the shared index", () => {
    const legacy = buildEchoReportGroups(raw, null, new Set(), undefined, "Canina").flatMap((group) => group.rows);
    expect(legacy.find((row) => row.key === "E_A")?.value).toBe("0.70");
    const mixed = buildEchoReportGroups({ ...raw, Diastolica_ondas: "nao_confirmadas", TDI_ondas: "fundidas" }, null, new Set(), undefined, "Canina").flatMap((group) => group.rows);
    expect(mixed.find((row) => row.key === "E_E_linha")?.value).toBe("Não mensurável");
    expect(mixed.find((row) => row.key === "E_A")?.value).toBe("0.70 (valor a confirmar)");
  });
});
