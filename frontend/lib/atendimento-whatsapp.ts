import type { PatientAgeValue } from "./paciente-idade";
export type AtendimentoWhatsAppDocumentKind = "prescricao" | "exames";

type DocumentScalar = string | number | null | undefined;

type DocumentFormSource = {
  paciente_id?: DocumentScalar;
  clinica_id?: DocumentScalar;
  data_atendimento?: string;
  queixa_principal?: string;
  triagem?: { peso?: DocumentScalar };
  prescricao_alvo_id?: DocumentScalar;
  prescricao_orientacoes?: string;
  prescricao_retorno_dias?: DocumentScalar;
  prescricao_itens?: ReadonlyArray<{
    medicamento_id?: DocumentScalar;
    medicamento_nome?: string;
    apresentacao_selecionada?: string;
    dose?: string;
    frequencia?: string;
    duracao?: string;
    via?: string;
    instrucoes?: string;
  }>;
  exames?: ReadonlyArray<{ tipo_exame?: string; _destroy?: boolean }>;
};

type DocumentCadastroSource = {
  paciente?: PatientAgeValue & {
    nome?: string;
    especie?: string;
    raca?: string;
    sexo?: string;
    idade?: string;
    data_nascimento?: string | null;
    peso_kg?: DocumentScalar;
    observacoes?: string;
  };
  tutor?: { nome?: string };
};

/**
 * Snapshot of content used by the prescription/exam PDF builders. A save adds
 * row IDs, request timestamps and adjustment history; those are not user edits
 * and must not cancel the PDF preparation that requested that very save.
 */
export function buildAtendimentoDocumentRevision(form: DocumentFormSource, cadastro: DocumentCadastroSource): string {
  const scalar = (value: DocumentScalar) => value == null ? "" : String(value);
  const text = (value: string | null | undefined) => value ?? "";
  const paciente = cadastro.paciente;
  return JSON.stringify({
    paciente_id: scalar(form.paciente_id),
    clinica_id: scalar(form.clinica_id),
    data_atendimento: text(form.data_atendimento),
    queixa_principal: text(form.queixa_principal),
    peso_atendimento: scalar(form.triagem?.peso),
    paciente: {
      nome: text(paciente?.nome), especie: text(paciente?.especie), raca: text(paciente?.raca),
      sexo: text(paciente?.sexo), idade: text(paciente?.idade), nascimento: text(paciente?.data_nascimento),
      idade_informada: text(paciente?.idade_informada), idade_referencia: text(paciente?.idade_referencia), idade_fonte: text(paciente?.idade_fonte),
      peso: scalar(paciente?.peso_kg), observacoes: text(paciente?.observacoes),
    },
    tutor_nome: text(cadastro.tutor?.nome),
    prescricao_alvo_id: scalar(form.prescricao_alvo_id),
    prescricao_orientacoes: text(form.prescricao_orientacoes),
    prescricao_retorno_dias: scalar(form.prescricao_retorno_dias),
    prescricao_itens: (form.prescricao_itens ?? [])
      .filter((item) => item.medicamento_id || item.medicamento_nome?.trim())
      .map((item) => ({
        medicamento_id: scalar(item.medicamento_id), nome: text(item.medicamento_nome),
        apresentacao: text(item.apresentacao_selecionada), dose: text(item.dose),
        frequencia: text(item.frequencia), duracao: text(item.duracao), via: text(item.via),
        instrucoes: text(item.instrucoes),
      })),
    exames: (form.exames ?? []).filter((item) => !item._destroy && item.tipo_exame?.trim()).map((item) => item.tipo_exame),
  });
}

const BRAZIL_AREA_CODES = new Set([
  "11", "12", "13", "14", "15", "16", "17", "18", "19",
  "21", "22", "24", "27", "28", "31", "32", "33", "34", "35", "37", "38",
  "41", "42", "43", "44", "45", "46", "47", "48", "49", "51", "53", "54", "55",
  "61", "62", "63", "64", "65", "66", "67", "68", "69", "71", "73", "74", "75", "77", "79",
  "81", "82", "83", "84", "85", "86", "87", "88", "89", "91", "92", "93", "94", "95", "96", "97", "98", "99",
]);

/** Only accept an unambiguous Brazilian number, without inventing a DDD. */
export function normalizeAtendimentoWhatsAppPhone(value: string): string | null {
  const input = value.trim();
  if (!input || !/^\+?[\d\s().-]+$/.test(input)) return null;
  let digits = input.replace(/\D/g, "");
  // An explicitly international number must include country code and DDD.
  // Do not reinterpret '+55 99999-1234' as a local number in area code 55.
  if (input.startsWith("+") && (!digits.startsWith("55") || ![12, 13].includes(digits.length))) return null;
  if (digits.startsWith("0055")) digits = digits.slice(2);
  if (digits.length === 12 || digits.length === 13) {
    if (!digits.startsWith("55")) return null;
    digits = digits.slice(2);
  }
  if (!BRAZIL_AREA_CODES.has(digits.slice(0, 2))) return null;
  if (!/^\d{2}(?:[2-5]\d{7}|9\d{8})$/.test(digits)) return null;
  return `55${digits}`;
}

export function formatAtendimentoWhatsAppPhone(normalized: string): string {
  const local = normalized.slice(2);
  const split = local.length === 11 ? 7 : 6;
  return `+55 (${local.slice(0, 2)}) ${local.slice(2, split)}-${local.slice(split)}`;
}

// Do not put patient names, clinical content, protected document URLs or tokens in a URL.
export function buildAtendimentoWhatsAppUrl(phone: string): string | null {
  const normalized = normalizeAtendimentoWhatsAppPhone(phone);
  if (!normalized) return null;
  const message = "Olá! Aqui é da Fort Cordis. Posso compartilhar os documentos do atendimento por aqui?";
  return `https://wa.me/${normalized}?text=${encodeURIComponent(message)}`;
}

export function canShareAtendimentoPdf(file: File): boolean {
  try {
    return typeof navigator.share === "function"
      && typeof navigator.canShare === "function"
      && navigator.canShare({ files: [file] });
  } catch {
    return false;
  }
}

export function downloadAtendimentoPdf(file: File): void {
  const url = URL.createObjectURL(file);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Safari may start consuming the blob after the click handler returns.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
