export interface FiscalServico {
  os_id: number;
  numero_os: string;
  data_atendimento: string | null;
  data_prestacao: string | null;
  competencia: string | null;
  valor_final: number;
  status_os: string;
  tipo_cliente: string;
  cliente_nome: string;
  cliente_documento: string;
  clinica_id: number | null;
  clinica_nome: string | null;
  servico_nome: string;
  elegivel: boolean;
  motivos_pendencia: string[];
  fechamento_id: number | null;
  exportacoes_anteriores: number;
}

export interface FiscalPrevia {
  competencia: string;
  data_inicio: string;
  data_fim: string;
  items: FiscalServico[];
  resumo: {
    quantidade_os: number;
    quantidade_aptas: number;
    quantidade_pendentes: number;
    quantidade_canceladas: number;
    quantidade_ja_preparadas: number;
    quantidade_exportadas_anteriormente: number;
    valor_total: number;
    valor_apto: number;
  };
}

export interface FiscalPacote {
  id: number;
  competencia: string;
  quantidade_os: number;
  valor_total: number;
  arquivo_nome: string;
  usuario_nome: string | null;
  preparado_em: string;
}

export interface FiscalErro {
  mensagem: string;
  fechamentoIds: number[];
}

export function competenciaValida(value: string): boolean {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
}

export function formatarCompetencia(value: string): string {
  if (!competenciaValida(value)) return value;
  return `${value.slice(5, 7)}/${value.slice(0, 4)}`;
}

export function servicoSelecionavel(item: FiscalServico, competencia: string): boolean {
  return item.elegivel === true
    && item.competencia === competencia
    && !item.fechamento_id
    && item.status_os.trim().toLowerCase() !== "cancelado";
}

export function assinaturaSelecao(competencia: string, osIds: number[]): string {
  return JSON.stringify([competencia, [...new Set(osIds)].sort((a, b) => a - b)]);
}

export function nomeArquivoFiscal(headers: Record<string, unknown>, fallback: string): string {
  const disposition = String(headers["content-disposition"] || "");
  const match = disposition.match(/filename="([^"]+)"/i);
  return match?.[1] || fallback;
}

export async function lerErroFiscal(error: unknown, fallback: string): Promise<FiscalErro> {
  const failure = error as { response?: { data?: unknown }; userMessage?: string; message?: string } | undefined;
  let data = failure?.response?.data;
  try {
    if (typeof Blob !== "undefined" && data instanceof Blob) data = await data.text();
    if (typeof data === "string") {
      try {
        data = JSON.parse(data);
      } catch {
        return { mensagem: data as string, fechamentoIds: [] };
      }
    }
    if (data && typeof data === "object") {
      const object = data as { detail?: unknown; message?: string };
      const detail = object.detail ?? object;
      if (typeof detail === "string") return { mensagem: detail, fechamentoIds: [] };
      if (detail && typeof detail === "object") {
        const parsed = detail as { message?: string; fechamento_id?: number; fechamentos_ids?: number[] };
        const ids = [parsed.fechamento_id, ...(parsed.fechamentos_ids || [])]
          .filter((id): id is number => typeof id === "number" && Number.isInteger(id) && id > 0);
        return { mensagem: parsed.message || fallback, fechamentoIds: [...new Set(ids)] };
      }
    }
  } catch {
    // A falha de leitura do corpo não deve apagar a seleção nem impedir a tentativa seguinte.
  }
  return { mensagem: failure?.userMessage || failure?.message || fallback, fechamentoIds: [] };
}
