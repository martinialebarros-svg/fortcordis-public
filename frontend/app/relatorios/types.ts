export type PerfilDeslocamento = "comercial" | "plantao";

export type DominioRelatorio =
  | "visao-geral"
  | "operacao"
  | "logistica"
  | "financeiro"
  | "rentabilidade";

export type SecaoExport =
  | "resumo"
  | "logistica"
  | "producao"
  | "financeiro"
  | "rentabilidade"
  | "alertas"
  | "insights"
  | "sugestoes";

export interface FiltrosRelatorio {
  data_inicio: string;
  data_fim: string;
  data_referencia: string;
  perfil_deslocamento: PerfilDeslocamento;
  clinica_base_id?: number;
  clinica_id?: number;
  servico_id?: number;
  profissional_id?: number;
  regiao?: string;
}

export interface ClinicaOption {
  id: number;
  nome: string;
  regiao_operacional?: string | null;
  bairro?: string | null;
  cidade?: string | null;
  estado?: string | null;
}

export interface ServicoOption {
  id: number;
  nome: string;
}

export interface ProfissionalOption {
  id: number;
  nome: string;
  email?: string | null;
}

export interface KmProjetadoDia {
  data: string;
  agendamentos: number;
  trechos: number;
  trechos_estimados: number;
  km_total: number;
  duracao_total_min: number;
}

export interface KmMesItem {
  mes: string;
  km_total: number;
  duracao_total_min: number;
  trechos: number;
  dias_com_rota: number;
  agendamentos: number;
}

export interface RotaLongaItem {
  origem_clinica_id: number;
  origem_nome: string;
  destino_clinica_id: number;
  destino_nome: string;
  distancia_km: number;
  duracao_min: number;
  fonte: string;
}

export interface ClinicaDistanteItem {
  clinica_id: number;
  clinica_nome: string;
  distancia_km: number;
  duracao_min: number;
  fonte: string;
}

export interface ClinicaAgendaItem {
  clinica_id: number;
  clinica_nome: string;
  agendamentos: number;
  realizados: number;
  cancelados: number;
  faltou: number;
  taxa_realizacao_percent: number;
}

export interface ServicoSolicitadoItem {
  servico_id: number;
  servico_nome: string;
  agendamentos: number;
  realizados: number;
  taxa_realizacao_percent: number;
}

export interface ClinicaFaturamentoItem {
  clinica_id: number;
  clinica_nome: string;
  valor_total: number;
  servicos: number;
}

export interface SugestaoRelatorioItem {
  codigo: string;
  titulo: string;
  descricao: string;
}

export interface RentabilidadeClinicaItem {
  clinica_id: number;
  clinica_nome: string;
  agendamentos: number;
  realizados: number;
  cancelados: number;
  faltou: number;
  taxa_realizacao_percent: number;
  taxa_cancelamento_percent: number;
  taxa_falta_percent: number;
  valor_total_servicos: number;
  quantidade_servicos: number;
  distancia_km_base: number;
  duracao_min_base: number;
  distancia_fonte: string;
  km_estimado_operacao: number;
  retorno_por_km: number | null;
  indice_rentabilidade: number;
  despesa_transacoes?: number;
  despesa_frota?: number;
  despesa_total?: number;
  lucro_liquido?: number;
  margem_percent?: number;
  metodologia?: "real" | "proxy_operacional" | string;
}

export interface AlertaOperacionalItem {
  codigo: string;
  severidade: "alto" | "medio" | "baixo" | string;
  titulo: string;
  descricao: string;
  recomendacao: string;
  clinica_id: number | null;
}

export interface OciosidadeJanelaItem {
  hora_inicio: string;
  hora_fim: string;
  agendamentos_total: number;
  media_agendamentos_dia: number;
  indice_ociosidade_percent: number;
}

export interface AntecedenciaClinicaItem {
  clinica_id: number;
  clinica_nome: string;
  media_dias: number;
  amostras: number;
}

export interface PontualidadeCriticaItem {
  data: string;
  origem_clinica_id: number;
  origem_nome: string;
  destino_clinica_id: number;
  destino_nome: string;
  folga_min: number;
  deslocamento_estimado_min: number;
  deficit_min: number;
}

export interface MixServicoClinicaItem {
  clinica_id: number;
  clinica_nome: string;
  total_agendamentos: number;
  servico_principal_id: number;
  servico_principal_nome: string;
  servico_principal_quantidade: number;
  servico_principal_participacao_percent: number;
  servicos_distintos: number;
}

export interface PrevisaoRecebimentoItem {
  clinica_id: number;
  clinica_nome: string;
  valor_previsto: number;
  ordens_pendentes: number;
}

export interface PendenciaRecebimentoItem {
  clinica_id: number;
  clinica_nome: string;
  valor_pendente: number;
  ordens_pendentes: number;
}

export interface RelatorioControleResponse {
  periodo: {
    data_inicio: string;
    data_fim: string;
    data_referencia: string;
    dias: number;
  };
  parametros: {
    perfil_deslocamento: string;
    clinica_base_id_solicitada: number | null;
    clinica_id?: number | null;
    servico_id?: number | null;
    profissional_id?: number | null;
    regiao?: string | null;
  };
  base_operacional: {
    clinica_id: number | null;
    clinica_nome: string | null;
    criterio: string;
  };
  logistica: {
    km_projetado_dia: KmProjetadoDia;
    km_por_mes: KmMesItem[];
    rotas_mais_longas: RotaLongaItem[];
    clinicas_mais_distantes_base: ClinicaDistanteItem[];
  };
  producao: {
    clinicas_mais_agendam: ClinicaAgendaItem[];
    servicos_mais_solicitados: ServicoSolicitadoItem[];
    total_agendamentos: number;
    realizados: number;
    cancelados: number;
    faltas: number;
    taxa_realizacao_percent: number;
    taxa_cancelamento_percent: number;
    taxa_falta_percent: number;
  };
  financeiro: {
    periodo: {
      entradas_recebidas: number;
      saidas_pagas: number;
      saldo: number;
      taxas_pagamento: number;
      creditos_gerados: number;
      valor_total_servicos: number;
      quantidade_servicos: number;
    };
    mes_referencia: {
      mes: string;
      ate_data_referencia: string;
      entradas_recebidas: number;
      saidas_pagas: number;
      saldo: number;
      taxas_pagamento: number;
      creditos_gerados: number;
      valor_total_servicos_realizados: number;
      quantidade_servicos_realizados: number;
      ticket_medio_servico: number;
      km_estimado_mes: number;
      retorno_por_km: number | null;
    };
    clinicas_maior_faturamento: ClinicaFaturamentoItem[];
  };
  indicadores_extras: {
    retorno_por_km_mes_referencia: number | null;
    taxa_realizacao_percent: number;
    taxa_cancelamento_percent: number;
    taxa_falta_percent: number;
  };
  rentabilidade: {
    metodologia?: "real" | "proxy_operacional" | string;
    mensagem_metodologia?: string;
    dados_necessarios_para_real?: string[];
    pendencias_para_real?: string[];
    cobertura_real?: {
      clinicas_com_receita: number;
      clinicas_com_despesa_vinculada: number;
      clinicas_sem_despesa_vinculada: number;
      despesas_sem_clinica: number;
      custos_frota_total?: number;
      custos_frota_nao_alocados?: number;
      cobertura_percent: number;
    };
    custos_frota?: {
      total_periodo: number;
      alocado_por_km: number;
      alocado_por_atendimento: number;
      alocado_fixo: number;
      diretos_por_clinica: number;
      nao_alocados: number;
      total_itens: number;
    };
    ranking_clinicas: RentabilidadeClinicaItem[];
  };
  alertas_operacionais: AlertaOperacionalItem[];
  insights_avancados: {
    ociosidade_janela_horario: OciosidadeJanelaItem[];
    antecedencia_agendamento: {
      media_dias: number | null;
      mediana_dias: number | null;
      amostras: number;
      por_clinica: AntecedenciaClinicaItem[];
    };
    pontualidade_atrasos: {
      total_transicoes: number;
      transicoes_com_risco: number;
      taxa_risco_percent: number;
      transicoes_criticas: PontualidadeCriticaItem[];
    };
    mix_servicos_por_clinica: MixServicoClinicaItem[];
    previsao_recebimentos_30d: {
      data_referencia: string;
      data_limite: string;
      valor_total_previsto: number;
      itens: PrevisaoRecebimentoItem[];
    };
    pendencias_recebimento?: {
      data_corte: string;
      valor_total_pendente: number;
      itens: PendenciaRecebimentoItem[];
    };
  };
  sugestoes_relatorios: SugestaoRelatorioItem[];
}

export interface DreLinha {
  categoria: string;
  valor: number;
}

export interface DreResponse {
  periodo: string;
  data_inicio: string;
  data_fim: string;
  receita_bruta: number;
  receita_liquida: number;
  custos: DreLinha[];
  total_custos: number;
  lucro_bruto: number;
  margem_bruta: number;
  despesas_operacionais: DreLinha[];
  total_despesas_operacionais: number;
  lucro_operacional: number;
  margem_operacional: number;
  outras_despesas: DreLinha[];
  total_outras_despesas: number;
  lucro_liquido: number;
  margem_liquida: number;
}

export interface FluxoCaixaItem {
  data: string;
  entradas: number;
  saidas: number;
  saldo_dia: number;
  saldo_acumulado: number;
}

export interface FluxoCaixaResponse {
  data_inicio: string;
  data_fim: string;
  saldo_inicial: number;
  total_entradas: number;
  total_saidas: number;
  saldo_final: number;
  items: FluxoCaixaItem[];
}

export interface CategoriaResumo {
  categoria: string;
  total: number;
  quantidade: number;
  percentual: number;
}

export interface RelatorioCategoriaResponse {
  tipo: "entrada" | "saida";
  periodo: string;
  total: number;
  categorias: CategoriaResumo[];
}

export interface ComparativoMensalItem {
  mes: string;
  ano: number;
  entradas: number;
  saidas: number;
  saldo: number;
  variacao_entrada?: number;
  variacao_saida?: number;
}

export interface RelatorioComparativoResponse {
  items: ComparativoMensalItem[];
}

export interface ContaFinanceiraItem {
  id: number;
  descricao?: string | null;
  categoria?: string | null;
  valor: number;
  status: string;
  data_vencimento?: string | null;
  data_pagamento?: string | null;
  clinica_id?: number | null;
}

export interface ContaFinanceiraResponse {
  total: number;
  items: ContaFinanceiraItem[];
}

export interface FinanceiroContextoResponse {
  dre: DreResponse | null;
  fluxo_caixa: FluxoCaixaResponse | null;
  despesas_por_categoria: RelatorioCategoriaResponse | null;
  comparativo_mensal: RelatorioComparativoResponse | null;
  contas_receber: ContaFinanceiraResponse | null;
  contas_pagar: ContaFinanceiraResponse | null;
}
