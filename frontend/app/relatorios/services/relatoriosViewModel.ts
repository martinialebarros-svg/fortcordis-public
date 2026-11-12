import {
  ClinicaOption,
  ComparativoMensalItem,
  ContaFinanceiraItem,
  FinanceiroContextoResponse,
  RelatorioControleResponse,
  RentabilidadeClinicaItem,
} from "../types";

const toNum = (v: number | null | undefined): number => Number(v || 0);

export const somarKmPeriodo = (relatorio: RelatorioControleResponse | null): number => {
  if (!relatorio) return 0;
  return relatorio.logistica.km_por_mes.reduce((acc, item) => acc + toNum(item.km_total), 0);
};

export const somarDuracaoPeriodoMin = (relatorio: RelatorioControleResponse | null): number => {
  if (!relatorio) return 0;
  return relatorio.logistica.km_por_mes.reduce((acc, item) => acc + Number(item.duracao_total_min || 0), 0);
};

export const mediaTicketPeriodo = (relatorio: RelatorioControleResponse | null): number => {
  if (!relatorio) return 0;
  const valor = toNum(relatorio.financeiro.periodo.valor_total_servicos);
  const qtd = Number(relatorio.financeiro.periodo.quantidade_servicos || 0);
  if (qtd <= 0) return 0;
  return valor / qtd;
};

export const totalContasPendentes = (
  contaResponse: { items?: ContaFinanceiraItem[] } | null | undefined,
  statuses: string[]
): number => {
  if (!contaResponse?.items) return 0;
  const pool = new Set(statuses.map((status) => status.toLowerCase()));
  return contaResponse.items
    .filter((item) => pool.has(String(item.status || "").toLowerCase()))
    .reduce((acc, item) => acc + toNum(item.valor), 0);
};

export const calcularInadimplenciaPercent = (
  contasReceber: { items?: ContaFinanceiraItem[] } | null
): number => {
  const itens = contasReceber?.items || [];
  if (!itens.length) return 0;
  const valorTotal = itens.reduce((acc, item) => acc + toNum(item.valor), 0);
  if (valorTotal <= 0) return 0;

  const atrasado = itens
    .filter((item) => String(item.status || "").toLowerCase() === "atrasado")
    .reduce((acc, item) => acc + toNum(item.valor), 0);
  return (atrasado / valorTotal) * 100;
};

export const montarComparativoCompetenciaCaixa = (
  relatorio: RelatorioControleResponse | null
): {
  receita_competencia: number;
  receita_caixa: number;
  gap_percent: number;
} => {
  const receitaCompetencia = toNum(relatorio?.financeiro.periodo.valor_total_servicos);
  const receitaCaixa = toNum(relatorio?.financeiro.periodo.entradas_recebidas);
  if (receitaCompetencia <= 0) {
    return {
      receita_competencia: receitaCompetencia,
      receita_caixa: receitaCaixa,
      gap_percent: 0,
    };
  }

  return {
    receita_competencia: receitaCompetencia,
    receita_caixa: receitaCaixa,
    gap_percent: ((receitaCaixa - receitaCompetencia) / receitaCompetencia) * 100,
  };
};

export const montarProjecaoFluxo30d = (
  financeiro: FinanceiroContextoResponse | null,
  dataReferencia: string
): {
  entradas_previstas: number;
  saidas_previstas: number;
  saldo_previsto: number;
} => {
  if (!financeiro) {
    return { entradas_previstas: 0, saidas_previstas: 0, saldo_previsto: 0 };
  }

  const dataBase = new Date(`${dataReferencia}T00:00:00`);
  const limite = new Date(dataBase);
  limite.setDate(limite.getDate() + 30);

  const dentroJanela = (valor?: string | null): boolean => {
    if (!valor) return false;
    const dt = new Date(valor);
    if (Number.isNaN(dt.getTime())) return false;
    return dt >= dataBase && dt <= limite;
  };

  const entradasPrevistas = (financeiro.contas_receber?.items || [])
    .filter((item) => ["Pendente", "Atrasado"].includes(String(item.status || "")))
    .filter((item) => dentroJanela(item.data_vencimento))
    .reduce((acc, item) => acc + toNum(item.valor), 0);

  const saidasPrevistas = (financeiro.contas_pagar?.items || [])
    .filter((item) => ["Pendente", "Atrasado"].includes(String(item.status || "")))
    .filter((item) => dentroJanela(item.data_vencimento))
    .reduce((acc, item) => acc + toNum(item.valor), 0);

  return {
    entradas_previstas: entradasPrevistas,
    saidas_previstas: saidasPrevistas,
    saldo_previsto: entradasPrevistas - saidasPrevistas,
  };
};

export const analisarPorRegiao = (
  relatorio: RelatorioControleResponse | null,
  clinicas: ClinicaOption[]
): Array<{ regiao: string; clinicas: number; agendamentos: number; valor_total: number }> => {
  if (!relatorio) return [];

  const clinicaMap = new Map<number, ClinicaOption>();
  clinicas.forEach((clinica) => clinicaMap.set(clinica.id, clinica));

  const agrupado = new Map<string, { clinicas: Set<number>; agendamentos: number; valor_total: number }>();
  for (const item of relatorio.rentabilidade.ranking_clinicas) {
    const clinica = clinicaMap.get(item.clinica_id);
    const regiao =
      clinica?.regiao_operacional ||
      clinica?.bairro ||
      clinica?.cidade ||
      clinica?.estado ||
      "Nao informado";

    if (!agrupado.has(regiao)) {
      agrupado.set(regiao, { clinicas: new Set<number>(), agendamentos: 0, valor_total: 0 });
    }
    const atual = agrupado.get(regiao)!;
    atual.clinicas.add(item.clinica_id);
    atual.agendamentos += Number(item.agendamentos || 0);
    atual.valor_total += toNum(item.valor_total_servicos);
  }

  return Array.from(agrupado.entries())
    .map(([regiao, valor]) => ({
      regiao,
      clinicas: valor.clinicas.size,
      agendamentos: valor.agendamentos,
      valor_total: valor.valor_total,
    }))
    .sort((a, b) => b.agendamentos - a.agendamentos);
};

export const ordenarComparativoMensal = (
  comparativo: ComparativoMensalItem[] | undefined
): ComparativoMensalItem[] => {
  if (!comparativo?.length) return [];
  return [...comparativo];
};

export const montarRentabilidadeResumo = (
  relatorio: RelatorioControleResponse | null
): {
  retorno_medio_por_km: number | null;
  ponto_equilibrio_servicos: number;
  ticket_medio_top_clinicas: number;
  melhores_clinicas: RentabilidadeClinicaItem[];
} => {
  if (!relatorio) {
    return {
      retorno_medio_por_km: null,
      ponto_equilibrio_servicos: 0,
      ticket_medio_top_clinicas: 0,
      melhores_clinicas: [],
    };
  }

  const ranking = relatorio.rentabilidade.ranking_clinicas || [];
  const retornoValidos = ranking
    .map((item) => item.retorno_por_km)
    .filter((value): value is number => value !== null && Number.isFinite(value));

  const retornoMedio =
    retornoValidos.length > 0
      ? retornoValidos.reduce((acc, value) => acc + value, 0) / retornoValidos.length
      : null;

  const ticketMedioTop = relatorio.financeiro.clinicas_maior_faturamento.length
    ? relatorio.financeiro.clinicas_maior_faturamento.reduce((acc, item) => {
        const qtd = Number(item.servicos || 0);
        if (qtd <= 0) return acc;
        return acc + item.valor_total / qtd;
      }, 0) / relatorio.financeiro.clinicas_maior_faturamento.length
    : 0;

  const ticketMedioGeral = toNum(relatorio.financeiro.mes_referencia.ticket_medio_servico);
  const despesas = toNum(relatorio.financeiro.periodo.saidas_pagas);
  const pontoEquilibrio = ticketMedioGeral > 0 ? despesas / ticketMedioGeral : 0;

  return {
    retorno_medio_por_km: retornoMedio,
    ponto_equilibrio_servicos: pontoEquilibrio,
    ticket_medio_top_clinicas: ticketMedioTop,
    melhores_clinicas: ranking.slice(0, 10),
  };
};
