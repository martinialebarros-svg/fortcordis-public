import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";
import { makePulmonaryReviewStamp } from "@/lib/echo-pulmonary-probability";
import { useEchoMeasurements } from "./useEchoMeasurements";
import { montarDescricaoEcocardiograma } from "@/lib/ecocardiograma-estruturado";

function reviewed(species = "Canina"): Record<string, string> {
  const values = { HP_ativa: "sim", HP_TRV: "adequado", HP_VSVD: "sem_obstrucao", HP_suporte_automatico: "sim",
    HP_ventriculos: "sem_sinais", HP_arteria_pulmonar: "sem_sinais", HP_atrio_cava: "sem_sinais", IT_Vmax: "3.2" };
  return { ...values, HP_revisao: makePulmonaryReviewStamp(values, species) };
}

describe("persistência e reconfirmação da avaliação de HP", () => {
  it("preserva revisão no dicionário oficial e decodifica uma camada JSON somente na descrição", () => {
    const fixture = { ...reviewed(), HP_observacoes: 'Aquisição revisada.\nTexto com "aspas".' };
    expect(parseStoredEchoMeasurements(fixture)).toEqual(fixture);
    const description = `## Medidas Ecocardiográficas\n${Object.entries(fixture).map(([key, value]) => `- ${key}: ${key.startsWith("HP_") ? JSON.stringify(value) : value}`).join("\n")}\n\n## Avaliação Qualitativa`;
    expect(parseStoredEchoMeasurements(null, description)).toEqual(fixture);
    expect(parseStoredEchoMeasurements(null, montarDescricaoEcocardiograma(fixture,
      { valvas: "", camaras: "", funcao: "", pericardio: "", vasos: "", ad_vd: "" }))).toEqual(fixture);
    expect(parseStoredEchoMeasurements({ HP_observacoes: '"Aspas literais"' }).HP_observacoes).toBe('"Aspas literais"');
    expect(parseStoredEchoMeasurements({ HP_ativa: "talvez", HP_VSVD: "normal", HP_revisao: "json inválido", HP_inventado: "sim" })).toEqual({});
  });

  it("invalida edição clínica e não revalida ao voltar ao número antigo", () => {
    const hook = renderHook(() => useEchoMeasurements({ species: "Canina" }));
    const fixture = reviewed();
    act(() => hook.result.current.replaceMeasurements(fixture));
    act(() => hook.result.current.setMeasurements((previous) => ({ ...previous, IT_Vmax: "3.20", IT_Grad: "40.96", PSAP: "45.96" })));
    expect(hook.result.current.measurements.HP_revisao).toBe(fixture.HP_revisao);
    act(() => hook.result.current.setMeasurements((previous) => ({ ...previous, IT_Vmax: "3.3" })));
    expect(hook.result.current.measurements.HP_revisao).toBe("");
    act(() => hook.result.current.setMeasurements((previous) => ({ ...previous, IT_Vmax: "3.2" })));
    expect(hook.result.current.measurements.HP_revisao).toBe("");
  });

  it("reimportação coincidente exige revisão e não importa decisões ou observações HP", () => {
    const hook = renderHook(() => useEchoMeasurements({ species: "Canina" }));
    const fixture = reviewed();
    act(() => hook.result.current.replaceMeasurements(fixture));
    act(() => hook.result.current.importMeasurements({ IT_Vmax: "3.2", HP_ativa: "", HP_TRV: "nao_mensuravel",
      HP_VSVD: "obstrucao", HP_ventriculos: "com_sinais", HP_suporte_automatico: "nao", HP_observacoes: "ditado", HP_revisao: fixture.HP_revisao }));
    expect(hook.result.current.measurements).toMatchObject({ ...fixture, HP_revisao: "" });
    expect(hook.result.current.measurements).not.toHaveProperty("HP_observacoes");
    act(() => hook.result.current.replaceMeasurements(fixture));
    act(() => hook.result.current.importMeasurements({ HP_TA: "45" }));
    expect(hook.result.current.measurements.HP_TA).toBe("45");
    expect(hook.result.current.measurements.HP_revisao).toBe("");
    act(() => hook.result.current.replaceMeasurements(fixture));
    act(() => hook.result.current.importMeasurements({ TD: "108" }));
    expect(hook.result.current.measurements.HP_revisao).toBe(fixture.HP_revisao);
  });

  it("recupera o snapshot literal e exige revisão ao alterar a espécie", () => {
    const hook = renderHook(({ species }) => useEchoMeasurements({ species }), { initialProps: { species: "Canina" } });
    const snapshot = { measurements: reviewed("Gato"), aeAoDerived: false };
    act(() => {
      hook.result.current.restoreState(snapshot, "Gato");
      hook.rerender({ species: "Gato" });
    });
    expect(hook.result.current.exportState()).toEqual(snapshot);
    hook.rerender({ species: "Canina" });
    expect(hook.result.current.measurements.HP_revisao).toBe("");
    hook.rerender({ species: "Gato" });
    expect(hook.result.current.measurements.HP_revisao).toBe("");
  });

  it("não remove uma revisão válida quando o carregamento oficial entrega a espécie junto às medidas", () => {
    const hook = renderHook(({ species }) => useEchoMeasurements({ species }), { initialProps: { species: "Canina" } });
    const fixture = reviewed("Gato");
    act(() => {
      hook.result.current.replaceMeasurements(parseStoredEchoMeasurements(fixture));
      hook.rerender({ species: "Gato" });
    });
    expect(hook.result.current.measurements.HP_revisao).toBe(fixture.HP_revisao);
  });
});
