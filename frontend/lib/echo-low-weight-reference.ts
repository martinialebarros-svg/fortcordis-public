import type { EchoRangeMetadata, ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { normalizeEchoSpecies } from "./echo-species";

export const LOW_WEIGHT_PREFIXES = ["lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s"] as const;
type Prefix = typeof LOW_WEIGHT_PREFIXES[number];
type Bounds = readonly [number, number];
const TOY: Record<Prefix, readonly [number, number, number]> = {
  lvid_d: [1.02, 1.57, .332], lvid_s: [.54, 1.15, .263], ivs_d: [.15, .77, .486],
  ivs_s: [.46, .83, .238], lvpw_d: [.33, .57, .275], lvpw_s: [.43, .75, .310],
};
const FELINE: Record<number, Record<Prefix, Bounds>> = {
  1.5: { lvid_d: [9.5, 15], lvid_s: [4.2, 9.6], ivs_d: [2.3, 4], ivs_s: [3.5, 6.7], lvpw_d: [2.2, 3.8], lvpw_s: [3.6, 6.5] },
  2: { lvid_d: [10.2, 16], lvid_s: [4.6, 10.5], ivs_d: [2.5, 4.3], ivs_s: [3.7, 7.2], lvpw_d: [2.4, 4.1], lvpw_s: [3.9, 7.1] },
  2.5: { lvid_d: [10.9, 17], lvid_s: [4.8, 11.2], ivs_d: [2.6, 4.5], ivs_s: [3.9, 7.6], lvpw_d: [2.5, 4.4], lvpw_s: [4.1, 7.5] },
  3: { lvid_d: [11.4, 17.8], lvid_s: [5.1, 11.7], ivs_d: [2.7, 4.7], ivs_s: [4.1, 7.9], lvpw_d: [2.6, 4.5], lvpw_s: [4.3, 7.9] },
};
const FELINE_EXPONENT: Record<Prefix, number> = { lvid_d: .262, lvid_s: .261, ivs_d: .204, ivs_s: .227, lvpw_d: .244, lvpw_s: .263 };
const DOMAINS: Record<string, Bounds> = { Canina: [2.2, 95], Felina: [1.5, 11] };

function finite(value: unknown): number | null {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const numeric = Number(String(value).replace(",", "."));
  return Number.isFinite(numeric) ? numeric : null;
}
function validWeight(value: unknown): number | null {
  const weight = finite(value);
  return weight !== null && weight > 0 ? weight : null;
}
function round(value: number): number { return Math.floor(value * 100 + .5) / 100; }

/** <12 months is a conservative software guard, not a study's maturity cutoff. */
export function lowWeightAgeContext(age: unknown): "juvenile" | "adult" | "unknown" {
  let text = Array.from(String(age ?? "").trim().normalize("NFKD"))
    .filter((character) => character.charCodeAt(0) <= 0x7f).join("").toLowerCase();
  const yearRange = /^(\d+)[–-](\d+) anos \(estimada pelo ano\)$/.exec(String(age ?? "").toLowerCase());
  if (yearRange) return Number(yearRange[1]) >= 1 ? "adult" : "unknown";
  if (String(age ?? "").toLowerCase() === "0–11 meses (estimada pelo ano)") return "juvenile";
  text = text.replace(/\s*\(estimada\)$/, "");
  if (/^(?:filhote|juvenil|kitten|puppy|em crescimento)$/.test(text)) return "juvenile";
  if (/^(?:adult[oa]|adult)$/.test(text)) return "adult";
  const tokens = [...text.matchAll(/(\d+(?:[.,]\d+)?)\s*(anos?|years?|a|y|mes(?:es)?|months?|m|dias?|days?|d|semanas?|weeks?|w)\b/g)];
  if (!tokens.length) return "unknown";
  let remaining = text;
  for (const token of tokens.toReversed()) remaining = remaining.slice(0, token.index) + " " + remaining.slice(token.index! + token[0].length);
  if (remaining.replace(/[\s,;+]|\be\b|\band\b/g, "")) return "unknown";
  const months = tokens.reduce((sum, token) => {
    const unit = token[2];
    const factor = /^(?:a|y)/.test(unit) ? 12 : /^m/.test(unit) ? 1 : /^(?:s|w)/.test(unit) ? 7 / 30.4375 : 1 / 30.4375;
    return sum + Number(token[1].replace(",", ".")) * factor;
  }, 0);
  return months < 12 ? "juvenile" : "adult";
}

/** Only six M-mode dimensions; never adds 2D, atrial, Doppler or annular bounds. */
export function lowWeightMModeRanges(species: string | null | undefined, weightValue: unknown, age?: unknown): Record<string, EchoRangeMetadata> {
  const normalized = normalizeEchoSpecies(species);
  const weight = validWeight(weightValue);
  if (!["Canina", "Felina"].includes(normalized) || weight === null || weight >= 3) return {};
  const below = weight < 1.5;
  const maturity = lowWeightAgeContext(age);
  const output: Record<string, EchoRangeMetadata> = {};
  for (const prefix of LOW_WEIGHT_PREFIXES) {
    let bounds: number[], calculation: NonNullable<EchoRangeMetadata["calculation"]>, formula: string, statistic: string, source: string, doi: string, population: string;
    const exponent = normalized === "Canina" ? TOY[prefix][2] : FELINE_EXPONENT[prefix];
    if (normalized === "Canina") {
      const [lower, upper] = TOY[prefix];
      bounds = [lower, upper].map((coefficient) => round(10 * coefficient * weight ** exponent));
      calculation = below ? "extrapolated" : "allometric";
      formula = `10 x (${lower}; ${upper}) x peso^${exponent} mm`;
      source = "Isayama et al. 2022; Tabela 2; limites alométricos aproximados; modo M";
      doi = "10.3389/fvets.2022.918457";
      population = "86 cães adultos de pequeno porte, não sedados; peso <5 kg; domínio tabulado 1,5-5 kg";
      statistic = "approximate_allometric_prediction_limits_95";
    } else {
      source = "Häggström et al. 2016; Tabela 3 corrigida; modo M";
      doi = "10.1111/jvim.14569";
      population = "18460 gatos adultos de raça pura com ecocardiogramas normais; domínio tabulado 1,5-11 kg";
      if (below) {
        bounds = FELINE[1.5][prefix].map((bound) => round(bound * (weight / 1.5) ** exponent));
        calculation = "extrapolated"; statistic = "extrapolated_estimate";
        formula = `limites tabulados de 1,5 kg x (peso / 1,5)^${exponent}`;
      } else {
        const nodes = Object.keys(FELINE).map(Number);
        const low = Math.max(...nodes.filter((node) => node <= weight));
        const high = Math.min(...nodes.filter((node) => node >= weight));
        const factor = low === high ? 0 : (weight - low) / (high - low);
        bounds = FELINE[low][prefix].map((bound, index) => round(bound + factor * (FELINE[high][prefix][index] - bound)));
        calculation = low === high ? "tabulated" : "interpolated";
        statistic = calculation === "tabulated" ? "prediction_interval_95" : "interpolated_prediction_limits_95";
        formula = factor ? `Tabela 3: ${low}-${high} kg; interpolação linear dos limites` : "Tabela 3: limites do peso tabulado";
      }
    }
    if (!(bounds[0] > 0 && bounds[1] > bounds[0])) continue;
    let reason = below ? "Estimativa por extrapolação abaixo de 1,5 kg; sem intervalo individual validado e sem classificação automática. "
      : calculation === "interpolated" ? "Limites calculados por interpolação entre pesos tabulados. "
      : calculation === "allometric" ? "Limites alométricos aproximados calculados para o peso real. " : "Intervalo do peso tabulado na publicação. ";
    reason += "Referência de adultos; não aplicar automaticamente a animais em crescimento nem concluir diagnóstico isoladamente.";
    const meta: EchoRangeMetadata = { status: below ? "estimated" : "published", source, doi, statistic: below ? "extrapolated_estimate" : statistic,
      population, min_weight_kg: 1.5, max_weight_kg: normalized === "Canina" ? 5 : 11,
      model_weight_kg: weight, calculation, formula, exponent, reason,
      candidate_min: below ? null : bounds[0], candidate_max: below ? null : bounds[1] };
    if (below) Object.assign(meta, { estimate_min: bounds[0], estimate_max: bounds[1], estimate_context: "weight_extrapolation" });
    if (maturity === "juvenile") {
      Object.assign(meta, { status: "unavailable", candidate_min: null, candidate_max: null,
        reason: "Referência de adultos não aplicada: paciente em crescimento; sem comparação automática e sem referência pediátrica reconciliada." });
      delete meta.estimate_min; delete meta.estimate_max; delete meta.estimate_context;
    } else if (maturity === "unknown") {
      Object.assign(meta, { status: "estimated", candidate_min: null, candidate_max: null, estimate_min: bounds[0], estimate_max: bounds[1],
        estimate_context: below ? "weight_extrapolation" : "age_unconfirmed",
        reason: `${reason} Limites de adultos; idade/maturidade a confirmar, sem classificação automática.` });
    }
    output[prefix] = meta;
  }
  return output;
}

/** Ephemeral display carrier, never an editable database row. */
export function makeLowWeightReference(species: string | null | undefined, weightValue: unknown, id = 0,
  catalogRanges: ReferenciaEco["catalog_ranges"] = {}, age?: unknown): ReferenciaEco | null {
  const normalized = normalizeEchoSpecies(species);
  const weight = validWeight(weightValue);
  if (!["Canina", "Felina"].includes(normalized) || weight === null || weight >= 3) return null;
  return { id, especie: normalized as ReferenciaEco["especie"], peso_kg: weight, patient_weight_kg: weight,
    patient_age: age == null ? undefined : String(age), reference_origin: "computed", catalog_ranges: structuredClone(catalogRanges) };
}

/** Recompute from current context, never by reusing a cached model's bounds. */
export function applyLowWeightReference(reference: ReferenciaEco, measurements: Record<string, string>, weightValue: unknown, age?: unknown): ReferenciaEco {
  const result = { ...reference, range_metadata: { ...reference.range_metadata } } as ReferenciaEco & Record<string, unknown>;
  const weight = validWeight(weightValue);
  const normalized = normalizeEchoSpecies(reference.especie);
  const domain = DOMAINS[normalized];
  const min = finite(reference.catalog_weight_min), max = finite(reference.catalog_weight_max);
  const rowWeight = validWeight(reference.peso_kg);
  const eligible = Boolean(weight !== null && domain && weight >= domain[0] && weight <= domain[1]
    && rowWeight !== null && rowWeight >= domain[0] && rowWeight <= domain[1]
    && (min === null || max === null || (weight >= min && weight <= max)));
  for (const prefix of LOW_WEIGHT_PREFIXES) {
    const meta = result.range_metadata?.[prefix];
    if (meta?.model_weight_kg == null) continue;
    const raw = reference.catalog_ranges?.[prefix];
    const low = finite(raw?.min), high = finite(raw?.max);
    const usableRaw = eligible && low !== null && high !== null && high >= low && (low !== 0 || high !== 0);
    result[`${prefix}_min`] = usableRaw ? low : null; result[`${prefix}_max`] = usableRaw ? high : null;
    result.range_metadata![prefix] = usableRaw ? { status: "catalog", reason: "Faixa cadastrada; publicação e método ainda não reconciliados", candidate_min: low, candidate_max: high }
      : { status: "unavailable", reason: "Modelo calculado indisponível para o contexto atual" };
  }
  let used = false;
  for (const [prefix, model] of Object.entries(lowWeightMModeRanges(normalized, weight, age))) {
    const existingLow = finite(result[`${prefix}_min`]), existingHigh = finite(result[`${prefix}_max`]);
    if (existingLow !== null && existingHigh !== null && existingLow <= existingHigh && (existingLow !== 0 || existingHigh !== 0)) continue;
    const meta = { ...model };
    if (measurements.VE_tecnica_relatorio === "2d") {
      Object.assign(meta, { status: "unavailable", candidate_min: null, candidate_max: null, reason: "Modo M: não aplicar à técnica 2D selecionada" });
      delete meta.estimate_min; delete meta.estimate_max; delete meta.estimate_context;
    }
    result.range_metadata![prefix] = meta;
    result[`${prefix}_min`] = meta.candidate_min ?? null; result[`${prefix}_max`] = meta.candidate_max ?? null;
    used = true;
  }
  delete result.reference_origin;
  if (used) result.reference_origin = "computed";
  return result;
}

export function lowWeightEstimateText(metadata: EchoRangeMetadata | undefined): string | null {
  if (metadata?.status !== "estimated" || finite(metadata.estimate_min) === null || finite(metadata.estimate_max) === null) return null;
  const format = (value: number) => value.toFixed(2).replace(".", ",");
  return `~${format(metadata.estimate_min!)}–${format(metadata.estimate_max!)} mm (estimativa)`;
}
