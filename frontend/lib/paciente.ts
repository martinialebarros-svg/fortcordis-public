import { calcularIdadeComFonte, type PatientAgeValue } from "./paciente-idade";
export function normalizarSexoPaciente(sexo?: string | null): string {
  const texto = String(sexo || "").trim();
  if (!texto) return "";

  const normalizado = texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  if (normalizado.startsWith("f")) return "Fêmea";
  if (normalizado.startsWith("m")) return "Macho";
  return texto;
}

export function parsePesoKg(valor?: string | number | null): number | null {
  const texto = String(valor ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(",", ".");
  if (!texto) return null;

  const match = texto.match(/^([0-9]{1,3}(?:\.[0-9]{1,3})?)(?:kg)?$/);
  if (!match) return null;

  const peso = Number(match[1]);
  return Number.isFinite(peso) && peso > 0 && peso <= 300 ? peso : null;
}

function calcularIdadePorNascimento(dataNascimento?: string | null): string {
  const texto = String(dataNascimento || "").trim();
  if (!texto) return "";

  const nascimento = calendarDateParts(texto);
  const hoje = calendarDateParts(operationalTodayDateInput());
  if (!nascimento || !hoje) {
    return texto;
  }

  let meses = (Number(hoje.year) - Number(nascimento.year)) * 12;
  meses += Number(hoje.month) - Number(nascimento.month);

  if (meses < 12) {
    return `${meses}m`;
  }

  const anos = Math.floor(meses / 12);
  const mesesRestantes = meses % 12;
  return mesesRestantes > 0 ? `${anos}a ${mesesRestantes}m` : `${anos}a`;
}

export function extrairIdadePaciente(source: PatientAgeValue, referenceDate?: string): string {
  const authoritative = calcularIdadeComFonte(source, referenceDate);
  if (authoritative !== null) return authoritative;
  const idadeDireta = String(source.idade || "").trim();
  if (idadeDireta) {
    return idadeDireta;
  }

  const idadePorNascimento = calcularIdadePorNascimento(source.data_nascimento);
  if (idadePorNascimento) {
    return idadePorNascimento;
  }

  const match = /(?:^|\n)Idade:\s*(.+?)(?:\n|$)/i.exec(String(source.observacoes || ""));
  return match ? match[1].trim() : "";
}
import { calendarDateParts, operationalTodayDateInput } from "@/lib/calendar-date";
