import { ECHO_REFERENCE_METHOD_KEYS } from "./echo-reference-policy";

export const ECHO_LENGTH_KEYS = [
  "DIVEd", "SIVd", "PLVEd", "DIVES", "SIVs", "PLVES",
  "DIVEd_2D", "SIVd_2D", "PLVEd_2D", "DIVES_2D", "SIVs_2D", "PLVES_2D",
  "Aorta", "Atrio_esquerdo", "AE_diametro_max", "AE_diametro_min", "Ao_nivel_AP", "AP",
] as const;

const lengthKeys = new Set<string>(ECHO_LENGTH_KEYS);
const UNIT_PREFIX = "unidade_confirmada_";
const DIASTOLIC_CONFIRMATIONS = ["Diastolica_metodo", "Diastolica_ondas"];
const TDI_CONFIRMATIONS = ["TDI_metodo", "TDI_ondas"];
const METHOD_SOURCES: Record<string, string[]> = {
  TAPSE: ["TAPSE_metodo"],
  AE_Ao: ["AE_Ao_metodo"], LA_Ao: ["AE_Ao_metodo"],
  Aorta: ["AE_Ao_metodo"], Atrio_esquerdo: ["AE_Ao_metodo"],
  Ao: ["AE_Ao_metodo"], LA: ["AE_Ao_metodo"],
  Onda_E: DIASTOLIC_CONFIRMATIONS, Onda_A: DIASTOLIC_CONFIRMATIONS,
  TD: DIASTOLIC_CONFIRMATIONS, TRIV: DIASTOLIC_CONFIRMATIONS,
  MV_E: DIASTOLIC_CONFIRMATIONS, MV_A: DIASTOLIC_CONFIRMATIONS,
  MV_DT: DIASTOLIC_CONFIRMATIONS, IVRT: DIASTOLIC_CONFIRMATIONS,
  e_doppler: TDI_CONFIRMATIONS, a_doppler: TDI_CONFIRMATIONS,
  TDI_e: TDI_CONFIRMATIONS, TDI_a: TDI_CONFIRMATIONS,
};

const WAVE_METHODS: Record<string, string> = { Diastolica_ondas: "Diastolica_metodo", TDI_ondas: "TDI_metodo" };
const WAVE_STATES = new Set(["separadas", "fundidas", "nao_confirmadas"]);
const METHOD_WAVES: Record<string, string> = { Diastolica_metodo: "Diastolica_ondas", TDI_metodo: "TDI_ondas" };

/** An invalidated review is distinct from a genuinely untouched legacy exam.
 * Keep that distinction across serialization and repeat imports. */
function invalidateAcquisition(next: Record<string, string>, previous: Record<string, string>, key: string) {
  const method = WAVE_METHODS[key];
  if (method && (WAVE_STATES.has(previous[key]) || Boolean(previous[method]))) {
    next[key] = "nao_confirmadas";
  } else {
    delete next[key];
    // Retracting the method can remove the last sign that this acquisition was
    // reviewed, even when the operator has not selected a wave state yet.
    const wave = METHOD_WAVES[key];
    if (wave && previous[key] && !WAVE_STATES.has(next[wave])) next[wave] = "nao_confirmadas";
  }
}

export function confirmedUnitKey(key: string): string {
  return `${UNIT_PREFIX}${key}`;
}

export function isEchoLengthKey(key: string): boolean {
  return lengthKeys.has(key);
}

export function confirmedEchoUnit(measurements: Record<string, string>, key: string): "cm" | "mm" | null {
  if (!isEchoLengthKey(key)) return null;
  const unit = measurements[confirmedUnitKey(key)]?.trim().toLowerCase();
  return unit === "cm" || unit === "mm" ? unit : null;
}

export function echoLengthInputLabel(label: string, measurements: Record<string, string>, key: string): string {
  if (confirmedEchoUnit(measurements, key) === "cm") return label.replace("(mm", "(cm de origem");
  if (ambiguousEchoLengthKeys(measurements).has(key)) return label.replace("(mm", "(unidade a confirmar");
  return label;
}

function positiveNumber(value: unknown): number | null {
  const parsed = Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function echoUnitReviewCandidates(measurements: Record<string, string>): string[] {
  const values = ECHO_LENGTH_KEYS.map((key) => [key, positiveNumber(measurements[key])] as const)
    .filter((entry): entry is readonly [typeof ECHO_LENGTH_KEYS[number], number] => entry[1] !== null);
  const candidates = values.filter(([, value]) => value >= 0.3 && value <= 3.5);
  const millimeters = values.filter(([, value]) => value >= 5).length;
  if (values.length < 3 || candidates.length < 3 || candidates.length < millimeters * 2) return [];
  return candidates.map(([key]) => key);
}

export function ambiguousEchoLengthKeys(measurements: Record<string, string>): Set<string> {
  return new Set(echoUnitReviewCandidates(measurements).filter((key) => !confirmedEchoUnit(measurements, key)));
}

export function echoLengthInMm(measurements: Record<string, string>, key: string): number | null {
  const value = positiveNumber(measurements[key]);
  if (value === null || ambiguousEchoLengthKeys(measurements).has(key)) return null;
  return confirmedEchoUnit(measurements, key) === "cm" ? value * 10 : value;
}

export function updateEchoMeasurement(
  measurements: Record<string, string>, key: string, value: string
): Record<string, string> {
  const next = { ...measurements, [key]: value };
  // An explicit method selection/retraction is a review interaction, including
  // "outro". Preserve an existing wave review; otherwise record unresolved.
  const wave = METHOD_WAVES[key];
  if (wave && !WAVE_STATES.has(next[wave])) next[wave] = "nao_confirmadas";
  if (ECHO_REFERENCE_METHOD_KEYS.includes(key) && value === "") invalidateAcquisition(next, measurements, key);
  if (value !== measurements[key]) {
    for (const confirmation of METHOD_SOURCES[key] ?? []) invalidateAcquisition(next, measurements, confirmation);
  }
  if (key.startsWith(UNIT_PREFIX) && value === "") delete next[key];
  if (isEchoLengthKey(key) && value !== measurements[key]) {
    delete next[confirmedUnitKey(key)];
  }
  return next;
}

export function mergeImportedEchoMeasurements(
  measurements: Record<string, string>, imported: Record<string, string>
): Record<string, string> {
  const next = { ...measurements, ...imported };
  for (const key of Object.keys(imported)) {
    if (isEchoLengthKey(key)) delete next[confirmedUnitKey(key)];
    for (const confirmation of METHOD_SOURCES[key] ?? []) invalidateAcquisition(next, measurements, confirmation);
    if (ECHO_REFERENCE_METHOD_KEYS.includes(key)) invalidateAcquisition(next, measurements, key);
  }
  return next;
}
