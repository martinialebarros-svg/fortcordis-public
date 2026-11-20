import { describe, expect, it } from "vitest";
import { deriveAutomaticEchoMeasurements, parseStoredEchoMeasurements } from "./echo-derived-measurements";
import { mergeImportedEchoMeasurements, updateEchoMeasurement } from "./echo-unit-provenance";

describe("deriveAutomaticEchoMeasurements", () => {
  it("preserva a presença canônica diastólica vazia ou inválida sem recuperar a descrição histórica", () => {
    const keys = ["Onda_E", "Onda_A", "E_A", "TD", "TRIV", "E_TRIV", "e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"];
    for (const key of keys) {
      for (const value of ["", null, undefined, NaN, "NaN", 0, "0"]) {
        const raw = { [key]: value };
        const before = { ...raw };
        const description = `## Medidas Ecocardiograficas\n- ${key}: 1.80\n- MV_E: 1.90\n\n## Avaliacao Qualitativa`;
        const parsed = parseStoredEchoMeasurements(raw, description);
        expect(parsed).toEqual({ [key]: String(value ?? "") });
        expect(raw).toEqual(before);
      }
    }
    expect(parseStoredEchoMeasurements({ DIVEd: "", unrelated: "NaN", Diastolica_metodo: "inferido" })).toEqual({});
  });

  it("lê a canônica diastólica vazia na mesma linha sem consumir o alias da linha seguinte", () => {
    for (const canonicalFirst of [true, false]) {
      const lines = ["- Onda_E: ", "- MV_E: 1.80"];
      const description = "## Medidas Ecocardiograficas\n" +
        (canonicalFirst ? lines : lines.toReversed()).join("\n") + "\n\n## Avaliacao Qualitativa";
      expect(parseStoredEchoMeasurements(null, description)).toEqual({ Onda_E: "", MV_E: "1.80" });
    }
  });

  it.each(["Canina", "Felina"])("não usa alias para recalcular índices após hidratar uma origem limpa em %s", (species) => {
    for (const value of ["", null, NaN, 0]) {
      const raw = { MV_E: "1.80", Onda_E: value, Onda_A: "0.50", TRIV: "70", e_doppler: "0.09",
        E_A: "0.70", E_TRIV: "0.55", E_E_linha: "6.71", Diastolica_ondas: "nao_confirmadas", TDI_ondas: "separadas" };
      const before = { ...raw };
      const parsed = parseStoredEchoMeasurements(raw);
      const derived = deriveAutomaticEchoMeasurements(parsed, 10, species);
      expect(parsed).toHaveProperty("Onda_E", String(value ?? ""));
      expect(parsed.MV_E).toBe("1.80");
      for (const key of ["E_A", "E_TRIV", "E_E_linha"]) expect(derived).not.toHaveProperty(key);
      expect({ ...parsed, ...derived }).toMatchObject({ E_A: "0.70", E_TRIV: "0.55", E_E_linha: "6.71" });
      expect(raw).toEqual(before);
    }
  });

  it.each(["Felina", "felino", "FELINOS", "Feline", " Gato ", "gatos", "Cat", "CATS"])
    ("preserva relações históricas e fusões independentes para %s", (species) => {
      const historical = {
        Onda_E: "1.08", Onda_A: "0.95", TRIV: "40", e_doppler: "0.16", a_doppler: "0.08",
        E_A: "1.13", E_TRIV: "2.66", E_E_linha: "6.95", doppler_tecidual_relacao: "1.8",
        Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico",
        Diastolica_ondas: "fundidas", TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "fundidas",
      };
      const before = { ...historical };
      for (const waves of ["", "fundidas"]) {
        const context = { ...historical, Diastolica_ondas: waves, TDI_ondas: waves };
        const derived = deriveAutomaticEchoMeasurements(context, 5.6, species);
        for (const key of ["E_A", "E_TRIV", "E_E_linha", "doppler_tecidual_relacao"]) {
          expect(derived).not.toHaveProperty(key);
        }
        expect({ ...context, ...derived }).toMatchObject({
          E_A: "1.13", E_TRIV: "2.66", E_E_linha: "6.95", doppler_tecidual_relacao: "1.8",
        });
      }
      const tissueSeparate = deriveAutomaticEchoMeasurements({ ...historical, TDI_ondas: "separadas" }, 5.6, species);
      expect(tissueSeparate.doppler_tecidual_relacao).toBe("2");
      expect(tissueSeparate).not.toHaveProperty("E_A");
      expect(tissueSeparate).not.toHaveProperty("E_E_linha");
      const flowSeparate = deriveAutomaticEchoMeasurements({ ...historical, Diastolica_ondas: "separadas" }, 5.6, species);
      expect(flowSeparate).toMatchObject({ E_A: "1.14", E_TRIV: "2.7" });
      expect(flowSeparate).not.toHaveProperty("E_E_linha");
      expect(flowSeparate).not.toHaveProperty("doppler_tecidual_relacao");
      const separate = { ...historical, Diastolica_ondas: "separadas", TDI_ondas: "separadas" };
      expect(deriveAutomaticEchoMeasurements(separate, 5.6, species)).toMatchObject({
        E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.75", doppler_tecidual_relacao: "2",
      });
      for (const changedFlow of [updateEchoMeasurement(separate, "Onda_E", "1.1"), mergeImportedEchoMeasurements(separate, { Onda_E: "1.08" })]) {
        const derived = deriveAutomaticEchoMeasurements(changedFlow, 5.6, species);
        for (const key of ["E_A", "E_TRIV", "E_E_linha"]) expect(derived).not.toHaveProperty(key);
        expect(derived.doppler_tecidual_relacao).toBe("2");
      }
      const changedTissue = updateEchoMeasurement(separate, "e_doppler", "0.15");
      const derivedTissue = deriveAutomaticEchoMeasurements(changedTissue, 5.6, species);
      expect(derivedTissue).toMatchObject({ E_A: "1.14", E_TRIV: "2.7" });
      expect(derivedTissue).not.toHaveProperty("E_E_linha");
      expect(derivedTissue).not.toHaveProperty("doppler_tecidual_relacao");
      expect(historical).toEqual(before);
    });

  it("aplica os mesmos cálculos aos aliases caninos exatos sem aceitar prefixos", () => {
    const measurements = {
      Onda_E: "1.08", Onda_A: "0.95", TRIV: "40", e_doppler: "0.16", a_doppler: "0.08",
      DIVEd: "30", DIVEd_2D: "32", VE_vista_2D: "eixo_curto",
    };
    expect(deriveAutomaticEchoMeasurements(measurements, 10, "Canina")).toMatchObject({
      E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.75", doppler_tecidual_relacao: "2",
      DIVEd_normalizado: "1.52", DIVEd_normalizado_2D: "1.55",
    });
    for (const species of ["Dog", " Cão ", "cães", "Cachorro", "canino", "Canine"]) {
      expect(deriveAutomaticEchoMeasurements(measurements, 10, species)).toMatchObject({
        DIVEd_normalizado: "1.52", DIVEd_normalizado_2D: "1.55", E_A: "1.14",
      });
    }
    for (const species of ["CaninaXYZ", "Caninoide", "Dogfish", "Felina"]) {
      const derived = deriveAutomaticEchoMeasurements(measurements, 10, species);
      expect(derived).not.toHaveProperty("DIVEd_normalizado");
      expect(derived).not.toHaveProperty("DIVEd_normalizado_2D");
    }
  });

  it("exige separação felina confirmada após editar ou reimportar origens de um contexto fundido", () => {
    const historical = { Onda_E: "1.08", Onda_A: "0.95", TRIV: "40", e_doppler: "0.16", E_A: "1.13", E_TRIV: "2.66", E_E_linha: "6.95", Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "fundidas", TDI_ondas: "separadas" };
    const contexts = [
      updateEchoMeasurement(historical, "Onda_E", "1.1"),
      mergeImportedEchoMeasurements(historical, { Onda_E: "1.08", Onda_A: "0.95" }),
      { ...historical, Diastolica_ondas: "" },
    ];
    for (const context of contexts) {
      const calculated = deriveAutomaticEchoMeasurements(context, 5.6, "Felina");
      for (const key of ["E_A", "E_TRIV", "E_E_linha"]) expect(calculated).not.toHaveProperty(key);
      const kept = { ...context, ...calculated };
      expect(kept).toMatchObject({ E_A: "1.13", E_TRIV: "2.66", E_E_linha: "6.95" });
    }
    const separate = { ...historical, Diastolica_ondas: "separadas" };
    expect(deriveAutomaticEchoMeasurements(separate, 5.6, "Felina")).toMatchObject({ E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.75" });
    const editedTissue = updateEchoMeasurement(separate, "e_doppler", "0.15");
    expect(deriveAutomaticEchoMeasurements(editedTissue, 5.6, "Felina")).not.toHaveProperty("E_E_linha");
    expect(deriveAutomaticEchoMeasurements({ ...historical, Diastolica_ondas: "", TDI_ondas: "" }, 5.6, "Canina"))
      .toMatchObject({ E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.75" });
  });
  it("persiste os controles diastólicos e teciduais sem inferi-los das medidas", () => {
    const metadata = { Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "fundidas",
      TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas" };
    expect(parseStoredEchoMeasurements(metadata)).toEqual(metadata);
    const description = "## Medidas Ecocardiograficas\n" + Object.entries(metadata).map(([key, value]) => `- ${key}: ${value}`).join("\n") + "\n\n## Avaliacao Qualitativa";
    expect(parseStoredEchoMeasurements(null, description)).toEqual(metadata);
    expect(parseStoredEchoMeasurements({ TDI_metodo: "inferido", Diastolica_ondas: "provavelmente_separadas" })).toEqual({});
  });

  it("não recalcula relações com ondas felinas explicitamente fundidas e conserva o histórico", () => {
    const raw = { Onda_E: "1.08", Onda_A: "0.95", e_doppler: "0.16", a_doppler: "0.08", TRIV: "40", E_A: "1.13", E_E_linha: "6.95", doppler_tecidual_relacao: "1.8", Diastolica_ondas: "fundidas", TDI_ondas: "separadas" };
    const derived = deriveAutomaticEchoMeasurements(raw, 5.6, "Felina");
    expect(derived).not.toHaveProperty("E_A");
    expect(derived).not.toHaveProperty("E_E_linha");
    expect(derived).not.toHaveProperty("E_TRIV");
    expect(derived.doppler_tecidual_relacao).toBe("2");
    expect(raw.E_E_linha).toBe("6.95");
    expect(deriveAutomaticEchoMeasurements({ ...raw, TDI_ondas: "fundidas" }, 5.6, "Felina")).not.toHaveProperty("doppler_tecidual_relacao");
    expect(deriveAutomaticEchoMeasurements({ ...raw, TDI_ondas: "" }, 5.6, "Felina")).not.toHaveProperty("doppler_tecidual_relacao");
    expect(deriveAutomaticEchoMeasurements(raw, 5.6, "Canina")).not.toHaveProperty("E_A");
    expect(deriveAutomaticEchoMeasurements(raw, 5.6, "Canina")).not.toHaveProperty("E_E_linha");
  });
  it("calcula E/A, E/TRIV e E/e' automaticamente a partir das medidas de origem", () => {
    expect(
      deriveAutomaticEchoMeasurements(
        {
          Onda_E: "1,20",
          Onda_A: "0,60",
          TRIV: "48",
          e_doppler: "0,10",
        },
        "10"
      )
    ).toMatchObject({
      E_A: "2",
      E_TRIV: "2.5",
      E_E_linha: "12",
    });
  });

  it("preserva relações históricas quando não há medidas suficientes para recalculá-las", () => {
    const automaticas = deriveAutomaticEchoMeasurements(
      {
        E_A: "1.35",
        E_TRIV: "2.2",
        E_E_linha: "12.4",
        Onda_E: "1.17",
      },
      "10"
    );

    expect(automaticas).not.toHaveProperty("E_A");
    expect(automaticas).not.toHaveProperty("E_TRIV");
    expect(automaticas).not.toHaveProperty("E_E_linha");
  });

  it("lê unidade confirmada e calcula DIVEd normalizado somente com unidade conhecida", () => {
    const description = "## Medidas Ecocardiograficas\n- DIVEd: 2.5\n- SIVd: 3.0\n- PLVEd: 0.8\n- unidade_confirmada_DIVEd: cm\n- unidade_confirmada_SIVd: mm\n\n## Avaliacao Qualitativa";
    const parsed = parseStoredEchoMeasurements(null, description);
    expect(parsed.unidade_confirmada_DIVEd).toBe("cm");
    expect(parsed.unidade_confirmada_SIVd).toBe("mm");
    expect(deriveAutomaticEchoMeasurements(parsed, 10, "Canina").DIVEd_normalizado).toBe("1.27");
    expect(deriveAutomaticEchoMeasurements({ DIVEd: "2.5", SIVd: "3.0", PLVEd: "0.8" }, 10, "Canina").DIVEd_normalizado).toBe("");
    expect(parseStoredEchoMeasurements(null, description.replace("cm", "metros"))).not.toHaveProperty("unidade_confirmada_DIVEd");
  });

  it("preserva somente vistas 2D explicitamente confirmadas", () => {
    const description = "## Medidas Ecocardiograficas\n- DIVEd_2D: 33.53\n- VE_vista_2D: eixo_curto\n\n## Avaliacao Qualitativa";
    expect(parseStoredEchoMeasurements(null, description).VE_vista_2D).toBe("eixo_curto");
    expect(parseStoredEchoMeasurements(null, description.replace("eixo_curto", "desconhecida"))).not.toHaveProperty("VE_vista_2D");
    expect(deriveAutomaticEchoMeasurements({ DIVEd_2D: "33.53", VE_vista_2D: "eixo_curto" }, 13.6, "Canina").DIVEd_normalizado_2D).toBe("1.47");
    expect(deriveAutomaticEchoMeasurements({ DIVEd_2D: "33.53", VE_vista_2D: "eixo_curto" }, 13.6, "Felina")).not.toHaveProperty("DIVEd_normalizado_2D");
  });

  it("persiste apenas métodos de TAPSE e AE/Ao explicitamente selecionados", () => {
    const saved = { TAPSE: "10", TAPSE_metodo: "modo_m_apical", AE_Ao: "1.42", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" };
    expect(parseStoredEchoMeasurements(saved)).toMatchObject(saved);
    const text = "## Medidas Ecocardiograficas\n- TAPSE: 10\n- TAPSE_metodo: 2d\n- AE_Ao_metodo: outro\n\n## Avaliacao Qualitativa";
    expect(parseStoredEchoMeasurements(null, text)).toMatchObject({ TAPSE_metodo: "2d", AE_Ao_metodo: "outro" });
    expect(parseStoredEchoMeasurements({ TAPSE_metodo: "modo_m", AE_Ao_metodo: "desconhecido" })).toEqual({});
    expect(parseStoredEchoMeasurements({ TAPSE: "10", AE_Ao: "1.42" })).not.toHaveProperty("TAPSE_metodo");
  });

  it("não calcula o índice de Cornell em felinos; deriva função atrial e gradiente da VSVE", () => {
    const raw = { DIVEd: "15", AE_diametro_max: "18", AE_diametro_min: "13.5", Vmax_VSVE: "2.5" };
    const derived = deriveAutomaticEchoMeasurements(raw, 4, "Felina");
    expect(derived).not.toHaveProperty("DIVEd_normalizado");
    expect(derived.Fracao_encurtamento_AE).toBe("25");
    expect(derived.Grad_VSVE).toBe("25");
    expect(deriveAutomaticEchoMeasurements({ ...raw, AE_diametro_min: "19" }, 4, "Felina"))
      .not.toHaveProperty("Fracao_encurtamento_AE");
  });
});


describe("explicit canine wave review protects historical diastolic ratios", () => {
  const recorded = { Onda_E: "1.08", Onda_A: "0.95", TRIV: "40", e_doppler: "0.16", a_doppler: "0.08", E_A: "1.13", E_TRIV: "2.66", E_E_linha: "6.95", doppler_tecidual_relacao: "1.8" };
  it.each(["Canina", "Cão", "Dog"])("separates fusion domains for %s without rewriting imported history", (species) => {
    const raw = Object.freeze({ ...recorded, Diastolica_ondas: "fundidas", TDI_ondas: "separadas" });
    const calculated = deriveAutomaticEchoMeasurements(raw, 10, species);
    for (const key of ["E_A", "E_TRIV", "E_E_linha"]) expect(calculated).not.toHaveProperty(key);
    expect(calculated.doppler_tecidual_relacao).toBe("2");
    expect({ ...raw, ...calculated }).toMatchObject({ E_A: "1.13", E_TRIV: "2.66", E_E_linha: "6.95" });
    const tissueFused = deriveAutomaticEchoMeasurements({ ...raw, Diastolica_ondas: "separadas", TDI_ondas: "fundidas" }, 10, species);
    expect(tissueFused).toMatchObject({ E_A: "1.14", E_TRIV: "2.7" });
    expect(tissueFused).not.toHaveProperty("E_E_linha");
    expect(tissueFused).not.toHaveProperty("doppler_tecidual_relacao");
    expect(deriveAutomaticEchoMeasurements(recorded, 10, species)).toMatchObject({ E_A: "1.14", E_E_linha: "6.75", E_TRIV: "2.7", doppler_tecidual_relacao: "2" });
    expect(raw.E_A).toBe("1.13");
  });
});


describe("invalidated acquisition review survives edits, imports and serialization", () => {
  const raw = { Onda_E: "1.08", Onda_A: "0.95", TRIV: "40", e_doppler: "0.16", a_doppler: "0.08", E_A: "1.13", E_TRIV: "2.66", E_E_linha: "6.95", doppler_tecidual_relacao: "1.8", Diastolica_metodo: "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo", Diastolica_ondas: "fundidas", TDI_metodo: "canino_pw_anel_septal_choi", TDI_ondas: "separadas" };
  const actions = [
    { name: "edit transmitral", domain: "flow", run: (values: Record<string, string>) => updateEchoMeasurement(values, "Onda_E", "1.10") },
    { name: "reimport transmitral", domain: "flow", run: (values: Record<string, string>) => mergeImportedEchoMeasurements(values, { Onda_E: "1.10" }) },
    { name: "edit tissue", domain: "tissue", run: (values: Record<string, string>) => updateEchoMeasurement(values, "e_doppler", "0.15") },
    { name: "reimport tissue", domain: "tissue", run: (values: Record<string, string>) => mergeImportedEchoMeasurements(values, { e_doppler: "0.15" }) },
  ];
  it.each(actions)("$name blocks only dependent calculations after reload and preserves the save payload", ({ run, domain }) => {
    const original = domain === "flow" ? raw : { ...raw, Diastolica_ondas: "separadas", TDI_ondas: "fundidas" };
    const edited = run(original);
    const waveKey = domain === "flow" ? "Diastolica_ondas" : "TDI_ondas";
    expect(edited[waveKey]).toBe("nao_confirmadas");
    const reloaded = parseStoredEchoMeasurements(JSON.parse(JSON.stringify(edited)));
    expect(reloaded[waveKey]).toBe("nao_confirmadas");
    const calculated = deriveAutomaticEchoMeasurements(reloaded, 10, "Cão");
    const blocked = domain === "flow" ? ["E_A", "E_TRIV", "E_E_linha"] : ["E_E_linha", "doppler_tecidual_relacao"];
    for (const key of blocked) expect(calculated).not.toHaveProperty(key);
    if (domain === "flow") expect(calculated.doppler_tecidual_relacao).toBe("2");
    else expect(calculated).toMatchObject({ E_A: "1.14", E_TRIV: "2.7" });
    const payload = { ...reloaded, ...calculated };
    for (const key of blocked) expect(payload[key]).toBe(raw[key as keyof typeof raw]);
    expect(payload[waveKey]).toBe("nao_confirmadas");
    const repeated = run(reloaded);
    expect(repeated[waveKey]).toBe("nao_confirmadas");
    const reconfirmed = { ...reloaded, [waveKey]: "separadas" };
    const afterConfirmation = deriveAutomaticEchoMeasurements(reconfirmed, 10, "Dog");
    for (const key of blocked) expect(afterConfirmation).toHaveProperty(key);
    expect(raw.Onda_E).toBe("1.08");
  });
  it("clearing a reviewed wave selection remains unknown across reload rather than reverting to legacy", () => {
    const cleared = updateEchoMeasurement(raw, "Diastolica_ondas", "");
    expect(cleared.Diastolica_ondas).toBe("nao_confirmadas");
    const reloaded = parseStoredEchoMeasurements(cleared);
    expect(deriveAutomaticEchoMeasurements(reloaded, 10, "Canina")).not.toHaveProperty("E_A");
    expect(updateEchoMeasurement({}, "Diastolica_ondas", "")).toEqual({});
  });
  it("a confirmed new acquisition with unknown separation never activates legacy calculations", () => {
    const values = { Onda_E: "1.08", Onda_A: "0.95", e_doppler: "0.16", a_doppler: "0.08", TRIV: "40", Diastolica_metodo: raw.Diastolica_metodo, TDI_metodo: raw.TDI_metodo };
    const calculated = deriveAutomaticEchoMeasurements(values, 10, "Canina");
    for (const key of ["E_A", "E_TRIV", "E_E_linha", "doppler_tecidual_relacao"]) expect(calculated).not.toHaveProperty(key);
    const legacy = { Onda_E: "1.08", Onda_A: "0.95", e_doppler: "0.16", a_doppler: "0.08", TRIV: "40" };
    expect(deriveAutomaticEchoMeasurements(legacy, 10, "Canina")).toMatchObject({ E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.75", doppler_tecidual_relacao: "2" });
    expect(mergeImportedEchoMeasurements(legacy, { Onda_E: "1.10" })).not.toHaveProperty("Diastolica_ondas");
  });
});
