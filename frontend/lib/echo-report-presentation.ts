import type { ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { calculateCanine2DNormalizedLVIDd, getCanine2DReference, type Echo2DView } from "./echo-2d-reference";
import { ambiguousEchoLengthKeys, confirmedEchoUnit, confirmedUnitKey, ECHO_LENGTH_KEYS } from "./echo-unit-provenance";
import { calculateLeftAtrialFractionalShortening } from "./echo-derived-measurements";
import { ECHO_REFERENCE_METHOD_KEYS, resolveEchoReferenceForMeasurements } from "./echo-reference-policy";
import { canonicalEchoDiastolicKey, echoDiastolicReferences, type EchoDiastolicReference } from "./echo-diastolic-reference";
import { FELINE_DIASTOLIC_KEYS } from "./echo-feline-diastolic-reference";
import { isCanineEchoSpecies, isFelineEchoSpecies, normalizeEchoSpecies } from "./echo-species";
import { deriveOutflowGradients, ECHO_OUTFLOW_KEYS, formatOutflowValue, isOutflowMetadataKey, outflowMeasurementLabel } from "./echo-outflow";
import { lowWeightAgeContext, lowWeightEstimateText, makeLowWeightReference } from "./echo-low-weight-reference";

type Parameter = { key: string; label: string; unit?: string; reference?: string };
export type EchoReportReferenceMetadata = Pick<EchoDiastolicReference, "source" | "doi" | "statistic" | "note" | "kind">;
export type EchoReportRow = {
  key: string;
  label: string;
  value: string;
  reference: string;
  referenceMetadata?: EchoReportReferenceMetadata;
};
export type EchoReportGroup = { title: string; rows: EchoReportRow[] };
export type EchoCalculationAlert = { key: string; recorded: number; calculated: number };

const parameter = (key: string, label: string, unit = "", reference?: string): Parameter => ({ key, label, unit, reference });

const mMode: Parameter[] = [
  parameter("DIVEd", "DIVEd · diâmetro interno do VE em diástole", "mm", "lvid_d"),
  parameter("DIVEd_normalizado", "DIVEd normalizado · DIVEd [cm] / peso^0,294"),
  parameter("SIVd", "SIVd · septo interventricular em diástole", "mm", "ivs_d"),
  parameter("PLVEd", "PLVEd · parede livre do VE em diástole", "mm", "lvpw_d"),
  parameter("DIVES", "DIVEs · diâmetro interno do VE em sístole", "mm", "lvid_s"),
  parameter("SIVs", "SIVs · septo interventricular em sístole", "mm", "ivs_s"),
  parameter("PLVES", "PLVEs · parede livre do VE em sístole", "mm", "lvpw_s"),
  parameter("VDF", "VDF · Teicholz", "ml", "edv"),
  parameter("VSF", "VSF · Teicholz", "ml", "esv"),
  parameter("FE_Teicholz", "FE · Teicholz", "%"),
  parameter("DeltaD_FS", "Encurtamento fracional · %FS", "%", "fs"),
];
const mode2D: Parameter[] = mMode.map((item) => ({
  ...item,
  key: `${item.key}_2D`,
  label: `${item.label} · 2D`,
  reference: undefined,
}));
mode2D.find((item) => item.key === "DIVEd_normalizado_2D")!.label = "DIVEd normalizado · 2D, Visser · DIVEd [cm] / peso^0,316";
const annularExcursion: Parameter[] = [
  parameter("TAPSE", "TAPSE · excursão anular tricúspide", "mm", "tapse"),
  parameter("MAPSE", "MAPSE · excursão anular mitral", "mm", "mapse"),
];

const otherGroups: { title: string; parameters: Parameter[] }[] = [
  { title: "Excursão do plano anular", parameters: annularExcursion },
  { title: "Átrio esquerdo / aorta", parameters: [
    parameter("Aorta", "Aorta", "mm", "ao"),
    parameter("Atrio_esquerdo", "Átrio esquerdo", "mm", "la"),
    parameter("AE_Ao", "AE/Ao · átrio esquerdo / aorta", "", "la_ao"),
    parameter("AE_diametro_max", "AE · diâmetro máximo", "mm"),
    parameter("AE_diametro_min", "AE · diâmetro mínimo", "mm"),
    parameter("Fracao_encurtamento_AE", "Fração de encurtamento do AE", "%"),
    parameter("Fluxo_auricular", "Velocidade máxima do apêndice atrial esquerdo", "m/s"),
  ] },
  { title: "Artéria pulmonar / aorta", parameters: [
    parameter("AP", "Artéria pulmonar", "mm", "ap"),
    parameter("Ao_nivel_AP", "Aorta no nível da AP", "mm", "ao"),
    parameter("AP_Ao", "AP/Ao · artéria pulmonar / aorta", "", "ap_ao"),
  ] },
  { title: "Doppler · saídas", parameters: [
    parameter("Vmax_aorta", "Velocidade máxima aórtica", "m/s", "vmax_ao"),
    parameter("Grad_aorta", "Gradiente aórtico", "mmHg"),
    parameter("Vmax_VSVE", "Velocidade máxima da via de saída do VE", "m/s"),
    parameter("Grad_VSVE", "Gradiente da via de saída do VE", "mmHg"),
    parameter("Vmax_VSVD", "Velocidade máxima da via de saída do VD", "m/s"),
    parameter("Grad_VSVD", "Gradiente da via de saída do VD", "mmHg"),
    parameter("Vmax_pulmonar", "Velocidade máxima pulmonar", "m/s", "vmax_pulm"),
    parameter("Grad_pulmonar", "Gradiente pulmonar", "mmHg"),
  ] },
  { title: "Função diastólica", parameters: [
    parameter("Onda_E", "Onda E", "m/s", "mv_e"),
    parameter("Onda_A", "Onda A", "m/s", "mv_a"),
    parameter("E_A", "Relação E/A", "", "mv_ea"),
    parameter("TD", "Tempo de desaceleração", "ms", "mv_dt"),
    parameter("TRIV", "Tempo de relaxamento isovolumétrico", "ms", "ivrt"),
    parameter("E_TRIV", "Relação E/TRIV"),
    parameter("MR_dp_dt", "MR dp/dt", "mmHg/s"),
    parameter("e_doppler", "e' · Doppler tecidual", "m/s", "tdi_e"),
    parameter("a_doppler", "a' · Doppler tecidual", "m/s", "tdi_a"),
    parameter("doppler_tecidual_relacao", "Relação e'/a'"),
    parameter("E_E_linha", "Relação E/e'", "", "e_e_linha"),
  ] },
  { title: "Regurgitações e estimativa de pressão", parameters: [
    parameter("IM_Vmax", "Velocidade máxima da insuficiência mitral", "m/s"),
    parameter("IM_Grad", "Gradiente da insuficiência mitral", "mmHg"),
    parameter("IT_Vmax", "Velocidade máxima da insuficiência tricúspide", "m/s"),
    parameter("IT_Grad", "Gradiente da insuficiência tricúspide", "mmHg"),
    parameter("PAD_estimada", "Pressão atrial direita estimada", "mmHg"),
    parameter("PSAP", "Pressão sistólica da artéria pulmonar estimada", "mmHg"),
    parameter("IA_Vmax", "Velocidade máxima da insuficiência aórtica", "m/s"),
    parameter("IA_Grad", "Gradiente da insuficiência aórtica", "mmHg"),
    parameter("IP_Vmax", "Velocidade máxima da insuficiência pulmonar", "m/s"),
    parameter("IP_Grad", "Gradiente da insuficiência pulmonar", "mmHg"),
  ] },
];

// TAPSE e MAPSE não permitem inferir cm a partir de outros diâmetros do exame.
const lengthKeys = new Set<string>(ECHO_LENGTH_KEYS);
const diastolicKeys = new Set<string>(FELINE_DIASTOLIC_KEYS);

function number(value: unknown): number | null {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const parsed = Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function referenceRange(reference: ReferenciaEco | null, item: Parameter): string {
  if (!reference || !item.reference) return "—";
  const estimate = lowWeightEstimateText(reference.range_metadata?.[item.reference]);
  if (estimate) return estimate;
  if (item.reference === "fs" && !reference.fs_source) return "—";
  const fields = reference as unknown as Record<string, unknown>;
  let min = number(fields[`${item.reference}_min`]);
  let max = number(fields[`${item.reference}_max`]);
  if (min === null || max === null || (min === 0 && max === 0)) return "—";
  if (item.key === "e_doppler" || item.key === "a_doppler") {
    min /= 100;
    max /= 100;
  }
  return `${min.toFixed(2)}–${max.toFixed(2)}${item.unit ? ` ${item.unit}` : ""}`;
}

function normalizeDiastolicAliases(raw: Record<string, string>): Record<string, string> {
  const measurements = { ...raw };
  for (const [key, value] of Object.entries(raw)) {
    const canonical = canonicalEchoDiastolicKey(key);
    if (!Object.hasOwn(measurements, canonical)) measurements[canonical] = value;
  }
  return measurements;
}

export function prepareEchoReportMeasurements(raw: Record<string, string>, weightKg: unknown, species = "", age?: unknown) {
  const measurements = normalizeDiastolicAliases(raw);
  const canine = isCanineEchoSpecies(species);
  const ambiguousKeys = ambiguousEchoLengthKeys(raw);
  for (const key of lengthKeys) {
    if (confirmedEchoUnit(raw, key) === "cm") {
      const value = number(raw[key]);
      if (value !== null && value > 0) measurements[key] = String(value * 10);
    }
  }
  if (!canine || ambiguousKeys.has("DIVEd")) delete measurements.DIVEd_normalizado;
  if (ambiguousKeys.has("DIVEd_2D")) delete measurements.DIVEd_normalizado_2D;
  if (isFelineEchoSpecies(species)) {
    const laFraction = calculateLeftAtrialFractionalShortening(raw);
    if (laFraction !== null) measurements.Fracao_encurtamento_AE = String(Number(laFraction.toFixed(2)));
  }
  Object.assign(measurements, deriveOutflowGradients(measurements));
  const view = raw.VE_vista_2D === "eixo_curto" || raw.VE_vista_2D === "eixo_longo"
    ? raw.VE_vista_2D as Echo2DView : "";
  const dived2D = number(measurements.DIVEd_2D);
  const visser2D = ambiguousKeys.has("DIVEd_2D") ? null : calculateCanine2DNormalizedLVIDd(
    dived2D, number(weightKg), view, species, age,
  );
  if (visser2D === null) delete measurements.DIVEd_normalizado_2D;

  const alerts: EchoCalculationAlert[] = [];
  const weight = number(weightKg);
  if (weight !== null && weight > 0) {
    const selectedNormalizedKey = raw.VE_tecnica_relatorio === "2d"
      ? "DIVEd_normalizado_2D"
      : "DIVEd_normalizado";
    for (const [diameterKey, normalizedKey] of [["DIVEd", "DIVEd_normalizado"], ["DIVEd_2D", "DIVEd_normalizado_2D"]]) {
      if (normalizedKey === "DIVEd_normalizado" && !canine) continue;
      if (ambiguousKeys.has(diameterKey)) {
        continue;
      }
      const diameter = number(measurements[diameterKey]);
      if (diameter === null || diameter <= 0) continue;
      const calculated = normalizedKey === "DIVEd_normalizado_2D"
        ? visser2D : Number(((diameter / 10) / weight ** 0.294).toFixed(2));
      if (calculated === null) continue;
      const recorded = number(raw[normalizedKey]);
      if (normalizedKey === selectedNormalizedKey && recorded !== null && Math.abs(recorded - calculated) > 0.05) {
        alerts.push({ key: normalizedKey, recorded, calculated });
      }
      measurements[normalizedKey] = String(calculated);
    }
  }
  return { measurements, alerts, ambiguousKeys };
}

export function canineAeAoClinicalReference(measurements: Record<string, string>, species: string, ambiguousKeys = ambiguousEchoLengthKeys(measurements)): string | null {
  const ratio = number(measurements.AE_Ao);
  if (!isCanineEchoSpecies(species) || !["2d_eixo_curto_diastole_inicial", "2d_eixo_curto_diastole_inicial_sueco"].includes(measurements.AE_Ao_metodo)
      || ratio === null || ratio <= 0
      || ["AE_Ao", "Aorta", "Atrio_esquerdo"].some((key) => ambiguousKeys.has(key))) return null;
  return "<1,60 (2D, eixo curto)";
}

export function buildEchoReportGroups(measurements: Record<string, string>, reference: ReferenciaEco | null, ambiguousKeys: Set<string> = new Set(), weightKg?: number, species = reference?.especie ?? "", age?: string | null): EchoReportGroup[] {
  measurements = normalizeDiastolicAliases(measurements);
  const currentAge = age === undefined ? reference?.patient_age : age;
  const referenceCarrier = reference || makeLowWeightReference(species, weightKg, 0, {}, age);
  const safeReference = resolveEchoReferenceForMeasurements(referenceCarrier, measurements, weightKg, age);
  const diastolicReferences = echoDiastolicReferences(measurements, species);
  const pendingIndices = new Set<string>();
  if (["Canina", "Felina"].includes(normalizeEchoSpecies(species))) {
    if (measurements.Diastolica_ondas === "nao_confirmadas") {
      for (const key of ["E_A", "E_TRIV", "E_E_linha"]) pendingIndices.add(key);
    }
    if (measurements.TDI_ondas === "nao_confirmadas") {
      for (const key of ["doppler_tecidual_relacao", "E_E_linha"]) pendingIndices.add(key);
    }
  }
  const selected2D = measurements.VE_tecnica_relatorio === "2d";
  const view = measurements.VE_vista_2D === "eixo_curto" || measurements.VE_vista_2D === "eixo_longo"
    ? measurements.VE_vista_2D as Echo2DView : "";
  const d = number(measurements.DIVEd_2D);
  const s = number(measurements.DIVES_2D);
  const fs = number(measurements.DeltaD_FS_2D);
  const fsMatchesPair = d !== null && s !== null && fs !== null && d > 0 && s > 0 && s <= d
    && !ambiguousKeys.has("DIVEd_2D") && !ambiguousKeys.has("DIVES_2D")
    && Math.abs(fs - (d - s) / d * 100) <= 1;
  const groups = [
    { title: selected2D ? "Ventrículo esquerdo · modo 2D" : "Ventrículo esquerdo · modo M", parameters: selected2D ? mode2D : mMode },
    ...otherGroups,
  ];
  const known = new Set(["VE_tecnica_relatorio", "VE_vista_2D", "Remodelamento_AD", ...ECHO_REFERENCE_METHOD_KEYS, ...mMode.map((item) => item.key), ...mode2D.map((item) => item.key)]);
  for (const key of ECHO_LENGTH_KEYS) known.add(confirmedUnitKey(key));
  for (const group of otherGroups) for (const item of group.parameters) known.add(item.key);
  const unknown: Parameter[] = Object.keys(measurements).filter((key) => !known.has(canonicalEchoDiastolicKey(key)) && !isOutflowMetadataKey(key)).map((key) => parameter(key, key));
  if (unknown.length) groups.push({ title: "Outras medidas registradas", parameters: unknown });
  return groups.map((group) => ({
    title: group.title,
    rows: group.parameters.filter((item) => {
      if (item.key === "DIVEd_normalizado_2D" && lowWeightAgeContext(currentAge) === "juvenile") return false;
      const value = number(measurements[item.key]);
      return diastolicReferences[canonicalEchoDiastolicKey(item.key)]?.kind === "uninterpretable"
        || (ECHO_OUTFLOW_KEYS.has(item.key) && String(measurements[item.key] ?? "").trim() !== "")
        || (value !== null && (diastolicKeys.has(item.key) ? value > 0 : value !== 0));
    }).map((item) => {
      const outflowValue = ECHO_OUTFLOW_KEYS.has(item.key);
      const numericValue = number(measurements[item.key]);
      const unconfirmed = outflowValue && (numericValue === null || numericValue < 0);
      const pendingIndex = pendingIndices.has(canonicalEchoDiastolicKey(item.key));
      const referenceForKey = diastolicReferences[canonicalEchoDiastolicKey(item.key)];
      const diastolicReference = ambiguousKeys.has(item.key) && referenceForKey?.kind !== "uninterpretable"
        ? undefined : diastolicReferences[canonicalEchoDiastolicKey(item.key)];
      const model = item.reference ? safeReference?.range_metadata?.[item.reference] : undefined;
      return {
        key: item.key,
        label: outflowMeasurementLabel(item.key, item.label, measurements),
        value: unconfirmed ? `${measurements[item.key]} (valor a confirmar)`
          : diastolicReference?.kind === "uninterpretable" ? "Não mensurável"
          : pendingIndex ? `${numericValue?.toFixed(2)} (valor a confirmar)` : ambiguousKeys.has(item.key)
          ? `${number(measurements[item.key])?.toFixed(2)} (unidade a confirmar)`
          : `${outflowValue ? formatOutflowValue(measurements[item.key]) : numericValue?.toFixed(2)}${item.unit ? ` ${item.unit}` : ""}`,
        reference: unconfirmed || pendingIndex || (ambiguousKeys.has(item.key) && diastolicReference?.kind !== "uninterpretable") ? "—" : (() => {
          if (diastolicReference) return diastolicReference.text;
          const aeAoLimit = item.key === "AE_Ao" ? canineAeAoClinicalReference(measurements, species, ambiguousKeys) : null;
          if (aeAoLimit) return aeAoLimit;
          const twoD = selected2D && referenceCarrier && isCanineEchoSpecies(referenceCarrier.especie)
            && (item.key !== "DeltaD_FS_2D" || fsMatchesPair)
            ? getCanine2DReference(item.key, weightKg, view, currentAge) : null;
          return twoD ? `${twoD.min.toFixed(2)}–${twoD.max.toFixed(2)}${item.unit ? ` ${item.unit}` : ""}`
            : referenceRange(safeReference, item);
        })(),
        ...(diastolicReference ? { referenceMetadata: {
          source: diastolicReference.source,
          doi: diastolicReference.doi,
          statistic: diastolicReference.statistic,
          note: pendingIndex && diastolicReference.kind !== "uninterpretable"
            ? "Índice histórico: aguarda reconfirmação da separação das ondas antes de interpretar."
            : diastolicReference.note,
          kind: diastolicReference.kind,
        } } : model?.model_weight_kg != null ? { referenceMetadata: {
          source: model.source || "", doi: model.doi || "", statistic: model.statistic || "",
          note: [model.reason, model.formula].filter(Boolean).join(" "),
          kind: model.status === "published" ? "reference_interval" as const
            : model.status === "estimated" ? "descriptive" as const : "unconfirmed" as const,
        } } : {}),
      };
    }),
  })).filter((group) => group.rows.length > 0);
}

export function splitReportObservations(text: string): { clinical: string; operational: string } {
  const clinical: string[] = [];
  const operational: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    (/^\s*\[(?:Assistente agenda|Reserva manual)\]/i.test(line) ? operational : clinical).push(line);
  }
  return { clinical: clinical.join("\n").trim(), operational: operational.join("\n").trim() };
}
