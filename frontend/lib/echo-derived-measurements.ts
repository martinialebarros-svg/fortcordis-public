import { echoLengthInMm, isEchoLengthKey } from "./echo-unit-provenance";
import { calculateCanine2DNormalizedLVIDd, type Echo2DView } from "./echo-2d-reference";
import { ECHO_REFERENCE_METHOD_VALUES } from "./echo-reference-policy";
import { isFelineEchoSpecies, normalizeEchoSpecies } from "./echo-species";
import { deriveOutflowGradients, ECHO_OUTFLOW_KEYS, isOutflowMetadataKey } from "./echo-outflow";
import { FELINE_DIASTOLIC_KEYS } from "./echo-feline-diastolic-reference";

const DIASTOLIC_KEYS = new Set<string>(FELINE_DIASTOLIC_KEYS);

export type RightAtrialRemodeling =
  | ""
  | "ausente"
  | "leve"
  | "moderado"
  | "importante";

const REGURGITATION_GRADIENTS: Record<string, string> = {
  IM_Vmax: "IM_Grad",
  IT_Vmax: "IT_Grad",
  IA_Vmax: "IA_Grad",
  IP_Vmax: "IP_Grad",
};

export const LV_M_MODE_KEYS = [
  "DIVEd",
  "DIVEd_normalizado",
  "SIVd",
  "PLVEd",
  "DIVES",
  "SIVs",
  "PLVES",
  "VDF",
  "VSF",
  "FE_Teicholz",
  "DeltaD_FS",
] as const;

export const LV_2D_KEYS = [
  "DIVEd_2D",
  "DIVEd_normalizado_2D",
  "SIVd_2D",
  "PLVEd_2D",
  "DIVES_2D",
  "SIVs_2D",
  "PLVES_2D",
  "VDF_2D",
  "VSF_2D",
  "FE_Teicholz_2D",
  "DeltaD_FS_2D",
] as const;

function parsePositiveNumber(value: unknown): number | null {
  const parsed = Number.parseFloat(String(value ?? "").replace(",", "."));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function formatDerivedValue(value: number): string {
  return Number(value.toFixed(2)).toString();
}

function formatDerivedPercentage(value: number): string {
  return String(Math.round(value));
}

export function calculateBernoulliGradient(velocity: unknown): number | null {
  const parsed = parsePositiveNumber(velocity);
  return parsed === null ? null : 4 * parsed ** 2;
}

export function calculateLeftAtrialFractionalShortening(
  measurements: Record<string, string>
): number | null {
  const laMax = echoLengthInMm(measurements, "AE_diametro_max");
  const laMin = echoLengthInMm(measurements, "AE_diametro_min");
  return laMax !== null && laMin !== null && laMin <= laMax
    ? (laMax - laMin) / laMax * 100 : null;
}

export function estimateRightAtrialPressure(
  remodeling: unknown
): number | null {
  const normalized = String(remodeling ?? "").trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "moderado") return 10;
  if (normalized === "importante") return 15;
  if (normalized === "ausente" || normalized === "leve") return 5;
  return null;
}

export function hasAnyMeasurement(
  measurements: Record<string, string>,
  keys: readonly string[]
): boolean {
  return keys.some((key) => Boolean(String(measurements[key] ?? "").trim()));
}

function normalizeStoredMeasurement(
  key: string,
  value: unknown
): string | null {
  const text = String(value ?? "").trim();
  // Retain an explicit clearing/unresolved canonical entry in the read model.
  // Dropping it would let a historical alias become current on presentation.
  if (DIASTOLIC_KEYS.has(key)) return text.replace(",", ".");
  if (!text) return null;

  if (isOutflowMetadataKey(key)) {
    if (key.endsWith("_origem") && !key.endsWith("_rotulo_origem")) {
      return ["importado", "informado", "calculado"].includes(text) ? text : null;
    }
    return text;
  }
  // A recorded but unresolved value must not become an absent gradient on
  // reopen, which would silently replace it with a Bernoulli calculation.
  if (ECHO_OUTFLOW_KEYS.has(key)) {
    return Number.isFinite(Number(text.replace(",", "."))) ? text.replace(",", ".") : text;
  }

  if (key === "VE_tecnica_relatorio") {
    const normalized = text.toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
    return normalized === "modo_m" || normalized === "2d" ? normalized : null;
  }
  if (key === "VE_vista_2D") {
    return text === "eixo_curto" || text === "eixo_longo" ? text : null;
  }
  if (Object.hasOwn(ECHO_REFERENCE_METHOD_VALUES, key)) {
    const allowed = ECHO_REFERENCE_METHOD_VALUES[key as keyof typeof ECHO_REFERENCE_METHOD_VALUES];
    return (allowed as readonly string[]).includes(text) ? text : null;
  }
  if (key === "Remodelamento_AD") {
    const normalized = text.toLowerCase();
    return ["ausente", "leve", "moderado", "importante"].includes(normalized)
      ? normalized
      : null;
  }
  if (key.startsWith("unidade_confirmada_")) {
    const measurementKey = key.slice("unidade_confirmada_".length);
    const unit = text.toLowerCase();
    return isEchoLengthKey(measurementKey) && (unit === "cm" || unit === "mm")
      ? unit
      : null;
  }

  const normalized = text.replace(",", ".");
  return normalized !== "" && Number.isFinite(Number(normalized))
    ? normalized
    : null;
}

export function parseStoredEchoMeasurements(
  rawMeasurements: unknown,
  description = ""
): Record<string, string> {
  const parsed: Record<string, string> = {};

  if (
    rawMeasurements &&
    typeof rawMeasurements === "object" &&
    !Array.isArray(rawMeasurements)
  ) {
    Object.entries(rawMeasurements as Record<string, unknown>).forEach(
      ([key, value]) => {
        const normalized = normalizeStoredMeasurement(key, value);
        if (normalized !== null) parsed[key] = normalized;
      }
    );
  }

  if (Object.keys(parsed).length === 0 && description) {
    const section =
      description.match(
        /##\s*Medidas\s+Ecocardiogr(?:a|á)ficas\s*([\s\S]*?)(?=\n##\s*|$)/i
      )?.[1] || "";
    const linePattern = /^[ \t]*-[ \t]*([A-Za-z0-9_]+):[ \t]*(.*?)[ \t]*$/gm;
    let match: RegExpExecArray | null;
    while ((match = linePattern.exec(section)) !== null) {
      const normalized = normalizeStoredMeasurement(match[1], match[2]);
      if (normalized !== null) parsed[match[1]] = normalized;
    }
  }

  if (!parsed.VE_tecnica_relatorio) {
    const hasMMode = hasAnyMeasurement(parsed, LV_M_MODE_KEYS);
    const has2D = hasAnyMeasurement(parsed, LV_2D_KEYS);
    if (hasMMode && !has2D) parsed.VE_tecnica_relatorio = "modo_m";
    if (has2D && !hasMMode) parsed.VE_tecnica_relatorio = "2d";
  }

  return parsed;
}

export function deriveAutomaticEchoMeasurements(
  measurements: Record<string, string>,
  weightKg: unknown,
  species = "",
  age?: unknown,
): Record<string, string> {
  const derived: Record<string, string> = {};

  // As relações diastólicas são derivadas das medidas de origem informadas no
  // formulário. Quando alguma origem não estiver disponível, preservamos o
  // valor histórico importado pelo equipamento em vez de apagá-lo no save.
  const eWave = parsePositiveNumber(measurements.Onda_E);
  const aWave = parsePositiveNumber(measurements.Onda_A);
  const feline = isFelineEchoSpecies(species);
  // Reimporting or editing origins removes acquisition confirmations. Unknown
  // separation must therefore remain as restrictive as explicit fusion in cats.
  const canine = normalizeEchoSpecies(species) === "Canina";
  // Existing canine records without acquisition metadata retain their prior
  // calculation behavior. An explicit wave review guards each domain separately.
  const canineFlowReviewed = canine && (["separadas", "fundidas", "nao_confirmadas"].includes(measurements.Diastolica_ondas)
    || ["canino_nao_sedado_pw_apical", "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo"].includes(measurements.Diastolica_metodo));
  const canineTissueReviewed = canine && (["separadas", "fundidas", "nao_confirmadas"].includes(measurements.TDI_ondas)
    || ["canino_pw_anel_septal_choi", "canino_pw_basal_septal_wess", "canino_pw_basal_lateral_wess"].includes(measurements.TDI_metodo));
  const mitralMeasurable = !(feline || canineFlowReviewed) || measurements.Diastolica_ondas === "separadas";
  const tissueMeasurable = !(feline || canineTissueReviewed) || measurements.TDI_ondas === "separadas";
  if (mitralMeasurable && eWave !== null && aWave !== null) {
    derived.E_A = formatDerivedValue(eWave / aWave);
  }

  const trivMs = parsePositiveNumber(measurements.TRIV);
  if (mitralMeasurable && eWave !== null && trivMs !== null) {
    // O corte clínico de E/TRIV usa E em cm/s e TRIV em ms. O formulário
    // armazena a velocidade da onda E em m/s, portanto convertemos somente
    // o numerador antes de calcular o índice.
    derived.E_TRIV = formatDerivedValue((eWave * 100) / trivMs);
  }

  const ePrime = parsePositiveNumber(measurements.e_doppler);
  if (mitralMeasurable && tissueMeasurable && eWave !== null && ePrime !== null) {
    derived.E_E_linha = formatDerivedValue(eWave / ePrime);
  }
  const aPrime = parsePositiveNumber(measurements.a_doppler);
  if (tissueMeasurable && ePrime !== null && aPrime !== null) {
    derived.doppler_tecidual_relacao = formatDerivedValue(ePrime / aPrime);
  }

  for (const [velocityKey, gradientKey] of Object.entries(
    REGURGITATION_GRADIENTS
  )) {
    const gradient = calculateBernoulliGradient(measurements[velocityKey]);
    derived[gradientKey] =
      gradient === null ? "" : formatDerivedValue(gradient);
  }

  const rightAtrialPressure = estimateRightAtrialPressure(
    measurements.Remodelamento_AD
  );
  if (rightAtrialPressure !== null) {
    derived.PAD_estimada = formatDerivedValue(rightAtrialPressure);
    const tricuspidGradient = calculateBernoulliGradient(measurements.IT_Vmax);
    if (tricuspidGradient !== null) {
      derived.PSAP = formatDerivedValue(
        tricuspidGradient + rightAtrialPressure
      );
    } else {
      derived.PSAP = "";
    }
  } else {
    derived.PAD_estimada = "";
    derived.PSAP = "";
  }

  const weight = parsePositiveNumber(weightKg);
  const divedM = echoLengthInMm(measurements, "DIVEd");
  if (canine) {
    derived.DIVEd_normalizado = divedM !== null && weight !== null
      ? formatDerivedValue(divedM / 10 / weight ** 0.294) : "";
  }
  if (feline) {
    const laFraction = calculateLeftAtrialFractionalShortening(measurements);
    if (laFraction !== null) {
      derived.Fracao_encurtamento_AE = formatDerivedValue(laFraction);
    }
  }
  Object.assign(derived, deriveOutflowGradients(measurements));
  const view = measurements.VE_vista_2D === "eixo_curto" || measurements.VE_vista_2D === "eixo_longo"
    ? measurements.VE_vista_2D as Echo2DView : "";
  const normalized2D = calculateCanine2DNormalizedLVIDd(
    echoLengthInMm(measurements, "DIVEd_2D"), weight, view, species, age,
  );
  // Sem aplicabilidade comprovada, preservar o valor histórico no registro;
  // a prévia e o PDF omitem esse índice para evitar atribuir-lhe Visser.
  if (normalized2D !== null) derived.DIVEd_normalizado_2D = formatDerivedValue(normalized2D);

  const hasMMode = hasAnyMeasurement(measurements, LV_M_MODE_KEYS);
  const has2D = hasAnyMeasurement(measurements, LV_2D_KEYS);
  if (hasMMode && !has2D) derived.VE_tecnica_relatorio = "modo_m";
  if (has2D && !hasMMode) derived.VE_tecnica_relatorio = "2d";

  return derived;
}

/**
 * Completa apenas a visualizacao das referencias com a funcao ventricular que
 * pode ser obtida das medidas ja preenchidas. Nao altera o formulario nem o
 * payload do laudo: se a FE ou o FS informado pelo equipamento existir, ele
 * sempre tem precedencia sobre o valor calculado aqui.
 */
export function deriveLeftVentricularFunctionForReference(
  measurements: Record<string, string>
): Record<string, string> {
  const derived: Record<string, string> = {};

  for (const fields of Object.values({
    modo_m: {
      edv: "VDF",
      esv: "VSF",
      ef: "FE_Teicholz",
      lvidD: "DIVEd",
      lvidS: "DIVES",
      fs: "DeltaD_FS",
    },
    modo_2d: {
      edv: "VDF_2D",
      esv: "VSF_2D",
      ef: "FE_Teicholz_2D",
      lvidD: "DIVEd_2D",
      lvidS: "DIVES_2D",
      fs: "DeltaD_FS_2D",
    },
  })) {
    const edv = parsePositiveNumber(measurements[fields.edv]);
    const esv = parsePositiveNumber(measurements[fields.esv]);
    if (!String(measurements[fields.ef] ?? "").trim() && edv !== null && esv !== null && esv <= edv) {
      derived[fields.ef] = formatDerivedPercentage(((edv - esv) / edv) * 100);
    }

    const lvidD = echoLengthInMm(measurements, fields.lvidD);
    const lvidS = echoLengthInMm(measurements, fields.lvidS);
    if (
      !String(measurements[fields.fs] ?? "").trim() &&
      lvidD !== null &&
      lvidS !== null &&
      lvidS <= lvidD
    ) {
      derived[fields.fs] = formatDerivedPercentage(((lvidD - lvidS) / lvidD) * 100);
    }
  }

  return derived;
}
