import { normalizeEchoSpecies } from "./echo-species";
import { ECHO_LENGTH_KEYS, ambiguousEchoLengthKeys, echoLengthInMm } from "./echo-unit-provenance";

/** ACVIM 2020, Tables 2/3. This is echo probability, not a pressure grade. */
export const HP_SITE_KEYS = {
  ventriculos: "HP_ventriculos",
  arteria_pulmonar: "HP_arteria_pulmonar",
  atrio_cava: "HP_atrio_cava",
} as const;
export type HPSite = keyof typeof HP_SITE_KEYS;
const SITES = Object.keys(HP_SITE_KEYS) as HPSite[];
const SITE_LABELS: Record<HPSite, string> = {
  ventriculos: "Ventrículos", arteria_pulmonar: "Artéria pulmonar",
  atrio_cava: "Átrio direito/veia cava caudal",
};
export const HP_ENUM_VALUES: Record<string, readonly string[]> = {
  HP_ativa: ["", "sim"], HP_TRV: ["", "adequado", "nao_mensuravel"],
  HP_VSVD: ["", "sem_obstrucao", "obstrucao"],
  HP_ventriculos: ["", "sem_sinais", "com_sinais"],
  HP_arteria_pulmonar: ["", "sem_sinais", "com_sinais"],
  HP_atrio_cava: ["", "sem_sinais", "com_sinais"],
  HP_suporte_automatico: ["", "sim", "nao"],
};
/** Only these new clinical values may be acquired from an importer. */
export const HP_NUMERIC_KEYS = ["HP_RPAD", "HP_RPA_max", "HP_RPA_min", "HP_TA", "HP_TE", "HP_IP_inicio"] as const;
/** Keep this order in sync with the backend; the stamp binds review to acquisition. */
export const HP_CONTEXT_KEYS = [
  "HP_ativa", "HP_TRV", "HP_VSVD", "HP_ventriculos", "HP_arteria_pulmonar",
  "HP_atrio_cava", "HP_suporte_automatico", "IT_Vmax", "AP_Ao", "AP",
  "Ao_nivel_AP", "unidade_confirmada_AP", "unidade_confirmada_Ao_nivel_AP",
  "Remodelamento_AD", ...HP_NUMERIC_KEYS,
] as const;
const NUMERIC_CONTEXT = new Set<string>(["IT_Vmax", "AP_Ao", "AP", "Ao_nivel_AP", ...HP_NUMERIC_KEYS]);
const numericPattern = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
const text = (value: unknown): string => value === null || value === undefined ? "" : String(value).trim();
function number(value: unknown): number | null {
  if (typeof value === "boolean") return null;
  const raw = text(value).replace(/,/g, ".");
  if (!numericPattern.test(raw)) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}
type Measurements = Record<string, string>;
function lengthContext(measurements: Measurements): Measurements {
  const context = { ...measurements };
  for (const key of ECHO_LENGTH_KEYS) {
    const value = number(measurements[key]);
    context[key] = value === null ? "" : String(value);
  }
  return context;
}
type Probability = "baixa" | "intermediaria" | "alta";
export type EchoPulmonaryAssessment = {
  active: boolean; applicable: boolean;
  status: "inactive" | "unsupported" | "pending" | "classified";
  probability: Probability | null;
  positive_sites: HPSite[]; assessed_sites: HPSite[];
  missing: string[]; notes: string[]; evidence: string[]; summary: string;
  suggestions: Array<{ site: HPSite; reasons: string[] }>;
  review_valid: boolean; psap_usable: boolean;
  metrics: { trv: number | null; rpad: number | null; at_et: number | null; ap_ao: number | null; pr_early: number | null };
};

export function makePulmonaryReviewStamp(measurements: Measurements, species: string): string {
  const context: Array<[string, string | number | null | string[]]> = HP_CONTEXT_KEYS.map((key) => {
    const raw = text(measurements[key]);
    return [key, NUMERIC_CONTEXT.has(key) ? number(measurements[key]) ?? (raw || null) : raw];
  });
  context.push(["unidades_ambiguas_AP_Ao", [...ambiguousEchoLengthKeys(lengthContext(measurements))].filter((key) => key === "AP" || key === "Ao_nivel_AP").sort()]);
  return JSON.stringify(["acvim2020-v1", normalizeEchoSpecies(species), context]);
}
export function hasValidPulmonaryReview(measurements: Measurements, species: string): boolean {
  try {
    return JSON.stringify(JSON.parse(text(measurements.HP_revisao))) === makePulmonaryReviewStamp(measurements, species);
  } catch { return false; }
}
export function invalidatePulmonaryReview(measurements: Measurements): Measurements {
  return { ...measurements, HP_revisao: "" };
}
/** Raw dictionary values have already been decoded. Do not JSON-decode twice. */
export function normalizePulmonaryStoredValue(key: string, value: unknown): string | null {
  if (!key.startsWith("HP_") || value === null || value === undefined || typeof value === "object" || typeof value === "boolean") return null;
  const raw = String(value);
  if (key in HP_ENUM_VALUES) return HP_ENUM_VALUES[key].includes(raw.trim()) ? raw.trim() : null;
  if ((HP_NUMERIC_KEYS as readonly string[]).includes(key)) return raw.trim();
  if (key === "HP_observacoes") return raw;
  if (key === "HP_revisao") {
    if (!raw.trim()) return "";
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) && parsed.length === 3 && parsed[0] === "acvim2020-v1" && typeof parsed[1] === "string" && Array.isArray(parsed[2]) ? raw : null;
    } catch { return null; }
  }
  return null;
}
export function caninePulmonaryProbability(trv: number | null, siteCount: number): Probability {
  if (!Number.isInteger(siteCount) || siteCount < 0 || siteCount > 3) throw new RangeError("Anatomic sites must be an integer from 0 to 3");
  if (trv !== null && (!Number.isFinite(trv) || trv <= 0)) throw new RangeError("TR velocity must be positive and finite or explicitly nonmeasurable");
  // Exactly 3.0 belongs to the <=3.0 row, resolving the published overlap.
  if (trv === null || trv <= 3) return siteCount === 3 ? "alta" : siteCount === 2 ? "intermediaria" : "baixa";
  if (trv <= 3.4) return siteCount >= 2 ? "alta" : "intermediaria";
  return siteCount >= 1 ? "alta" : "intermediaria";
}

export function evaluatePulmonaryProbability(measurements: Measurements, species: string): EchoPulmonaryAssessment {
  const m = measurements || {};
  const active = text(m.HP_ativa) === "sim";
  const applicable = normalizeEchoSpecies(species) === "Canina";
  const review_valid = hasValidPulmonaryReview(m, species);
  const rawTrv = number(m.IT_Vmax);
  const trv = rawTrv !== null && rawTrv > 0 && text(m.HP_TRV) === "adequado" ? rawTrv : null;
  const result: EchoPulmonaryAssessment = {
    active, applicable, status: !active ? "inactive" : applicable ? "pending" : "unsupported",
    probability: null, positive_sites: [], assessed_sites: [], missing: [], notes: [], suggestions: [],
    review_valid, evidence: [], summary: "Avaliação de probabilidade de hipertensão pulmonar não ativada.",
    metrics: { trv, rpad: null, at_et: null, ap_ao: null, pr_early: null },
    psap_usable: !active || (review_valid && trv !== null && text(m.HP_VSVD) === "sem_obstrucao"),
  };
  if (!active) return result;
  const { missing, notes, metrics } = result;
  if (applicable && !review_valid) missing.push("Reconfirmar avaliação após preencher, editar ou reimportar medidas.");
  const trvState = text(m.HP_TRV);
  if (applicable && !["adequado", "nao_mensuravel"].includes(trvState)) missing.push("Confirmar qualidade/mensurabilidade da regurgitação tricúspide.");
  else if (applicable && trvState === "adequado" && trv === null) missing.push("Informar velocidade tricúspide positiva e finita.");
  if (trvState === "nao_mensuravel") notes.push("Regurgitação tricúspide não mensurável; sua ausência não exclui hipertensão pulmonar.");
  const rvot = text(m.HP_VSVD);
  if (applicable && rvot !== "sem_obstrucao") missing.push(rvot === "obstrucao" ? "Obstrução da via de saída do VD presente; matriz não interpretável." : "Confirmar ausência de obstrução da via de saída do VD.");
  for (const site of SITES) {
    const state = text(m[HP_SITE_KEYS[site]]);
    if (["sem_sinais", "com_sinais"].includes(state)) result.assessed_sites.push(site);
    if (state === "com_sinais") result.positive_sites.push(site);
  }
  let apAo = number(m.AP_Ao);
  if (apAo === null || apAo <= 0) {
    const lengths = lengthContext(m);
    const ambiguous = [...ambiguousEchoLengthKeys(lengths)].filter((key) => key === "AP" || key === "Ao_nivel_AP").sort();
    const ap = echoLengthInMm(lengths, "AP");
    const ao = echoLengthInMm(lengths, "Ao_nivel_AP");
    const apUnit = text(m.unidade_confirmada_AP), aoUnit = text(m.unidade_confirmada_Ao_nivel_AP);
    apAo = ap !== null && ao !== null && ap > 0 && ao > 0 && ["", "cm", "mm"].includes(apUnit) && ["", "cm", "mm"].includes(aoUnit) ? ap / ao : null;
    if (ambiguous.length) {
      const message = `Confirmar unidade de AP/Ao antes de usar a razão derivada: ${ambiguous.join(", ")}.`;
      if (applicable && text(m.HP_suporte_automatico) !== "nao") missing.push(message);
      else notes.push(message);
    }
    if (apAo !== null && (!Number.isFinite(apAo) || apAo <= 0)) {
      missing.push("Revisar AP/Ao calculado: resultado deve ser positivo e finito.");
      apAo = null;
    }
  }
  metrics.ap_ao = apAo;
  const early = number(m.HP_IP_inicio);
  metrics.pr_early = early !== null && early > 0 ? early : null;
  const rpaMax = number(m.HP_RPA_max), rpaMin = number(m.HP_RPA_min);
  if (text(m.HP_RPA_max) || text(m.HP_RPA_min)) {
    if (rpaMax !== null && rpaMin !== null && 0 < rpaMin && rpaMin <= rpaMax) {
      metrics.rpad = (rpaMax - rpaMin) / rpaMax * 100;
      notes.push("RPAD calculado pelos diâmetros máximo e mínimo no mesmo local/ciclo.");
    } else missing.push("Revisar diâmetros da artéria pulmonar direita: exigir 0 < mínimo ≤ máximo.");
  } else {
    const rpad = number(m.HP_RPAD);
    if (rpad !== null && rpad >= 0 && rpad <= 100) {
      metrics.rpad = rpad;
      notes.push("RPAD informado diretamente (%).");
    } else if (text(m.HP_RPAD)) missing.push("Revisar RPAD informado: exigir 0 a 100%.");
  }
  const ta = number(m.HP_TA), te = number(m.HP_TE);
  if (ta !== null && te !== null && 0 < ta && ta <= te) metrics.at_et = ta / te;
  else if (text(m.HP_TA) && text(m.HP_TE)) missing.push("Revisar TA/TE: exigir 0 < TA ≤ TE no mesmo traçado.");
  else if (text(m.HP_TA) || text(m.HP_TE)) notes.push("TA isolado é dado de consulta; não aplicado corte universal de probabilidade.");
  if (!applicable) {
    result.summary = "Matriz canina de probabilidade de hipertensão pulmonar não aplicável à espécie.";
    notes.push("Os critérios ACVIM caninos não estabelecem classificação validada para felinos ou outras espécies; métricas e sítios são apenas descritivos, sem aplicação de limiares caninos.");
    return result;
  }
  const reasons: string[] = [];
  if (apAo !== null && apAo > 1) reasons.push("AP/Ao > 1,0");
  if (metrics.pr_early !== null && metrics.pr_early > 2.5) reasons.push("Regurgitação pulmonar no início da diástole > 2,5 m/s");
  if (metrics.rpad !== null && metrics.rpad < 30) reasons.push("RPAD < 30%");
  if (metrics.at_et !== null && metrics.at_et < 0.30) reasons.push("TA/TE < 0,30");
  if (reasons.length) result.suggestions.push({ site: "arteria_pulmonar", reasons });
  if (["leve", "moderado", "importante"].includes(text(m.Remodelamento_AD))) result.suggestions.push({ site: "atrio_cava", reasons: ["Remodelamento do átrio direito informado"] });
  if (text(m.HP_suporte_automatico) !== "nao") {
    for (const suggestion of result.suggestions) if (!result.positive_sites.includes(suggestion.site)) missing.push(`Revisar sugestão de sinais em ${SITE_LABELS[suggestion.site]} ou excluir suporte automático por técnica inadequada.`);
  } else notes.push("Métricas de suporte automático excluídas pelo examinador; sítios classificados pela revisão anatômica.");
  const trvReady = trvState === "nao_mensuravel" || trv !== null;
  const minimum = trvReady ? caninePulmonaryProbability(trv, result.positive_sites.length) : null;
  const unassessed = SITES.filter((site) => !result.assessed_sites.includes(site));
  if (unassessed.length && minimum !== "alta") missing.push("Avaliar os três sítios anatômicos; ausência de preenchimento não significa ausência de sinais.");
  else if (unassessed.length) notes.push("Alta probabilidade já sustentada pelos sítios positivos; há sítios não avaliados.");
  result.evidence = [trvState === "nao_mensuravel" ? "TRV não mensurável" : trv !== null ? `TRV: ${trv} m/s` : "TRV pendente", `Sítios com sinais: ${result.positive_sites.length}/3; avaliados: ${result.assessed_sites.length}/3`];
  if (!missing.length) {
    result.status = "classified";
    result.probability = minimum;
    result.summary = `Probabilidade ecocardiográfica ${minimum === "intermediaria" ? "intermediária" : minimum} de hipertensão pulmonar (critérios ACVIM caninos).`;
  } else result.summary = "Probabilidade ecocardiográfica de hipertensão pulmonar pendente de revisão.";
  notes.push("PSAP estimada é informação complementar; não define isoladamente a probabilidade ou o diagnóstico de hipertensão pulmonar.");
  return result;
}
