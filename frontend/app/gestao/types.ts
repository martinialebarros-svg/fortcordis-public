export type ContextoGestao = {
  data_inicio: string;
  data_fim: string;
  clinica_id: number | null;
  regiao: string | null;
};

export type MovimentoPremissa = {
  data: string;
  tipo: "entrada" | "saida";
  valor: number | null;
  recorrencia: "unica" | "mensal";
  descricao: string;
};

export type PremissasGestao = {
  tributos_percentual: number | null;
  taxas_percentual: number | null;
  repasses_percentual: number | null;
  custos_variaveis: number | null;
  horas_atendimento: number | null;
  horas_laudos: number | null;
  horas_deslocamento: number | null;
  saldo_inicial: number | null;
  despesas_completas: boolean;
  movimentos: MovimentoPremissa[];
};

export type PremissasSalvas = {
  revision: number;
  updated_at: string | null;
  updated_by_id: number | null;
  contexto: ContextoGestao | null;
  values: Partial<PremissasGestao>;
};

export type DetalheOS = {
  os_id: number; numero_os: string; clinica_id: number | null; clinica_nome: string;
  regiao?: string | null; data_atendimento: string | null; valor: number | null; status?: string;
};
export type LinhaCaixa = {
  inicio: string; fim: string;
  entradas_confirmadas: number; entradas_previstas: number; saidas_confirmadas: number; saidas_previstas: number;
  entradas_premissas: number; saidas_premissas: number; saldo_final: number | null;
};
export type MetricasGestao = {
  contribuicao: {
    receita_competencia: number; tributos: number | null; taxas: number | null; repasses: number | null;
    custos_variaveis: number | null; horas_totais: number | null; valor: number | null; por_hora: number | null;
    estimado: boolean; lacunas: string[]; formula: string; detalhes: DetalheOS[];
    taxas_observadas?: number; taxas_fonte?: string; total_registros?: number; detalhes_limitados?: boolean; receita_parcial?: boolean;
  };
  recebimento: {
    prazo_medio_dias: number | null; valor_recebido_bruto: number; credito_utilizado: number;
    saldo_aberto: number; vencido: number; sem_vencimento: number; os_pagas_sem_comprovante: number; saldo_parcial?: boolean;
    lacunas: string[]; formula: string; data_referencia?: string; total_registros?: number; detalhes_limitados?: boolean;
    detalhes: Array<DetalheOS & { recebido: number; credito: number; saldo_aberto: number | null; prazo_medio_dias: number | null; vencimento: string | null; legacy: boolean }>;
  };
  concentracao: {
    base: string; receita_total: number; top1_pct: number | null; top3_pct: number | null; top5_pct: number | null; parcial?: boolean;
    clinicas: Array<{ clinica_id: number | null; clinica_nome: string; ativa: boolean | null; regiao: string | null; receita: number; participacao_pct: number | null; quantidade_os: number }>;
    evolucao: Array<{ mes: string; clinica_id: number | null; clinica_nome: string; receita: number; participacao_pct: number | null }>;
    lacunas: string[];
  };
  caixa: {
    saldo_inicial: number | null; saldo_final: number | null; entradas_confirmadas: number; entradas_previstas: number;
    saidas_confirmadas: number; saidas_previstas: number; entradas_premissas?: number; saidas_premissas?: number; pendencias_sem_data?: number; total_registros?: number; detalhes_limitados?: boolean; parcial: boolean; semanas: LinhaCaixa[]; meses: LinhaCaixa[];
    detalhes: Array<{ fonte: string; id: number | string; descricao?: string | null; os_id?: number; clinica_id: number | null; data: string; tipo: string; valor: number; natureza: "confirmado" | "previsto" | "premissa" }>;
    lacunas: string[]; formula: string;
  };
  ocupacao: {
    capacidade_minutos: number; agendados_minutos: number; agendados_totais_minutos: number; realizados_minutos: number;
    livres_minutos: number | null; taxa_agendada_pct: number | null; taxa_realizada_pct: number | null;
    base: string; formula: string; parcial: boolean; lacunas: string[]; limites: string[];
    dias: Array<{ data: string; capacidade_minutos: number; bloqueados_minutos: number; agendados_minutos: number; agendados_totais_minutos: number; realizados_minutos: number; livres_minutos: number | null; janelas_livres: Array<{ inicio: string; fim: string }>; regioes_presentes: string[]; motivo_fechado: string | null }>;
    por_regiao: Array<{ regiao: string; agendados_minutos: number; realizados_minutos: number }>;
    registros: Array<{ incluido_populacao_cancelamentos?: boolean; agendamento_id: number; data: string; inicio: string | null; fim: string | null; status: string; clinica_id: number | null; clinica_nome: string; regiao: string | null; duracao_minutos: number | null }>;
  };
  cancelamentos: {
    total_agendamentos: number; total_cancelados: number; taxa_pct: number | null;
    por_status: Array<{ status: string; quantidade: number }>;
    por_clinica: Array<{ clinica_id: number | null; clinica_nome: string; total_agendamentos: number; total_cancelados: number; taxa_pct: number | null }>;
    por_regiao: Array<{ regiao: string; total_agendamentos: number; total_cancelados: number; taxa_pct: number | null }>;
    motivos: string[]; reativados_identificados: number; reagendados_identificados: number;
    base: string; formula: string; parcial: boolean; lacunas: string[];
  };
};

export type PainelGestao = {
  atualizado_em: string;
  periodo: { inicio: string; fim: string; anterior_inicio: string; anterior_fim: string };
  filtros: { clinicas: Array<{ id: number; nome: string; ativo: boolean }>; regioes: string[] };
  atual: MetricasGestao;
  anterior: MetricasGestao;
  comparacao?: string;
  premissas_aplicadas?: PremissasGestao;
};

export function premissasVazias(): PremissasGestao {
  return { tributos_percentual: null, taxas_percentual: null, repasses_percentual: null, custos_variaveis: null, horas_atendimento: null, horas_laudos: null, horas_deslocamento: null, saldo_inicial: null, despesas_completas: false, movimentos: [] };
}

export function mesmoContexto(a: ContextoGestao | null | undefined, b: ContextoGestao): boolean {
  return Boolean(a && a.data_inicio === b.data_inicio && a.data_fim === b.data_fim && a.clinica_id === b.clinica_id && a.regiao === b.regiao);
}

export function premissasDoContexto(salvas: PremissasSalvas | null, contexto: ContextoGestao): PremissasGestao {
  return mesmoContexto(salvas?.contexto, contexto) ? { ...premissasVazias(), ...salvas?.values } : premissasVazias();
}
