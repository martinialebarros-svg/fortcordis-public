import { operationalTodayDateInput } from "@/lib/calendar-date";

export interface PatientAgeValue {
  idade?: string | null;
  data_nascimento?: string | null;
  nascimento?: string | null;
  idade_informada?: string | null;
  idade_referencia?: string | null;
  idade_fonte?: string | null;
  observacoes?: string | null;
}

function date(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? parsed : null;
}
export function normalizarNascimento(value: string): string {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value.trim());
  return match ? `${match[3]}-${match[2]}-${match[1]}` : value.trim();
}
export function exibirNascimento(value?: string | null): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(value || "") ? value!.split("-").reverse().join("/") : value || "";
}
export function parsePatientAge(value: string): [number, number] | null {
  let text = value.trim().toLowerCase();
  if (/^\d+(?:[.,]\d+)?$/.test(text)) text += " anos";
  const pattern = /(\d+(?:[.,]\d+)?)\s*(anos?|a|meses|m[eê]s|m|semanas?|s|dias?|d)\b/g;
  const tokens = [...text.matchAll(pattern)];
  if (!tokens.length || text.replace(pattern, "").replace(/\s|\be\b|[,;+]/g, "")) return null;
  let months = 0, days = 0;
  const seen = new Set<string>();
  for (const token of tokens) {
    const number = Number(token[1].replace(",", ".")), unit = token[2][0];
    if (seen.has(unit)) return null;
    seen.add(unit);
    if (unit === "a" || unit === "m") months += number * (unit === "a" ? 12 : 1);
    else days += number * (unit === "s" ? 7 : 1);
  }
  days += (months % 1) * 30;
  return months > 6000 || days > 183000 ? null : [Math.floor(months), Math.floor(days)];
}
function monthsBetween(start: Date, end: Date): number {
  if (end < start) return -monthsBetween(end, start);
  const count = (end.getUTCFullYear() - start.getUTCFullYear()) * 12 + end.getUTCMonth() - start.getUTCMonth();
  const lastDay = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() + 1, 0)).getUTCDate();
  return count - Number(end.getUTCDate() < Math.min(start.getUTCDate(), lastDay));
}
function formatAge(months: number, days = 0): string {
  if (months < 0 || days < 0) return "";
  if (!months && days) return days < 30 ? `${days}d` : `${Math.floor(days / 30)}m`;
  const years = Math.floor(months / 12), rest = months % 12;
  return years ? `${years}a${rest ? ` ${rest}m` : ""}` : `${rest}m`;
}
/** null means legacy provenance: the caller preserves the old fallback contract. */
export function calcularIdadeComFonte(value: PatientAgeValue, reference = operationalTodayDateInput()): string | null {
  if (!["idade", "nascimento"].includes(value.idade_fonte || "")) return null;
  const ref = date(reference);
  if (!ref || reference > operationalTodayDateInput()) return "";
  if (value.idade_fonte === "idade") {
    const amount = parsePatientAge(value.idade_informada || ""), anchor = date(value.idade_referencia || "");
    if (!amount || !anchor || (value.idade_referencia || "") > operationalTodayDateInput()) return "";
    const [declaredMonths, declaredDays] = amount;
    // Arithmetic origin for an estimate only; never stored as a birthdate.
    const origin = new Date(anchor);
    origin.setUTCDate(1);
    origin.setUTCMonth(origin.getUTCMonth() - declaredMonths);
    const lastDay = new Date(Date.UTC(origin.getUTCFullYear(), origin.getUTCMonth() + 1, 0)).getUTCDate();
    origin.setUTCDate(Math.min(anchor.getUTCDate(), lastDay) - declaredDays);
    if (origin.getUTCFullYear() < 1 || ref < origin) return "";
    const months = monthsBetween(origin, ref);
    const formatted = formatAge(months, !months ? Math.round((ref.getTime() - origin.getTime()) / 86400000) : 0);
    return formatted ? `${formatted} (estimada)` : "";
  }
  const raw = normalizarNascimento(value.data_nascimento || value.nascimento || "");
  if (/^\d{4}$/.test(raw)) {
    const years = ref.getUTCFullYear() - Number(raw);
    return years < 0 ? "" : years === 0 ? "0–11 meses (estimada pelo ano)" : `${years - 1}–${years} anos (estimada pelo ano)`;
  }
  const born = date(raw);
  if (!born || ref < born) return "";
  const months = monthsBetween(born, ref);
  return formatAge(months, !months ? Math.round((ref.getTime() - born.getTime()) / 86400000) : 0);
}
export function patientAgeForm(value: PatientAgeValue = {}) {
  return {
    idade: value.idade || "", data_nascimento: value.data_nascimento || value.nascimento || "",
    idade_informada: value.idade_informada || "", idade_referencia: value.idade_referencia || "",
    idade_fonte: value.idade_fonte || "",
  };
}
export function patientAgePayload(value: PatientAgeValue) {
  return {
    data_nascimento: value.data_nascimento?.trim() || null,
    idade_informada: value.idade_informada?.trim() || null,
    idade_referencia: value.idade_referencia || null,
    idade_fonte: value.idade_fonte || null,
  };
}
export function changePatientAge(value: PatientAgeValue, field: "idade" | "data_nascimento", input: string, reference = operationalTodayDateInput()) {
  reference = reference || operationalTodayDateInput();
  const result = patientAgeForm(value);
  if (field === "idade") {
    result.idade_informada = input;
    result.idade_referencia = input.trim() ? reference : "";
    result.idade_fonte = input.trim() || !result.data_nascimento ? "idade" : "nascimento";
    // Keep the draft editable even while a partially typed age is invalid.
    result.idade = input.trim() ? input : calcularIdadeComFonte(result, reference) || "";
  } else {
    result.data_nascimento = normalizarNascimento(input);
    result.idade_fonte = input.trim() ? "nascimento" : result.idade_informada ? "idade" : "";
    result.idade = calcularIdadeComFonte(result, reference) || "";
  }
  return result;
}

/** Imported birthdate is an observation; its derived age must not become a declaration. */
export function importedPatientAge(value: PatientAgeValue, imported: PatientAgeValue, reference?: string) {
  let birth = normalizarNascimento(imported.data_nascimento || imported.nascimento || "");
  if (/^\d{8}$/.test(birth)) birth = `${birth.slice(0, 4)}-${birth.slice(4, 6)}-${birth.slice(6, 8)}`;
  if (/^\d{4}-\d{2}-\d{2}T/.test(birth)) birth = birth.slice(0, 10);
  if (date(birth) || /^\d{4}$/.test(birth)) return changePatientAge(value, "data_nascimento", birth, reference);
  return imported.idade && parsePatientAge(imported.idade)
    ? changePatientAge(value, "idade", imported.idade, reference) : {};
}
