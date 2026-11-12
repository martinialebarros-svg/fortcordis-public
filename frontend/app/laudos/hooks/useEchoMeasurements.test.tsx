import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useEchoMeasurements } from "./useEchoMeasurements";
import { confirmedUnitKey, updateEchoMeasurement } from "@/lib/echo-unit-provenance";
import { parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";
import { NEW_CANINE_REPORT_PROTOCOL } from "@/lib/echo-new-report-defaults";

function edit(hook: { result: { current: ReturnType<typeof useEchoMeasurements> } }, key: string, value: string) {
  act(() => hook.result.current.setMeasurements((previous) => updateEchoMeasurement(previous, key, value)));
}

describe("ownership da razão AE/Ao no formulário", () => {
  it("snapshot recupera razão importada independente sem recalcular nem reaplicar defaults de espécie", () => {
    const hook = renderHook(({ species }) => useEchoMeasurements({ newReportSpecies: species }), { initialProps: { species: "Canina" } });
    const restored = { measurements: { Aorta: "10", Atrio_esquerdo: "14.6", AE_Ao: "1,40",
      AE_Ao_metodo: "", Diastolica_ondas: "fundidas", TDI_metodo: "", Onda_E: "", Onda_A: "0", MV_E: "1.8" }, aeAoDerived: false };
    act(() => {
      hook.result.current.restoreState(restored, "Cat");
      hook.rerender({ species: "Cat" });
    });
    expect(hook.result.current.exportState()).toEqual(restored);
    const exported = hook.result.current.exportState();
    exported.measurements.AE_Ao = "9";
    expect(hook.result.current.measurements.AE_Ao).toBe("1,40");
    edit(hook, "Aorta", "");
    expect(hook.result.current.measurements.AE_Ao).toBe("1,40");
    expect(hook.result.current.measurements.Diastolica_ondas).toBe("fundidas");
  });

  it("snapshot de razão derivada continua limpando a razão ao perder um componente", () => {
    const hook = renderHook(() => useEchoMeasurements());
    const snapshot = { measurements: { Aorta: "10", Atrio_esquerdo: "14.6", AE_Ao: "1.46" }, aeAoDerived: true };
    act(() => hook.result.current.restoreState(snapshot));
    expect(hook.result.current.exportState()).toEqual(snapshot);
    edit(hook, "Aorta", "");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
  });

  it("calcula imediatamente e limpa a razão derivada ao apagar qualquer componente", () => {
    const hook = renderHook(() => useEchoMeasurements());
    edit(hook, "Aorta", "10");
    edit(hook, "Atrio_esquerdo", "14,6");
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
    edit(hook, "AE_Ao_metodo", "2d_eixo_curto_diastole_inicial");
    edit(hook, "Aorta", "");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao_metodo");
    edit(hook, "Aorta", "10");
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
    edit(hook, "Atrio_esquerdo", "");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
    expect(hook.result.current.measurements.Aorta).toBe("10");
  });

  it.each(["0", "-1", "NaN", "Infinity", "10abc", "   "])("limpa o cálculo anterior se a origem fica inválida (%s)", (invalid) => {
    const hook = renderHook(() => useEchoMeasurements());
    act(() => hook.result.current.replaceMeasurements({ Aorta: "10", Atrio_esquerdo: "14.6" }));
    edit(hook, "Aorta", invalid);
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
  });

  it("respeita cm/mm confirmados e suspende uma origem ambígua", () => {
    const hook = renderHook(() => useEchoMeasurements());
    act(() => hook.result.current.replaceMeasurements({
      Aorta: "1", Atrio_esquerdo: "14.6", [confirmedUnitKey("Aorta")]: "cm",
    }));
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
    edit(hook, confirmedUnitKey("Aorta"), "mm");
    expect(hook.result.current.measurements.AE_Ao).toBe("14.60");

    act(() => hook.result.current.replaceMeasurements({
      Aorta: "1", Atrio_esquerdo: "1.46", SIVd: "1.2",
      [confirmedUnitKey("Aorta")]: "cm", [confirmedUnitKey("Atrio_esquerdo")]: "cm",
    }));
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
    edit(hook, confirmedUnitKey("Aorta"), "");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
  });

  it("preserva AE/Ao independente importado sem diâmetros no save, edição e reload", () => {
    const hook = renderHook(() => useEchoMeasurements());
    act(() => hook.result.current.importMeasurements({ AE_Ao: "1.46" }));
    edit(hook, "Aorta", "");
    edit(hook, "Atrio_esquerdo", "");
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
    const saved = JSON.parse(JSON.stringify(hook.result.current.measurements));
    expect(Object.keys(saved)).toEqual(["AE_Ao", "Aorta", "Atrio_esquerdo"]);
    act(() => hook.result.current.replaceMeasurements(parseStoredEchoMeasurements(saved)));
    edit(hook, "Aorta", "0");
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
  });

  it("reimportação direta coincidente com o último auto não herda ownership", () => {
    const hook = renderHook(() => useEchoMeasurements());
    act(() => hook.result.current.replaceMeasurements({ Aorta: "10", Atrio_esquerdo: "14.6" }));
    act(() => hook.result.current.importMeasurements({ AE_Ao: "1.46" }));
    // O effect dos demais índices e a confirmação do método clonam medidas.
    act(() => hook.result.current.setMeasurements((previous) => ({ ...previous, E_A: "1.2", DIVEd_normalizado: "1.5" })));
    edit(hook, "AE_Ao_metodo", "2d_eixo_curto_diastole_inicial");
    edit(hook, "Aorta", "");
    edit(hook, "Atrio_esquerdo", "");
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao_metodo");
  });

  it("importação explícita tem precedência sobre o cálculo mesmo com ambos diâmetros", () => {
    const hook = renderHook(() => useEchoMeasurements());
    act(() => hook.result.current.importMeasurements({ Aorta: "10", Atrio_esquerdo: "14.6", AE_Ao: "1.4" }));
    expect(hook.result.current.measurements.AE_Ao).toBe("1.4");
    edit(hook, "Aorta", "");
    expect(hook.result.current.measurements.AE_Ao).toBe("1.4");
    edit(hook, "Aorta", "10");
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
    edit(hook, "Atrio_esquerdo", "");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
  });

  it("reconstrói derivação após reload com componentes válidos e não herda o exame anterior", () => {
    const hook = renderHook(() => useEchoMeasurements());
    act(() => hook.result.current.replaceMeasurements(parseStoredEchoMeasurements({ Aorta: "10", Atrio_esquerdo: "14.6", AE_Ao: "1.46" })));
    act(() => hook.result.current.setMeasurements((previous) => ({ ...previous, TAPSE: "12" })));
    edit(hook, "Aorta", "");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
    act(() => hook.result.current.replaceMeasurements({ AE_Ao: "1.2" }));
    edit(hook, "Aorta", "");
    expect(hook.result.current.measurements).toEqual({ AE_Ao: "1.2", Aorta: "" });
    act(() => hook.result.current.replaceMeasurements({}));
    expect(hook.result.current.measurements).toEqual({});
  });

  it("não combina diâmetro de nova importação com componente remanescente para derivar a razão", () => {
    const hook = renderHook(() => useEchoMeasurements());
    act(() => hook.result.current.replaceMeasurements({ Aorta: "10", Atrio_esquerdo: "14.6" }));
    act(() => hook.result.current.importMeasurements({ Aorta: "12" }));
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
    act(() => hook.result.current.setMeasurements((previous) => ({ ...previous, E_A: "1.2" })));
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
    act(() => hook.result.current.importMeasurements({ Aorta: "12", Atrio_esquerdo: "18" }));
    expect(hook.result.current.measurements.AE_Ao).toBe("1.50");
  });

  it("normaliza alias de importação e preserva ratio órfão histórico conservadoramente", () => {
    const hook = renderHook(() => useEchoMeasurements());
    act(() => hook.result.current.importMeasurements({ LA_Ao: "1.46" }));
    expect(hook.result.current.measurements).toEqual({ AE_Ao: "1.46" });
    act(() => hook.result.current.replaceMeasurements(parseStoredEchoMeasurements(null,
      "## Medidas Ecocardiográficas\n- AE_Ao: 1,46\n\n## Avaliação Qualitativa")));
    edit(hook, "Aorta", "");
    expect(hook.result.current.measurements.AE_Ao).toBe("1.46");
  });
});

describe("técnicas de rotina nos novos laudos", () => {
  it("inicia somente o novo laudo canino com as seis escolhas do veterinário", () => {
    const hook = renderHook(() => useEchoMeasurements({ newReportSpecies: "Canina" }));
    expect(hook.result.current.measurements).toEqual({
      Diastolica_metodo: "canino_nao_sedado_pw_apical", Diastolica_ondas: "separadas",
      TDI_metodo: "canino_pw_basal_lateral_wess", TDI_ondas: "separadas",
      TAPSE_metodo: "modo_m_apical", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco",
    });
  });

  it("mantém os padrões ao importar e editar medidas, sem perder a derivação AE/Ao", () => {
    const hook = renderHook(() => useEchoMeasurements({ newReportSpecies: "Canina" }));
    act(() => hook.result.current.importMeasurements({
      Onda_E: "0.62", Onda_A: "0.54", e_doppler: "0.09", a_doppler: "0.06",
      TAPSE: "9.79", Aorta: "12.36", Atrio_esquerdo: "16.82", AE_Ao: "1.36",
    }));
    edit(hook, "Aorta", "12.5");
    edit(hook, "Onda_E", "0.65");
    expect(hook.result.current.measurements).toMatchObject(NEW_CANINE_REPORT_PROTOCOL);
    expect(hook.result.current.measurements.AE_Ao).toBe("1.35");
    edit(hook, "Aorta", "");
    expect(hook.result.current.measurements).not.toHaveProperty("AE_Ao");
    expect(hook.result.current.measurements.AE_Ao_metodo).toBe(NEW_CANINE_REPORT_PROTOCOL.AE_Ao_metodo);
  });

  it("preserva alterações manuais, ondas fundidas e escolhas vazias após reimportar e renderizar", () => {
    const hook = renderHook(() => useEchoMeasurements({ newReportSpecies: "Canina" }));
    act(() => {
      hook.result.current.setProtocolMeasurement("Diastolica_ondas", "fundidas");
      hook.result.current.setProtocolMeasurement("TDI_metodo", "canino_pw_basal_septal_wess");
      hook.result.current.setProtocolMeasurement("TAPSE_metodo", "2d");
      hook.result.current.setProtocolMeasurement("AE_Ao_metodo", "");
    });
    act(() => hook.result.current.importMeasurements({ Onda_E: "0.62", e_doppler: "0.09", TAPSE: "10", AE_Ao: "1.36" }));
    hook.rerender();
    expect(hook.result.current.measurements).toMatchObject({
      Diastolica_ondas: "fundidas", TDI_ondas: "separadas",
      TDI_metodo: "canino_pw_basal_septal_wess", TAPSE_metodo: "2d", AE_Ao_metodo: "",
    });
  });

  it.each(["Felina", "Gato", "Equina", ""])("não preenche técnicas caninas para %s", (species) => {
    const hook = renderHook(() => useEchoMeasurements({ newReportSpecies: species }));
    expect(hook.result.current.measurements).toEqual({});
  });

  it("remove técnicas caninas ao trocar a espécie, preservando valores numéricos", () => {
    const hook = renderHook(({ species }) => useEchoMeasurements({ newReportSpecies: species }), {
      initialProps: { species: "Canina" },
    });
    act(() => hook.result.current.importMeasurements({ Onda_E: "0.62" }));
    hook.rerender({ species: "Felina" });
    expect(hook.result.current.measurements).toEqual({ Onda_E: "0.62" });
    hook.rerender({ species: "Cão" });
    expect(hook.result.current.measurements).toMatchObject(NEW_CANINE_REPORT_PROTOCOL);
  });

  it("não transforma fusão observada em ondas separadas ao trocar a espécie", () => {
    const hook = renderHook(({ species }) => useEchoMeasurements({ newReportSpecies: species }), {
      initialProps: { species: "Felina" },
    });
    act(() => hook.result.current.setMeasurements({ Diastolica_ondas: "fundidas", TDI_ondas: "nao_confirmadas" }));
    hook.rerender({ species: "Canina" });
    expect(hook.result.current.measurements).toMatchObject({
      Diastolica_metodo: "canino_nao_sedado_pw_apical", Diastolica_ondas: "fundidas", TDI_ondas: "nao_confirmadas",
    });
    hook.rerender({ species: "Felina" });
    expect(hook.result.current.measurements).toEqual({ Diastolica_ondas: "fundidas", TDI_ondas: "nao_confirmadas" });
  });

  it("não preenche laudo existente e mantém a invalidação de aquisição histórica", () => {
    const hook = renderHook(() => useEchoMeasurements());
    expect(hook.result.current.measurements).toEqual({});
    act(() => hook.result.current.replaceMeasurements({ Onda_E: "0.62", ...NEW_CANINE_REPORT_PROTOCOL }));
    edit(hook, "Onda_E", "0.65");
    expect(hook.result.current.measurements.Diastolica_metodo).toBeUndefined();
    expect(hook.result.current.measurements.Diastolica_ondas).toBe("nao_confirmadas");
  });
});
