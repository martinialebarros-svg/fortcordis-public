import {
  confirmedUnitKey,
  echoLengthInMm,
  mergeImportedEchoMeasurements,
  updateEchoMeasurement,
} from "./echo-unit-provenance";

type Measurements = Record<string, string>;

export interface EchoMeasurementState {
  measurements: Measurements;
  aeAoDerived: boolean;
}

const SOURCE_KEYS = [
  "Aorta", "Atrio_esquerdo",
  confirmedUnitKey("Aorta"), confirmedUnitKey("Atrio_esquerdo"),
] as const;

function calculateAeAo(measurements: Measurements): string | null {
  const aorta = echoLengthInMm(measurements, "Aorta");
  const atrium = echoLengthInMm(measurements, "Atrio_esquerdo");
  if (aorta === null || atrium === null) return null;
  const ratio = atrium / aorta;
  return Number.isFinite(ratio) && ratio > 0 ? ratio.toFixed(2) : null;
}

function deriveAeAo(measurements: Measurements, ratio: string): EchoMeasurementState {
  const next = updateEchoMeasurement(measurements, "AE_Ao", ratio);
  delete next.LA_Ao;
  return { measurements: next, aeAoDerived: true };
}

function clearDerivedAeAo(measurements: Measurements): EchoMeasurementState {
  const next = updateEchoMeasurement(measurements, "AE_Ao", "");
  delete next.AE_Ao;
  delete next.LA_Ao;
  delete next.AE_Ao_metodo;
  return { measurements: next, aeAoDerived: false };
}

/** Replace the entire exam. Ownership is reconstructed only by actually deriving
 * from two valid components; a historical ratio on its own remains independent. */
export function createEchoMeasurementState(measurements: Measurements = {}): EchoMeasurementState {
  const ratio = calculateAeAo(measurements);
  return ratio === null
    ? { measurements: { ...measurements }, aeAoDerived: false }
    : deriveAeAo(measurements, ratio);
}

/** Ownership belongs to this exam state, never to a value comparison. Cloning
 * other indices or changing a method does not turn an independent ratio into a derivation. */
export function updateEchoMeasurementState(
  state: EchoMeasurementState, measurements: Measurements,
): EchoMeasurementState {
  if (measurements === state.measurements) return state;
  const sourcesChanged = SOURCE_KEYS.some((key) => measurements[key] !== state.measurements[key]);
  const ratioChanged = measurements.AE_Ao !== state.measurements.AE_Ao
    || measurements.LA_Ao !== state.measurements.LA_Ao;
  if (ratioChanged && !sourcesChanged) return { measurements, aeAoDerived: false };

  const ratio = calculateAeAo(measurements);
  if (ratio !== null && (sourcesChanged || state.aeAoDerived)) return deriveAeAo(measurements, ratio);
  if (ratio === null && state.aeAoDerived) return clearDerivedAeAo(measurements);
  return { measurements, aeAoDerived: false };
}

/** An explicitly imported ratio is independent even if equal to the old auto
 * value. A new diameter acquisition needs both components in the same import. */
export function importEchoMeasurementState(
  state: EchoMeasurementState, imported: Measurements,
): EchoMeasurementState {
  const next = mergeImportedEchoMeasurements(state.measurements, imported);
  if (Object.hasOwn(imported, "AE_Ao") || Object.hasOwn(imported, "LA_Ao")) {
    next.AE_Ao = imported.AE_Ao ?? imported.LA_Ao;
    delete next.LA_Ao;
    return { measurements: next, aeAoDerived: false };
  }
  const hasDiameter = Object.hasOwn(imported, "Aorta") || Object.hasOwn(imported, "Atrio_esquerdo");
  if (hasDiameter) {
    const ratio = calculateAeAo(imported);
    if (ratio !== null) return deriveAeAo(next, ratio);
    return state.aeAoDerived ? clearDerivedAeAo(next) : { measurements: next, aeAoDerived: false };
  }
  return updateEchoMeasurementState(state, next);
}
