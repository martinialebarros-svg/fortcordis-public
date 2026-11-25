import type { FelinePediatricReference, FelinePediatricRange, ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { lowWeightAgeContext } from "./echo-low-weight-reference";
import { isFelineEchoSpecies } from "./echo-species";
import { felineAgeRangeMayIncludeJuvenile } from "./echo-feline-pediatric-age";

export const FELINE_PEDIATRIC_PROTOCOL = "gunther_harrington_2021_sem_sedacao";
export const FELINE_PEDIATRIC_SOURCE = "Gunther-Harrington et al. (2021); Tabela suplementar 1";
export const FELINE_PEDIATRIC_DOI = "10.1177/1098612X20946461";
export const FELINE_PEDIATRIC_NOTE = "Intervalos publicados da coorte pediátrica, não ajustados ao peso; consulta descritiva, sem classificação automática. Interpretar com a técnica, a morfologia e os demais achados.";
const POPULATION = "88 gatos domésticos de pelo curto saudáveis, de 6 a 16 semanas, sem sedação; peso mediano de 1,3 kg (intervalo interquartil 0,98–1,5 kg). O estudo não informa extremos de peso para definir um domínio individual.";

type Method = "modo_m" | "2d" | "ae_ao" | "doppler";
// Supplementary Table 1: reference-interval columns, NOT observed min/max or
// confidence limits. Source lengths in cm converted to mm; no allometric fit.
const COHORT_RANGES: Record<string, readonly [number, number, string, Method]> = {
  DIVEd: [8.6, 15.3, "mm", "modo_m"], DIVES: [2.8, 8.4, "mm", "modo_m"],
  SIVd: [2.1, 4.5, "mm", "modo_m"], SIVs: [3.7, 7.2, "mm", "modo_m"],
  PLVEd: [2, 4.5, "mm", "modo_m"], PLVES: [3.8, 7.4, "mm", "modo_m"],
  DeltaD_FS: [36.6, 68.6, "%", "modo_m"],
  DIVEd_2D: [8.3, 14, "mm", "2d"], DIVES_2D: [3.4, 8.8, "mm", "2d"],
  SIVd_2D: [2.3, 4.4, "mm", "2d"], SIVs_2D: [3.3, 7.1, "mm", "2d"],
  PLVEd_2D: [2, 4.5, "mm", "2d"], PLVES_2D: [3.4, 6.5, "mm", "2d"],
  Aorta: [4.7, 7.8, "mm", "ae_ao"], Atrio_esquerdo: [6.3, 10.6, "mm", "ae_ao"],
  AE_Ao: [1.12, 1.63, "", "ae_ao"],
  Vmax_aorta: [0.72, 1.39, "m/s", "doppler"], Vmax_pulmonar: [0.53, 1.35, "m/s", "doppler"],
};

const GENERIC_PREFIXES = ["lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s", "fs", "ef",
  "tapse", "mapse", "ao", "la", "la_ao", "ap", "ap_ao", "vmax_ao", "vmax_pulm", "mv_e", "mv_a", "mv_ea",
  "mv_dt", "ivrt", "tdi_e", "tdi_a", "e_e_linha", "edv", "esv", "sv"];

const ALIASES: Record<string, string> = {
  LVIDd: "DIVEd", LVIDs: "DIVES", IVSd: "SIVd", IVSs: "SIVs", LVPWd: "PLVEd", LVPWs: "PLVES",
  Ao: "Aorta", LA: "Atrio_esquerdo", LA_Ao: "AE_Ao", Vmax_Ao: "Vmax_aorta", Vmax_Pulm: "Vmax_pulmonar",
};
export function canonicalPediatricMeasurement(key: string): string { return ALIASES[key] ?? key; }

/** Only explicit, fully parsed quantities establish eligibility. Approximate
 * year-only ranges and words such as "filhote" never become a precise age. */
export function felinePediatricAgeWeeks(age: unknown): number | null {
  const text = String(age ?? "").trim().normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().replace(/\s*\(estimada\)$/, "");
  const tokens = [...text.matchAll(/(\d+(?:[.,]\d+)?)\s*(anos?|years?|a|y|mes(?:es)?|months?|m|dias?|days?|d|semanas?|weeks?|w)\b/g)];
  if (!tokens.length) return null;
  const units = tokens.map((token) => /^(?:a|y)/.test(token[2]) ? "years" : /^m/.test(token[2]) ? "months" : /^(?:s|w)/.test(token[2]) ? "weeks" : "days");
  if (new Set(units).size !== units.length) return null;
  let remaining = text;
  for (const token of tokens.toReversed()) remaining = remaining.slice(0, token.index) + " " + remaining.slice(token.index! + token[0].length);
  if (remaining.replace(/[\s,;+]|\be\b|\band\b/g, "")) return null;
  const days = tokens.reduce((sum, token) => {
    const unit = token[2];
    return sum + Number(token[1].replace(",", ".")) * (/^(?:a|y)/.test(unit) ? 365.25 : /^m/.test(unit) ? 30.4375 : /^(?:s|w)/.test(unit) ? 7 : 1);
  }, 0);
  return Number.isFinite(days) && days >= 0 ? days / 7 : null;
}

export function isFelinePediatricContext(species: string | null | undefined, age: unknown): boolean {
  return isFelineEchoSpecies(species)
    && (lowWeightAgeContext(age) === "juvenile" || felineAgeRangeMayIncludeJuvenile(age));
}

function positive(value: unknown): boolean {
  const number = Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(number) && number > 0;
}
const format = (value: number) => value.toFixed(2).replace(".", ",");

export function felinePediatricReference(species: string | null | undefined, weight: unknown, age: unknown,
  measurements: Record<string, string> = {}): FelinePediatricReference | undefined {
  if (!isFelinePediatricContext(species, age)) return undefined;
  const weeks = felinePediatricAgeWeeks(age);
  const ageReason = weeks === null ? "Informe idade precisa em dias, semanas ou meses; não é possível confirmar a população de 6–16 semanas."
    : weeks < 6 || weeks > 16 ? "Idade fora da coorte estudada de 6–16 semanas; não extrapolar estes intervalos." : "";
  const ranges: Record<string, FelinePediatricRange> = {};
  for (const [key, [lower, upper, unit, method]] of Object.entries(COHORT_RANGES)) {
    let status: FelinePediatricRange["status"] = "descriptive";
    let reason = FELINE_PEDIATRIC_NOTE;
    if (ageReason || !positive(weight)) {
      status = "unavailable";
      reason = ageReason || "Informe peso positivo e finito para contextualizar a coorte; não há domínio mínimo/máximo de peso publicado.";
    } else if (measurements.Pediatria_protocolo !== FELINE_PEDIATRIC_PROTOCOL) {
      status = "requires_method";
      reason = "Confirme ausência de sedação e o protocolo de aquisição de Gunther-Harrington et al. (2021).";
    } else if (method === "modo_m" && measurements.VE_tecnica_relatorio !== "modo_m") {
      status = "requires_method";
      reason = "Selecione modo M: eixo curto paraesternal direito no nível das cordoalhas, conforme o protocolo publicado.";
    } else if (method === "2d" && (measurements.VE_tecnica_relatorio !== "2d" || measurements.VE_vista_2D !== "eixo_longo")) {
      status = "requires_method";
      reason = "Selecione técnica 2D e vista de eixo longo paraesternal direito; limites do modo M não são intercambiáveis.";
    } else if (method === "ae_ao" && measurements.AE_Ao_metodo !== "2d_eixo_curto_diastole_inicial") {
      status = "requires_method";
      reason = "Confirme AE/Ao em 2D, eixo curto paraesternal direito, início da diástole, para estas dimensões.";
    }
    const available = status === "descriptive";
    ranges[key] = { status, lower: available ? lower : null, upper: available ? upper : null, unit,
      text: available ? `${format(lower)}–${format(upper)}${unit ? ` ${unit}` : ""} (coorte pediátrica)` : "—",
      reason, source: FELINE_PEDIATRIC_SOURCE, doi: FELINE_PEDIATRIC_DOI, statistic: "published_cohort_reference_interval" };
  }
  return { source: FELINE_PEDIATRIC_SOURCE, doi: FELINE_PEDIATRIC_DOI, population: POPULATION,
    patient_age_weeks: weeks, min_age_weeks: 6, max_age_weeks: 16, reason: ageReason || FELINE_PEDIATRIC_NOTE, ranges };
}

/** Juvenile age supersedes every adult catalog path. Cohort numbers never enter
 * generic min/max fields (nor their candidate metadata), so old consumers cannot
 * classify a kitten automatically or treat the cohort as weight-adjusted. */
export function applyFelinePediatricReference(reference: ReferenciaEco, measurements: Record<string, string>, weight: unknown, age: unknown): ReferenciaEco {
  const result = { ...reference } as ReferenciaEco & Record<string, unknown>;
  const pediatric = felinePediatricReference(reference.especie, weight, age, measurements);
  delete result.pediatric_reference;
  if (!pediatric) return result;
  result.pediatric_reference = pediatric;
  result.catalog_ranges = { ...reference.catalog_ranges };
  result.range_metadata = { ...reference.range_metadata };
  for (const prefix of GENERIC_PREFIXES) {
    if (!Object.hasOwn(result.catalog_ranges, prefix)) {
      result.catalog_ranges[prefix] = { min: reference[`${prefix}_min` as keyof ReferenciaEco] as number | null | undefined,
        max: reference[`${prefix}_max` as keyof ReferenciaEco] as number | null | undefined };
    }
    result[`${prefix}_min`] = null;
    result[`${prefix}_max`] = null;
    result.range_metadata[prefix] = { status: "unavailable", candidate_min: null, candidate_max: null,
      reason: "Paciente felino em crescimento: faixas do catálogo adulto não aplicadas. Consulte a referência pediátrica compatível com idade e técnica." };
  }
  delete result.fs_source;
  delete result.la_ao_source;
  delete result.tapse_source;
  delete result.reference_origin;
  return result;
}
