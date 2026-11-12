import { describe, expect, it } from "vitest";
import { parseStoredEchoMeasurements } from "./echo-derived-measurements";
import { deriveOutflowGradients, ECHO_OUTFLOW_SITES } from "./echo-outflow";
import { clearReplacedOutflowProvenance, mapImportedEchoMeasurements, updateEchoOutflowMeasurement } from "./echo-outflow-editor";
import { montarDescricaoEcocardiograma } from "./ecocardiograma-estruturado";

describe("edição e importação dos locais de aquisição", () => {
  it.each(ECHO_OUTFLOW_SITES)("preserva precisão e origem de $label no ciclo de salvar/reabrir", ({ velocity, gradient, label }) => {
    const imported = mapImportedEchoMeasurements({
      [velocity]: "1.0100", [gradient]: "4.1100",
      [`${velocity}_origem`]: "importado", [`${gradient}_origem`]: "importado",
      [`${velocity}_rotulo_origem`]: `${label} Vmax`, [`${gradient}_rotulo_origem`]: `${label} PG`,
    });
    const saved = JSON.parse(JSON.stringify({ ...imported, ...deriveOutflowGradients(imported) }));
    const reopened = parseStoredEchoMeasurements(saved);
    expect(reopened).toEqual(imported);
    const savedDescription = montarDescricaoEcocardiograma(imported, {
      valvas: "", camaras: "", funcao: "", pericardio: "", vasos: "", ad_vd: "",
    });
    expect(parseStoredEchoMeasurements({}, savedDescription)).toEqual(imported);
    expect(reopened[gradient]).toBe("4.1100");
    expect(Object.keys(reopened).filter((key) => /^(Vmax|Grad)_/.test(key) && !key.includes("origem")))
      .toEqual([velocity, gradient]);
  });

  it("mantém a separação dos quatro locais e os metadados dos aliases explícitos", () => {
    const imported = mapImportedEchoMeasurements({
      Vmax_VSVE: 1.01, Grad_VSVE: 4.11, Vmax_Ao: 1.2, Grad_Ao: 5.79,
      Vmax_VSVD: 0.8, Grad_VSVD: 2.57, Vmax_Pulm: 0.9, Grad_Pulm: 3.25,
      Vmax_Ao_origem: "importado", Vmax_Ao_rotulo_origem: "Aortic Vmax",
      Vmax_Pulm_origem: "importado", Vmax_Pulm_rotulo_origem: "Pulmonic Vmax",
      Grad_VSVE_origem: "origem não reconhecida",
      desconhecido: "texto sem contrato",
    });
    expect(imported).toMatchObject({
      Vmax_VSVE: "1.01", Grad_VSVE: "4.11", Vmax_aorta: "1.2", Grad_aorta: "5.79",
      Vmax_VSVD: "0.8", Grad_VSVD: "2.57", Vmax_pulmonar: "0.9", Grad_pulmonar: "3.25",
      Vmax_aorta_origem: "importado", Vmax_aorta_rotulo_origem: "Aortic Vmax",
      Vmax_pulmonar_origem: "importado", Vmax_pulmonar_rotulo_origem: "Pulmonic Vmax",
    });
    expect(imported).not.toHaveProperty("desconhecido");
    expect(imported).not.toHaveProperty("Vmax_Ao");
    expect(imported).not.toHaveProperty("Grad_VSVE_origem");
  });

  it.each(["importado", "informado", undefined])("não substitui gradiente %s ao corrigir a velocidade", (origin) => {
    const current = { Vmax_VSVE: "1.01", Grad_VSVE: "4.11", ...(origin ? { Grad_VSVE_origem: origin } : {}) };
    const changed = updateEchoOutflowMeasurement(current, "Vmax_VSVE", "1.02");
    expect(changed.Grad_VSVE).toBe("4.11");
    expect(changed.Grad_VSVE_origem).toBe(origin);
    expect(changed.Vmax_VSVE_origem).toBe("informado");
  });

  it("recalcula apenas gradiente calculado e permite correção manual com Vmax presente", () => {
    const calculated = updateEchoOutflowMeasurement({}, "Vmax_VSVE", "1.01");
    expect(calculated).toMatchObject({ Grad_VSVE: "4.08", Grad_VSVE_origem: "calculado" });
    const updated = updateEchoOutflowMeasurement(calculated, "Vmax_VSVE", "1.02");
    expect(updated.Grad_VSVE).toBe("4.16");
    const manual = updateEchoOutflowMeasurement(updated, "Grad_VSVE", "4.11");
    expect(manual).toMatchObject({ Vmax_VSVE: "1.02", Grad_VSVE: "4.11", Grad_VSVE_origem: "informado" });
    expect(updateEchoOutflowMeasurement(manual, "Vmax_VSVE", "1.03").Grad_VSVE).toBe("4.11");
    expect(updateEchoOutflowMeasurement(updated, "Vmax_VSVE", "")).toMatchObject({ Grad_VSVE: "", Grad_VSVE_origem: "" });
  });

  it("não reinterpreta o local de registros legados", () => {
    const legacy = mapImportedEchoMeasurements({ Vmax_pulmonar: "0.80", Grad_pulmonar: "2.57" });
    const roundTrip = parseStoredEchoMeasurements(JSON.parse(JSON.stringify(legacy)));
    expect(roundTrip).toEqual({ Vmax_pulmonar: "0.80", Grad_pulmonar: "2.57" });
    expect(roundTrip).not.toHaveProperty("Vmax_VSVD");
    expect(roundTrip).not.toHaveProperty("Vmax_pulmonar_origem");
  });

  it("mantém conflito explícito na importação e reabertura, impedindo fallback numérico", () => {
    const unresolved = mapImportedEchoMeasurements({ Vmax_VSVE: "1.01",
      Grad_VSVE: "Conflito de medidas no exame de origem", Grad_VSVE_origem: "importado",
      Grad_VSVE_rotulo_origem: "LVOT maxPG: 4.11 mmHg | Gradiente VSVE: 9.25 mmHg" });
    const reopened = parseStoredEchoMeasurements(unresolved);
    expect(reopened).toEqual(unresolved);
    expect(deriveOutflowGradients(reopened)).toEqual({});
    expect(reopened.Grad_VSVE).toBe("Conflito de medidas no exame de origem");
  });

  it("remove atribuição antiga apenas das medidas substituídas por nova aquisição sem fonte", () => {
    const previous = { Vmax_VSVD: "0.8", Vmax_VSVD_origem: "importado", Vmax_VSVD_rotulo_origem: "RVOT Vmax",
      Grad_VSVD: "2.57", Grad_VSVD_origem: "importado", Grad_VSVD_rotulo_origem: "RVOT PG" };
    const cleared = clearReplacedOutflowProvenance(previous, { Vmax_VSVD: "0.81" });
    expect(cleared).not.toHaveProperty("Vmax_VSVD_origem");
    expect(cleared).not.toHaveProperty("Vmax_VSVD_rotulo_origem");
    expect(cleared).toMatchObject({ Grad_VSVD: "2.57", Grad_VSVD_rotulo_origem: "RVOT PG", Grad_VSVD_origem: "importado" });
    expect(clearReplacedOutflowProvenance(previous, { Vmax_VSVD: "0.81", Vmax_VSVD_origem: "importado" }))
      .toHaveProperty("Vmax_VSVD_origem", "importado");
  });
});
