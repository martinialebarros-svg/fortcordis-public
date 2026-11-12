import { ambiguousEchoLengthKeys, confirmedEchoUnit, echoLengthInMm } from "./echo-unit-provenance";

export type EchoExamSnapshot = {
  id: number; paciente_id: number; status: string; data_exame: string | null;
  medidas: Record<string, string>;
};
export type EchoPreviousExamResponse = {
  estado: "disponivel" | "sem_anterior" | "data_atual_ausente" | "data_anterior_ambigua" | "tipo_nao_suportado";
  paciente_id: number; atual: EchoExamSnapshot; anterior: EchoExamSnapshot | null;
  opcoes: { id: number; data_exame: string }[];
};
type ComparisonRow = { key: string; label: string; current: string; previous: string; delta: string; reason: string };
const DIMENSIONS = [
  ["DIVEd", "DIVEd"], ["SIVd", "SIVd"], ["PLVEd", "PLVEd"],
  ["DIVES", "DIVEs"], ["SIVs", "SIVs"], ["PLVES", "PLVEs"],
] as const;
const AE_METHODS = ["2d_eixo_curto_diastole_inicial", "2d_eixo_curto_diastole_inicial_sueco"];
const STATES = ["disponivel", "sem_anterior", "data_atual_ausente", "data_anterior_ambigua", "tipo_nao_suportado"];
function object(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function id(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) > 0; }
function day(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value + "T00:00:00Z");
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
function snapshot(value: unknown, patientId: number): value is EchoExamSnapshot {
  return object(value) && id(value.id) && value.paciente_id === patientId && typeof value.status === "string"
    && (value.data_exame === null || day(value.data_exame)) && object(value.medidas)
    && Object.values(value.medidas).every((entry) => typeof entry === "string");
}

/** Reject mismatched/stale identities before exposing either snapshot. */
export function isEchoPreviousExamResponse(value: unknown, reportId: number, patientId: number, selectedId: number | null): value is EchoPreviousExamResponse {
  if (!object(value) || !STATES.includes(String(value.estado)) || value.paciente_id !== patientId
    || !snapshot(value.atual, patientId) || value.atual.id !== reportId || !Array.isArray(value.opcoes)) return false;
  const currentDay = value.atual.data_exame;
  const options = value.opcoes;
  if (!options.every((option) => object(option) && id(option.id) && option.id !== reportId && day(option.data_exame)
    && currentDay !== null && option.data_exame < currentDay)
    || new Set(options.map((option) => option.id)).size !== options.length) return false;
  if (value.estado !== "disponivel") {
    if (value.anterior !== null || selectedId !== null) return false;
    if (value.estado === "data_anterior_ambigua") {
      const dates = options.map((option) => option.data_exame as string).sort().reverse();
      return dates.length > 1 && dates[0] === dates[1];
    }
    return options.length === 0;
  }
  if (!day(currentDay) || !snapshot(value.anterior, patientId) || !["Finalizado", "Liberado no portal"].includes(value.anterior.status)
    || !day(value.anterior.data_exame) || value.anterior.data_exame >= currentDay || value.anterior.id === reportId
    || (selectedId !== null && value.anterior.id !== selectedId)) return false;
  const previous = value.anterior;
  if (!options.some((option) => option.id === previous.id && option.data_exame === previous.data_exame)) return false;
  if (selectedId === null) {
    const dates = options.map((option) => option.data_exame as string).sort().reverse();
    if (dates[0] !== previous.data_exame || dates[0] === dates[1]) return false;
  }
  return true;
}

function positive(value: string | undefined): number | null {
  if (!value?.trim() || !/^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$/.test(value.trim())) return null;
  const number = Number(value.replace(",", "."));
  return Number.isFinite(number) && number > 0 ? number : null;
}
const fixed = (value: number) => value.toFixed(2).replace(".", ",");
function invalidExplicitUnit(measurements: Record<string, string>, key: string): boolean {
  return Object.hasOwn(measurements, `unidade_confirmada_${key}`) && confirmedEchoUnit(measurements, key) === null;
}
function comparableLength(measurements: Record<string, string>, key: string): number | null {
  return invalidExplicitUnit(measurements, key) || positive(measurements[key]) === null ? null : echoLengthInMm(measurements, key);
}
function lengthValue(measurements: Record<string, string>, key: string): string {
  const raw = measurements[key];
  if (!raw?.trim()) return "—";
  const numeric = comparableLength(measurements, key);
  if (numeric === null) return `${raw} (unidade/valor a confirmar)`;
  return confirmedEchoUnit(measurements, key) === "cm"
    ? `${fixed(numeric)} mm (${raw} cm de origem)` : `${fixed(numeric)} mm`;
}

/** Arithmetic only. The complete 18-length context must reach the unit guard. */
export function buildEchoPreviousExamRows(current: EchoExamSnapshot, previous: EchoExamSnapshot): ComparisonRow[] {
  if (current.paciente_id !== previous.paciente_id || current.id === previous.id
    || !day(current.data_exame) || !day(previous.data_exame) || previous.data_exame >= current.data_exame) return [];
  const c = current.medidas, p = previous.medidas;
  const rows: ComparisonRow[] = [];
  for (const suffix of ["", "_2D"]) {
    for (const [base, label] of DIMENSIONS) {
      const key = base + suffix;
      if (!c[key]?.trim() && !p[key]?.trim()) continue;
      const technique = suffix ? "2d" : "modo_m";
      const sameTechnique = c.VE_tecnica_relatorio === technique && p.VE_tecnica_relatorio === technique;
      const sameView = !suffix || (["eixo_curto", "eixo_longo"].includes(c.VE_vista_2D) && c.VE_vista_2D === p.VE_vista_2D);
      const cv = comparableLength(c, key), pv = comparableLength(p, key);
      const ambiguous = invalidExplicitUnit(c, key) || invalidExplicitUnit(p, key)
        || ambiguousEchoLengthKeys(c).has(key) || ambiguousEchoLengthKeys(p).has(key);
      const reason = ambiguous ? "Unidade a confirmar" : cv === null || pv === null ? "Medida ausente ou inválida"
        : !sameTechnique ? "Técnica selecionada diferente ou não registrada"
        : !sameView ? "Vista 2D diferente ou não registrada" : "";
      const difference = reason ? null : Number((cv! - pv!).toFixed(2));
      rows.push({ key, label: `${label} · ${suffix ? "2D" : "Modo M"}`, current: lengthValue(c, key), previous: lengthValue(p, key),
        delta: difference === null ? "—" : `${difference > 0 ? "+" : ""}${fixed(difference)} mm`, reason });
    }
  }
  if (c.AE_Ao?.trim() || p.AE_Ao?.trim()) {
    const cv = positive(c.AE_Ao), pv = positive(p.AE_Ao);
    const reason = cv === null || pv === null ? "Medida ausente ou inválida"
      : !AE_METHODS.includes(c.AE_Ao_metodo) || c.AE_Ao_metodo !== p.AE_Ao_metodo
      ? "Método de AE/Ao diferente ou não confirmado" : "";
    const difference = reason ? null : Number((cv! - pv!).toFixed(2));
    rows.push({ key: "AE_Ao", label: "AE/Ao", current: c.AE_Ao || "—", previous: p.AE_Ao || "—",
      delta: difference === null ? "—" : `${difference > 0 ? "+" : ""}${fixed(difference)}`, reason });
  }
  return rows;
}

export function echoComparisonMethodLabel(measurements: Record<string, string>): string {
  const lv = measurements.VE_tecnica_relatorio === "modo_m" ? "Modo M"
    : measurements.VE_tecnica_relatorio === "2d" ? `2D · ${measurements.VE_vista_2D === "eixo_curto" ? "eixo curto" : measurements.VE_vista_2D === "eixo_longo" ? "eixo longo" : "vista não registrada"}`
    : "VE: técnica não registrada";
  const ae = measurements.AE_Ao_metodo === AE_METHODS[1] ? "AE/Ao: método sueco"
    : measurements.AE_Ao_metodo === AE_METHODS[0] ? "AE/Ao: 2D, eixo curto, diástole inicial" : "AE/Ao: método não confirmado";
  return `${lv}; ${ae}`;
}
