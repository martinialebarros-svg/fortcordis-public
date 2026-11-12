import { canonicalFelineDiastolicKey } from "./echo-feline-diastolic-reference";
import { deriveAutomaticEchoMeasurements } from "./echo-derived-measurements";
import { isFelineEchoSpecies } from "./echo-species";
import { updateEchoMeasurement } from "./echo-unit-provenance";

type Measurements = Record<string, string>;
export type FelineWaveKind = "transmitral" | "tissue";

const FUSED_KEYS: Record<FelineWaveKind, readonly string[]> = {
  transmitral: ["Onda_E", "Onda_A", "E_A", "TD", "E_TRIV", "E_E_linha"],
  tissue: ["e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"],
};
const DEPENDENT_RATIOS: Record<string, readonly string[]> = {
  Onda_E: ["E_A", "E_TRIV", "E_E_linha"],
  Onda_A: ["E_A"],
  TRIV: ["E_TRIV"],
  e_doppler: ["E_E_linha", "doppler_tecidual_relacao"],
  a_doppler: ["doppler_tecidual_relacao"],
};

function withoutKeys(measurements: Measurements, keys: readonly string[]): Measurements {
  return Object.fromEntries(Object.entries(measurements)
    .filter(([key]) => !keys.includes(canonicalFelineDiastolicKey(key))));
}

/** Explicit operator correction, never invoked by loading, importing or merely
 * selecting fusion. Keep acquisition metadata and independent measurements. */
export function discardFelineFusedMeasurements(
  measurements: Measurements, species: string, kind: FelineWaveKind,
): Measurements {
  const waveKey = kind === "transmitral" ? "Diastolica_ondas" : "TDI_ondas";
  if (!isFelineEchoSpecies(species) || measurements[waveKey] !== "fundidas") return measurements;
  return withoutKeys(measurements, FUSED_KEYS[kind]);
}

/** A manual correction of an origin invalidates only its old dependent ratios.
 * Independent historic ratios survive untouched load/import/save cycles. */
export function updateFelineDiastolicMeasurement(
  measurements: Measurements, key: string, value: string, species: string,
): Measurements {
  const next = updateEchoMeasurement(measurements, key, value);
  if (!isFelineEchoSpecies(species) || value === measurements[key]) return next;
  const dependencies = DEPENDENT_RATIOS[canonicalFelineDiastolicKey(key)];
  return dependencies ? withoutKeys(next, dependencies) : next;
}

/** Imported ratios remain editable while no applicable calculation exists. */
export function isEchoDiastolicRatioCalculated(
  measurements: Measurements, weightKg: unknown, species: string, key: string,
): boolean {
  return Object.hasOwn(deriveAutomaticEchoMeasurements(measurements, weightKg, species), key);
}
