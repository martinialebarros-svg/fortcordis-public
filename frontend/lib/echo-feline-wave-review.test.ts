import { describe, expect, it } from "vitest";
import { discardFelineFusedMeasurements, isEchoDiastolicRatioCalculated, updateFelineDiastolicMeasurement } from "./echo-feline-wave-review";
import { deriveAutomaticEchoMeasurements, parseStoredEchoMeasurements } from "./echo-derived-measurements";

const recorded = {
  Onda_E: "1.08", Onda_A: "0.95", E_A: "1.14", TD: "51", TRIV: "40", E_TRIV: "2.7",
  e_doppler: "0.16", a_doppler: "0.06", doppler_tecidual_relacao: "2.67", E_E_linha: "6.95",
  Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "fundidas",
  TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas", DIVEd: "17.06",
};

describe("revisão explícita de ondas felinas importadas", () => {
  it.each(["Felina", "Gato", "Cat", "Feline"])("remove grupo transmitral inválido para %s sem apagar TRIV ou TDI", (species) => {
    const input = { ...recorded, MV_E_A: "1.14", MV_E: "1.08", MV_E_TRIV: "2.7", EEp: "6.95" };
    const result = discardFelineFusedMeasurements(input, species, "transmitral");
    for (const key of ["Onda_E", "Onda_A", "TD", "E_A", "E_TRIV", "E_E_linha", "MV_E_A", "MV_E", "MV_E_TRIV", "EEp"]) {
      expect(result).not.toHaveProperty(key);
    }
    expect(result).toEqual({ TRIV: "40", e_doppler: "0.16", a_doppler: "0.06", doppler_tecidual_relacao: "2.67",
      Diastolica_metodo: recorded.Diastolica_metodo, Diastolica_ondas: "fundidas", TDI_metodo: recorded.TDI_metodo,
      TDI_ondas: "separadas", DIVEd: "17.06" });
    expect(input.Onda_E).toBe("1.08");
    const saved = { ...result, ...deriveAutomaticEchoMeasurements(result, 5.6, species) };
    expect(parseStoredEchoMeasurements(saved)).not.toHaveProperty("E_A");
  });

  it("remove grupo tecidual sem apagar velocidades transmitrais ou TRIV", () => {
    const input = { ...recorded, Diastolica_ondas: "separadas", TDI_ondas: "fundidas", TDI_e: "0.16", TDI_a: "0.06" };
    const result = discardFelineFusedMeasurements(input, "Gato", "tissue");
    for (const key of ["e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha", "TDI_e", "TDI_a"]) expect(result).not.toHaveProperty(key);
    expect(result).toMatchObject({ Onda_E: "1.08", Onda_A: "0.95", TRIV: "40", E_A: "1.14", TDI_ondas: "fundidas" });
  });

  it("não limpa dados por espécie ou condição não aplicável", () => {
    expect(discardFelineFusedMeasurements(recorded, "Canina", "transmitral")).toBe(recorded);
    expect(discardFelineFusedMeasurements(recorded, "Felina", "tissue")).toBe(recorded);
    const unknown = { ...recorded, Diastolica_ondas: "" };
    expect(discardFelineFusedMeasurements(unknown, "Felina", "transmitral")).toBe(unknown);
  });

  it.each(["0", "", "1.2"])("correção explícita de E para %s invalida suas relações, sem recriar valores importados", (value) => {
    const result = updateFelineDiastolicMeasurement(recorded, "Onda_E", value, "Cat");
    expect(result.Onda_E).toBe(value);
    for (const key of ["E_A", "E_TRIV", "E_E_linha", "Diastolica_metodo"]) expect(result).not.toHaveProperty(key);
    expect(result.Diastolica_ondas).toBe("nao_confirmadas");
    expect(result).toMatchObject({ TRIV: "40", e_doppler: "0.16", doppler_tecidual_relacao: "2.67", TDI_ondas: "separadas" });
  });

  it("corrigir uma origem preserva relações independentes e atualização sem mudança não limpa", () => {
    expect(updateFelineDiastolicMeasurement(recorded, "Onda_E", "1.08", "Cat")).toEqual(recorded);
    const a = updateFelineDiastolicMeasurement(recorded, "Onda_A", "0", "Felina");
    expect(a).not.toHaveProperty("E_A");
    expect(a.E_TRIV).toBe("2.7");
    const e = updateFelineDiastolicMeasurement(recorded, "e_doppler", "", "Felina");
    expect(e).not.toHaveProperty("E_E_linha");
    expect(e).not.toHaveProperty("doppler_tecidual_relacao");
    expect(e.E_A).toBe("1.14");
    expect(updateFelineDiastolicMeasurement(recorded, "Onda_E", "0", "Canina").E_A).toBe("1.14");
  });

  it("relações só ficam bloqueadas para digitação quando há cálculo aplicável", () => {
    expect(isEchoDiastolicRatioCalculated(recorded, 5.6, "Gato", "E_A")).toBe(false);
    expect(isEchoDiastolicRatioCalculated({ ...recorded, Diastolica_ondas: "separadas" }, 5.6, "Gato", "E_A")).toBe(true);
    expect(isEchoDiastolicRatioCalculated({ ...recorded, Diastolica_ondas: "separadas", Onda_A: "0" }, 5.6, "Gato", "E_A")).toBe(false);
    expect(isEchoDiastolicRatioCalculated(recorded, 5.6, "Gato", "doppler_tecidual_relacao")).toBe(true);
  });
});
