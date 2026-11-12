import type { EchoRangeMetadata, ReferenciaEco } from "@/app/laudos/types/referencia-eco";
import { isFelineEchoSpecies, normalizeEchoSpecies } from "./echo-species";
import { applyLowWeightReference, makeLowWeightReference } from "./echo-low-weight-reference";

export const ECHO_REFERENCE_METHOD_VALUES = {
  TAPSE_metodo: ["modo_m_apical", "2d"],
  AE_Ao_metodo: ["2d_eixo_curto_diastole_inicial", "2d_eixo_curto_diastole_inicial_sueco", "outro"],
  Diastolica_metodo: ["canino_nao_sedado_pw_apical", "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo", "felino_adulto_nao_sedado_pw_apical_clique_aortico", "felino_adulto_nao_sedado_pw_apical_fim_fluxo", "felino_adulto_nao_sedado_pw_clique_aortico", "felino_adulto_nao_sedado_pw_fim_fluxo", "outro"],
  Diastolica_ondas: ["separadas", "fundidas", "nao_confirmadas"],
  TDI_metodo: ["canino_pw_anel_septal_choi", "canino_pw_basal_septal_wess", "canino_pw_basal_lateral_wess", "felino_pw_anel_lateral", "felino_pw_anel_septal", "outro"],
  TDI_ondas: ["separadas", "fundidas", "nao_confirmadas"],
} as const;

export const ECHO_REFERENCE_METHOD_KEYS = Object.keys(ECHO_REFERENCE_METHOD_VALUES);
const STRUCTURAL_PREFIXES = ["lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s", "ao", "la", "la_ao", "ap", "ap_ao"];
const WEIGHT_DOMAINS: Record<string, readonly [number, number]> = { Canina: [2.2, 95], Felina: [1.5, 11] };

function normalizedSpecies(species: string): string {
  return normalizeEchoSpecies(species);
}

function finite(value: unknown): number | null {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const parsed = Number(String(value).replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function setRange(reference: Record<string, unknown>, prefix: string, min: number | null, max: number | null) {
  reference[`${prefix}_min`] = min;
  reference[`${prefix}_max`] = max;
}

/** Resolve only measurement-compatible ranges; never changes the stored catalog. */
export function resolveEchoReferenceForMeasurements(
  reference: ReferenciaEco | null,
  measurements: Record<string, string>,
  weightKg?: number,
  age?: string | null,
): ReferenciaEco | null {
  if (!reference) return null;
  const resolved = { ...reference } as ReferenciaEco & Record<string, unknown>;
  const metadata = { ...reference.range_metadata };
  resolved.range_metadata = metadata;
  const weight = finite(weightKg === undefined ? reference.patient_weight_kg : weightKg);
  resolved.patient_weight_kg = weight ?? undefined;
  const currentAge = age === undefined ? reference.patient_age : age;
  if (currentAge !== undefined) resolved.patient_age = currentAge;

  const domain = WEIGHT_DOMAINS[normalizedSpecies(reference.especie)];
  const outsideStudy = domain && weight !== null && (weight < domain[0] || weight > domain[1]
    || reference.peso_kg < domain[0] || reference.peso_kg > domain[1]);
  const coverageMin = finite(reference.catalog_weight_min);
  const coverageMax = finite(reference.catalog_weight_max);
  const outsideCatalog = coverageMin !== null && coverageMax !== null
    && (weight === null || weight < coverageMin || weight > coverageMax);
  if (outsideStudy || outsideCatalog) {
    for (const prefix of [...STRUCTURAL_PREFIXES, "fs"]) {
      metadata[prefix] = { ...metadata[prefix], status: "unavailable",
        reason: outsideStudy ? "Peso fora da população estudada para esta faixa"
          : "Peso fora da cobertura de pesos cadastrados; não extrapolar a linha mais próxima" };
    }
  }

  for (const [prefix, original] of Object.entries(metadata)) {
    const info: EchoRangeMetadata = { ...original };
    metadata[prefix] = info;
    const hasDomain = finite(info.min_weight_kg) !== null || finite(info.max_weight_kg) !== null;
    const outsideDomain = hasDomain && (weight === null
      || (info.min_weight_kg != null && weight < info.min_weight_kg)
      || (info.max_weight_kg != null && weight > info.max_weight_kg));
    const requiredKey = info.required_measurement_key;
    const requiredValue = info.required_measurement_value ?? info.required_method;
    const methodMatches = !requiredKey || Boolean(requiredValue && measurements[requiredKey] === requiredValue);
    const candidateWeight = prefix === "tapse"
      ? finite(info.candidate_weight_kg ?? reference.patient_weight_kg ?? reference.peso_kg) : null;
    if (prefix === "tapse") info.candidate_weight_kg = candidateWeight;
    const wrongCandidateWeight = prefix === "tapse" && (weight === null || candidateWeight === null || candidateWeight !== weight);
    if (info.status === "blocked" || info.status === "unavailable" || outsideDomain || wrongCandidateWeight || !methodMatches) {
      setRange(resolved, prefix, null, null);
      if (outsideDomain) {
        info.status = "unavailable";
        info.reason = weight === null ? "Informe o peso do paciente para verificar a população estudada"
          : "Peso fora da população estudada para esta faixa";
      } else if (wrongCandidateWeight && info.status !== "blocked") {
        info.status = "unavailable";
        info.reason = "Faixa de TAPSE resolvida para outro peso; obtenha a referência para o peso atual do paciente";
      } else if (!methodMatches && info.status !== "blocked" && info.status !== "unavailable") {
        info.status = "requires_method";
        info.reason = "Confirme o método de obtenção para comparar com esta faixa";
      }
      continue;
    }
    const min = finite(info.candidate_min);
    const max = finite(info.candidate_max);
    if (requiredKey && min !== null && max !== null && min <= max) {
      setRange(resolved, prefix, min, max);
      info.status = "published";
    } else if (info.status === "requires_method") {
      setRange(resolved, prefix, null, null);
    }
  }

  // Older API responses must not restore intervals already rejected in the audit.
  if (!metadata.tapse) setRange(resolved, "tapse", null, null);
  if (!metadata.la_ao && (isFelineEchoSpecies(reference.especie)
      || (finite(resolved.la_ao_min) === 0.8 && finite(resolved.la_ao_max) === 1.6))) {
    setRange(resolved, "la_ao", null, null);
  }
  for (const prefix of ["vmax_ao", "vmax_pulm"]) {
    if (!metadata[prefix]) setRange(resolved, prefix, null, null);
  }
  if (/^canin/i.test(reference.especie)) {
    for (const [prefix, min, maxima] of [
      ["mv_e", 0.5, [1.09, 1.1]], ["mv_a", 0.3, [0.8]], ["mv_dt", 0, [160]],
    ] as const) {
      if (!metadata[prefix] && finite(resolved[`${prefix}_min`]) === min
          && maxima.some((max) => max === finite(resolved[`${prefix}_max`]))) {
        setRange(resolved, prefix, null, null);
      }
    }
  }
  return applyLowWeightReference(resolved, measurements, weight, currentAge);
}

/** List fallback follows the same species, study and coverage guards as /buscar. */
export function selectEchoReferenceFromCatalog(items: ReferenciaEco[], weightKg: number, species: string, age?: string | null): ReferenciaEco | null {
  const normalized = normalizedSpecies(species);
  const rows = items.filter((row) => normalizedSpecies(row.especie) === normalized
    && Number.isFinite(row.peso_kg) && row.peso_kg > 0);
  if (!Number.isFinite(weightKg) || weightKg <= 0) return null;
  if (!rows.length) return resolveEchoReferenceForMeasurements(makeLowWeightReference(normalized, weightKg, 0, {}, age), {}, weightKg, age);
  const domain = WEIGHT_DOMAINS[normalized];
  const eligible = rows.filter((row) => !domain || (row.peso_kg >= domain[0] && row.peso_kg <= domain[1]));
  const candidates = eligible.length ? eligible : rows;
  const selected = candidates.reduce((best, row) => {
    const distance = Math.abs(row.peso_kg - weightKg);
    const bestDistance = Math.abs(best.peso_kg - weightKg);
    return distance < bestDistance || (distance === bestDistance && row.peso_kg < best.peso_kg) ? row : best;
  }, candidates[0]);
  const metadata = { ...selected.range_metadata };
  if (metadata.tapse) metadata.tapse = { ...metadata.tapse,
    candidate_weight_kg: metadata.tapse.candidate_weight_kg ?? selected.patient_weight_kg ?? selected.peso_kg,
  };
  return resolveEchoReferenceForMeasurements({ ...selected,
    range_metadata: metadata,
    catalog_weight_min: eligible.length ? Math.min(...eligible.map((row) => row.peso_kg)) : null,
    catalog_weight_max: eligible.length ? Math.max(...eligible.map((row) => row.peso_kg)) : null,
    patient_weight_kg: weightKg,
    ...(age !== undefined ? { patient_age: age } : {}),
  }, {}, weightKg, age);
}

export function echoCatalogRange(reference: ReferenciaEco, prefix: string) {
  if (reference.catalog_ranges && Object.prototype.hasOwnProperty.call(reference.catalog_ranges, prefix)) {
    return reference.catalog_ranges[prefix];
  }
  const fields = reference as unknown as Record<string, unknown>;
  return { min: finite(fields[`${prefix}_min`]), max: finite(fields[`${prefix}_max`]) };
}

/** Form submissions contain only raw editable catalog fields, never derived API ranges. */
export function buildEchoReferenceCatalogForm(reference: ReferenciaEco, editablePrefixes: readonly string[]) {
  const form: Record<string, string | number | null> = { especie: reference.especie, peso_kg: reference.peso_kg };
  for (const prefix of editablePrefixes) {
    const range = echoCatalogRange(reference, prefix);
    form[`${prefix}_min`] = range.min ?? null;
    form[`${prefix}_max`] = range.max ?? null;
  }
  return form;
}
