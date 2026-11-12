import type { FiscalPacote, FiscalPrevia, FiscalServico } from "./fiscal-fechamento";

export type ModoFiscalRotina = "semanal" | "por_servico" | "mensal";
export type EtapaFiscal = "preparado" | "enviado_contador" | "nota_recebida" | "nota_encaminhada";

export interface FiscalRotinaClinica {
  clinica_id: number;
  nome: string;
  modo: "semanal" | "por_servico";
  pagamento_depende_nf: boolean;
  versao: number;
  origem: "padrao" | "vet_fauna" | "personalizada";
}

export interface FiscalRotinas {
  padrao: { modo: "semanal"; dia_semana: string; horario: string; timezone: string; automatico: false };
  clinicas: FiscalRotinaClinica[];
}

export interface FiscalServicoRotina extends FiscalServico {
  modo_preparacao: "semanal" | "por_servico";
  pagamento_depende_nf: boolean;
  realizacao_confirmada: boolean;
  fonte_realizacao: string;
  prazo_preparacao: string | null;
}

export interface FiscalPreviaRotina extends Omit<FiscalPrevia, "items" | "resumo"> {
  items: FiscalServicoRotina[];
  resumo: FiscalPrevia["resumo"] & { quantidade_por_servico: number; quantidade_pagamento_depende_nf: number };
  rotina: {
    modo: ModoFiscalRotina;
    data_corte: string | null;
    corte_em: string | null;
    proxima_preparacao_em: string | null;
    horario: string;
    timezone: string;
    automatico: false;
  };
}

export type FiscalPacoteRotina = FiscalPacote;

export interface FiscalAndamentoEvento {
  id: number;
  etapa_anterior: EtapaFiscal;
  destino: EtapaFiscal;
  versao: number;
  referencia_nota: string | null;
  observacao: string | null;
  registrado_em: string;
  usuario_id: number | null;
  usuario_nome: string | null;
}

export interface FiscalAndamento {
  os_id: number;
  numero_os: string;
  cliente_nome: string;
  clinica_nome: string;
  etapa: EtapaFiscal;
  versao: number;
  referencia_nota: string | null;
  atualizado_em: string | null;
  eventos: FiscalAndamentoEvento[];
}

export const ETAPAS_FISCAIS: Record<EtapaFiscal, string> = {
  preparado: "Informações preparadas",
  enviado_contador: "Informações enviadas ao contador",
  nota_recebida: "Nota recebida do contador",
  nota_encaminhada: "Nota encaminhada ao tomador",
};

export function proximaEtapaFiscal(etapa: EtapaFiscal): EtapaFiscal | null {
  return ({ preparado: "enviado_contador", enviado_contador: "nota_recebida", nota_recebida: "nota_encaminhada", nota_encaminhada: null } as const)[etapa];
}

export function domingoFiscal(data: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(data)) return false;
  const parsed = new Date(`${data}T12:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === data && parsed.getUTCDay() === 0;
}

export function assinaturaRotina(contexto: { competencia: string; modo: ModoFiscalRotina; data_corte?: string | null; clinica_id?: number | null }, osIds: number[]): string {
  return JSON.stringify([contexto.competencia, contexto.modo, contexto.data_corte || null, contexto.clinica_id || null, [...new Set(osIds)].sort((a, b) => a - b)]);
}

export function dataHoraFiscal(value: string | null): string {
  if (!value) return "—";
  const normalized = /(Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value.replace(" ", "T")}-03:00`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short", timeStyle: "short", timeZone: "America/Fortaleza",
  }).format(date);
}
