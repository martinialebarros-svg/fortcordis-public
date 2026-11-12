import api from "@/lib/axios";
import { loadStableCatalog } from "@/lib/stable-catalog-cache";

import {
  ClinicaOption,
  ContaFinanceiraResponse,
  DreResponse,
  FiltrosRelatorio,
  FinanceiroContextoResponse,
  FluxoCaixaResponse,
  ProfissionalOption,
  RelatorioCategoriaResponse,
  RelatorioComparativoResponse,
  RelatorioControleResponse,
  SecaoExport,
  ServicoOption,
} from "../types";

const montarQuery = (params: object): string => {
  const query = new URLSearchParams();
  Object.entries(params as Record<string, unknown>).forEach(([chave, valor]) => {
    if (valor === undefined || valor === null || valor === "") return;
    query.set(chave, String(valor));
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
};

const normalizarLista = <T>(payload: unknown): T[] => {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const maybeItems = (payload as { items?: unknown; data?: unknown }).items;
    if (Array.isArray(maybeItems)) return maybeItems as T[];
    const maybeData = (payload as { data?: unknown }).data;
    if (Array.isArray(maybeData)) return maybeData as T[];
  }
  return [];
};

export const listarClinicasRelatorio = async (): Promise<ClinicaOption[]> => {
  const payload = await loadStableCatalog({
    catalog: "clinicas",
    variant: "limit=1000",
    load: () => api.get("/clinicas?limit=1000").then((response) => response.data),
  });
  const itens = normalizarLista<ClinicaOption>(payload);
  return itens
    .filter((item) => Number.isFinite(Number(item?.id)))
    .map((item) => ({
      id: Number(item.id),
      nome: String(item.nome || `Clinica #${item.id}`),
      regiao_operacional: item.regiao_operacional || null,
      bairro: item.bairro || null,
      cidade: item.cidade || null,
      estado: item.estado || null,
    }))
    .sort((a, b) => a.nome.localeCompare(b.nome));
};

export const listarServicosRelatorio = async (): Promise<ServicoOption[]> => {
  const payload = await loadStableCatalog({
    catalog: "servicos",
    variant: "limit=1000",
    load: () => api.get("/servicos?limit=1000").then((response) => response.data),
  });
  const itens = normalizarLista<ServicoOption>(payload);
  return itens
    .filter((item) => Number.isFinite(Number(item?.id)))
    .map((item) => ({
      id: Number(item.id),
      nome: String(item.nome || `Servico #${item.id}`),
    }))
    .sort((a, b) => a.nome.localeCompare(b.nome));
};

export const listarProfissionaisRelatorio = async (): Promise<ProfissionalOption[]> => {
  try {
    const response = await api.get("/admin/usuarios");
    const itens = normalizarLista<{ id: number; nome?: string; email?: string }>(response.data);
    return itens
      .filter((item) => Number.isFinite(Number(item?.id)))
      .map((item) => ({
        id: Number(item.id),
        nome: String(item.nome || `Usuario #${item.id}`),
        email: item.email || null,
      }))
      .sort((a, b) => a.nome.localeCompare(b.nome));
  } catch {
    return [];
  }
};

export const obterRelatorioControle = async (
  filtros: FiltrosRelatorio
): Promise<RelatorioControleResponse> => {
  const query = montarQuery(filtros);
  const response = await api.get<RelatorioControleResponse>(`/relatorios/controle${query}`);
  return response.data;
};

export const exportarRelatorioControle = async ({
  formato,
  filtros,
  secoes,
}: {
  formato: "csv" | "pdf";
  filtros: FiltrosRelatorio;
  secoes: SecaoExport[];
}): Promise<{ blob: Blob; filename: string }> => {
  const params: Record<string, unknown> = {
    ...filtros,
    secoes: secoes.join(","),
  };
  const query = montarQuery(params);
  const response = await api.get(`/relatorios/controle/export/${formato}${query}`, {
    responseType: "blob",
  });

  const blob = new Blob([response.data], {
    type: formato === "csv" ? "text/csv;charset=utf-8" : "application/pdf",
  });
  const contentDisposition = String(response.headers?.["content-disposition"] || "");
  const filenameMatch = contentDisposition.match(/filename=\"?([^\"]+)\"?/i);
  const filename = filenameMatch?.[1] || `relatorio_${formato}.${formato}`;
  return { blob, filename };
};

const tentar = async <T>(promessa: Promise<{ data: T }>): Promise<T | null> => {
  try {
    const response = await promessa;
    return response.data;
  } catch {
    return null;
  }
};

export const obterContextoFinanceiro = async (
  filtros: FiltrosRelatorio
): Promise<FinanceiroContextoResponse> => {
  const baseParams = {
    data_inicio: filtros.data_inicio,
    data_fim: filtros.data_fim,
  };

  const filtrosConta = {
    ...baseParams,
    limit: 500,
    clinica_id: filtros.clinica_id,
  };

  const [dre, fluxo_caixa, despesas_por_categoria, comparativo_mensal, contas_receber, contas_pagar] =
    await Promise.all([
      tentar(api.get<DreResponse>(`/financeiro/relatorios/dre${montarQuery(baseParams)}`)),
      tentar(api.get<FluxoCaixaResponse>(`/financeiro/relatorios/fluxo-caixa${montarQuery(baseParams)}`)),
      tentar(
        api.get<RelatorioCategoriaResponse>(
          `/financeiro/relatorios/categorias${montarQuery({
            ...baseParams,
            tipo: "saida",
          })}`
        )
      ),
      tentar(api.get<RelatorioComparativoResponse>("/financeiro/relatorios/comparativo-mensal?meses=6")),
      tentar(api.get<ContaFinanceiraResponse>(`/financeiro/contas-receber${montarQuery(filtrosConta)}`)),
      tentar(api.get<ContaFinanceiraResponse>(`/financeiro/contas-pagar${montarQuery(filtrosConta)}`)),
    ]);

  return {
    dre,
    fluxo_caixa,
    despesas_por_categoria,
    comparativo_mensal,
    contas_receber,
    contas_pagar,
  };
};
