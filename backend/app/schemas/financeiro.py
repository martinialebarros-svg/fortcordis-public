from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import Optional, List
from decimal import Decimal
from uuid import UUID


# ==================== TRANSAÇÕES ====================

class TransacaoBase(BaseModel):
    tipo: str = Field(..., pattern="^(entrada|saida)$", description="Tipo: entrada ou saida")
    categoria: str = Field(..., description="Categoria da transação")
    valor: float = Field(..., gt=0, description="Valor da transação")
    desconto: float = Field(default=0, ge=0, description="Desconto aplicado")
    forma_pagamento: Optional[str] = Field(default=None, description="Forma de pagamento")
    forma_pagamento_config_id: Optional[int] = Field(default=None, description="ID do cadastro de forma de pagamento")
    adquirente_pagamento: Optional[str] = Field(default=None, description="Adquirente/maquininha")
    bandeira_pagamento: Optional[str] = Field(default=None, description="Bandeira do cartao")
    taxa_percentual: float = Field(default=0, ge=0, description="Taxa percentual aplicada")
    taxa_fixa: float = Field(default=0, ge=0, description="Taxa fixa aplicada")
    valor_taxa: float = Field(default=0, ge=0, description="Valor monetario da taxa")
    status: str = Field(default="Pendente", description="Status: Pendente, Pago, Recebido, Cancelado")
    descricao: str = Field(..., min_length=3, max_length=255, description="Descrição da transação")
    data_transacao: datetime = Field(default_factory=datetime.now, description="Data da transação")
    data_vencimento: Optional[datetime] = Field(default=None, description="Data de vencimento")
    observacoes: Optional[str] = Field(default=None, description="Observações adicionais")

    # Relacionamentos opcionais
    paciente_id: Optional[int] = Field(default=None, description="ID do paciente")
    paciente_nome: Optional[str] = Field(default=None, description="Nome do paciente")
    agendamento_id: Optional[int] = Field(default=None, description="ID do agendamento")

    # Parcelas
    parcelas: int = Field(default=1, ge=1, description="Número de parcelas")
    parcela_atual: int = Field(default=1, ge=1, description="Parcela atual")

    # Centro de custos (Feature Flag: feature_centro_custos)
    clinica_id: Optional[int] = Field(default=None, description="ID da clínica (centro de custo)")


class TransacaoCreate(TransacaoBase):
    pass


class TransacaoUpdate(BaseModel):
    tipo: Optional[str] = Field(default=None, pattern="^(entrada|saida)$")
    categoria: Optional[str] = None
    valor: Optional[float] = Field(default=None, gt=0)
    desconto: Optional[float] = Field(default=None, ge=0)
    forma_pagamento: Optional[str] = None
    forma_pagamento_config_id: Optional[int] = None
    adquirente_pagamento: Optional[str] = None
    bandeira_pagamento: Optional[str] = None
    taxa_percentual: Optional[float] = Field(default=None, ge=0)
    taxa_fixa: Optional[float] = Field(default=None, ge=0)
    valor_taxa: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None
    descricao: Optional[str] = Field(default=None, min_length=3, max_length=255)
    data_transacao: Optional[datetime] = None
    data_vencimento: Optional[datetime] = None
    data_pagamento: Optional[datetime] = None
    observacoes: Optional[str] = None
    paciente_id: Optional[int] = None
    paciente_nome: Optional[str] = None
    agendamento_id: Optional[int] = None
    parcelas: Optional[int] = Field(default=None, ge=1)
    parcela_atual: Optional[int] = Field(default=None, ge=1)
    clinica_id: Optional[int] = Field(default=None, description="ID da clínica (centro de custo)")


class TransacaoResponse(BaseModel):
    id: int
    tipo: str
    categoria: str
    valor: float
    desconto: float
    valor_final: float
    forma_pagamento: Optional[str]
    forma_pagamento_config_id: Optional[int]
    adquirente_pagamento: Optional[str]
    bandeira_pagamento: Optional[str]
    taxa_percentual: float
    taxa_fixa: float
    valor_taxa: float
    status: str
    descricao: str
    data_transacao: datetime
    data_vencimento: Optional[datetime]
    data_pagamento: Optional[datetime]
    observacoes: Optional[str]
    paciente_id: Optional[int]
    paciente_nome: Optional[str]
    agendamento_id: Optional[int]
    parcelas: int
    parcela_atual: int
    clinica_id: Optional[int]
    criado_por_id: Optional[int]
    criado_por_nome: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TransacaoLista(BaseModel):
    total: int
    items: List[TransacaoResponse]


class BandeiraCartaoBase(BaseModel):
    nome: str = Field(..., min_length=2, max_length=120)
    codigo: str = Field(..., min_length=2, max_length=80)
    ativo: bool = True


class BandeiraCartaoCreate(BandeiraCartaoBase):
    pass


class BandeiraCartaoUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2, max_length=120)
    codigo: Optional[str] = Field(default=None, min_length=2, max_length=80)
    ativo: Optional[bool] = None


class BandeiraCartaoResponse(BaseModel):
    id: int
    nome: str
    codigo: str
    ativo: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class BandeiraCartaoLista(BaseModel):
    total: int
    items: List[BandeiraCartaoResponse]


class FormaPagamentoConfigBase(BaseModel):
    nome: str = Field(..., min_length=2, max_length=140)
    codigo: str = Field(..., min_length=2, max_length=80)
    tipo: str = Field(
        ...,
        pattern="^(dinheiro|pix|cartao_credito|cartao_debito|boleto|transferencia|credito|outro)$",
    )
    adquirente: Optional[str] = Field(default=None, max_length=120)
    bandeira_id: Optional[int] = None
    taxa_percentual: float = Field(default=0, ge=0)
    taxa_fixa: float = Field(default=0, ge=0)
    ativo: bool = True
    ordem_exibicao: int = Field(default=0, ge=0)


class FormaPagamentoConfigCreate(FormaPagamentoConfigBase):
    pass


class FormaPagamentoConfigUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2, max_length=140)
    codigo: Optional[str] = Field(default=None, min_length=2, max_length=80)
    tipo: Optional[str] = Field(
        default=None,
        pattern="^(dinheiro|pix|cartao_credito|cartao_debito|boleto|transferencia|credito|outro)$",
    )
    adquirente: Optional[str] = Field(default=None, max_length=120)
    bandeira_id: Optional[int] = None
    taxa_percentual: Optional[float] = Field(default=None, ge=0)
    taxa_fixa: Optional[float] = Field(default=None, ge=0)
    ativo: Optional[bool] = None
    ordem_exibicao: Optional[int] = Field(default=None, ge=0)


class FormaPagamentoConfigResponse(BaseModel):
    id: int
    nome: str
    codigo: str
    tipo: str
    adquirente: Optional[str]
    bandeira_id: Optional[int]
    bandeira_nome: Optional[str] = None
    taxa_percentual: float
    taxa_fixa: float
    ativo: bool
    ordem_exibicao: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class FormaPagamentoConfigLista(BaseModel):
    total: int
    items: List[FormaPagamentoConfigResponse]


class CreditoBaixaInput(BaseModel):
    tipo_destino: str = Field(..., pattern="^(cliente|clinica)$")
    paciente_id: Optional[int] = Field(default=None, ge=1)
    clinica_id: Optional[int] = Field(default=None, ge=1)
    valor: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    motivo: str = Field(..., min_length=3, max_length=500)
    idempotency_key: UUID


class CreditoFinanceiroResponse(BaseModel):
    id: int
    tipo_destino: str
    clinica_id: Optional[int]
    paciente_id: Optional[int]
    tutor_id: Optional[int]
    valor: float
    status: str
    origem: str
    descricao: Optional[str]
    ordem_servico_id: Optional[int]
    transacao_id: Optional[int]
    data_movimento: datetime
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class CreditoFinanceiroLista(BaseModel):
    total: int
    items: List[CreditoFinanceiroResponse]


class CreditoSaldoItem(BaseModel):
    tipo_destino: str
    clinica_id: Optional[int] = None
    paciente_id: Optional[int] = None
    tutor_id: Optional[int] = None
    saldo: float


class CreditoSaldoLista(BaseModel):
    total: int
    items: List[CreditoSaldoItem]


# ==================== CONTAS A PAGAR ====================

class ContaPagarBase(BaseModel):
    descricao: str = Field(..., min_length=3, max_length=255)
    fornecedor: Optional[str] = Field(default=None, max_length=255)
    categoria: Optional[str] = None
    valor: float = Field(..., gt=0)
    data_vencimento: datetime = Field(..., description="Data de vencimento")
    observacoes: Optional[str] = None
    clinica_id: Optional[int] = Field(default=None, description="ID da clínica (centro de custo)")


class ContaPagarCreate(ContaPagarBase):
    pass


class ContaPagarUpdate(BaseModel):
    descricao: Optional[str] = Field(default=None, min_length=3, max_length=255)
    fornecedor: Optional[str] = None
    categoria: Optional[str] = None
    valor: Optional[float] = Field(default=None, gt=0)
    data_vencimento: Optional[datetime] = None
    data_pagamento: Optional[datetime] = None
    status: Optional[str] = None
    observacoes: Optional[str] = None
    clinica_id: Optional[int] = Field(default=None, description="ID da clínica (centro de custo)")


class ContaPagarResponse(BaseModel):
    id: int
    descricao: str
    fornecedor: Optional[str]
    categoria: Optional[str]
    valor: float
    data_vencimento: datetime
    data_pagamento: Optional[datetime]
    status: str
    observacoes: Optional[str]
    clinica_id: Optional[int]
    criado_por_id: Optional[int]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class ContaPagarLista(BaseModel):
    total: int
    items: List[ContaPagarResponse]


# ==================== CONTAS A RECEBER ====================

class ContaReceberBase(BaseModel):
    descricao: str = Field(..., min_length=3, max_length=255)
    cliente: Optional[str] = Field(default=None, max_length=255)
    categoria: Optional[str] = None
    valor: float = Field(..., gt=0)
    data_vencimento: datetime = Field(..., description="Data de vencimento")
    observacoes: Optional[str] = None
    paciente_id: Optional[int] = None
    agendamento_id: Optional[int] = None
    clinica_id: Optional[int] = Field(default=None, description="ID da clínica (centro de custo)")


class ContaReceberCreate(ContaReceberBase):
    pass


class ContaReceberUpdate(BaseModel):
    descricao: Optional[str] = Field(default=None, min_length=3, max_length=255)
    cliente: Optional[str] = None
    categoria: Optional[str] = None
    valor: Optional[float] = Field(default=None, gt=0)
    data_vencimento: Optional[datetime] = None
    data_recebimento: Optional[datetime] = None
    status: Optional[str] = None
    observacoes: Optional[str] = None
    paciente_id: Optional[int] = None
    agendamento_id: Optional[int] = None
    clinica_id: Optional[int] = Field(default=None, description="ID da clínica (centro de custo)")


class ContaReceberResponse(BaseModel):
    id: int
    descricao: str
    cliente: Optional[str]
    categoria: Optional[str]
    valor: float
    data_vencimento: datetime
    data_recebimento: Optional[datetime]
    status: str
    observacoes: Optional[str]
    paciente_id: Optional[int]
    agendamento_id: Optional[int]
    clinica_id: Optional[int]
    criado_por_id: Optional[int]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class ContaReceberLista(BaseModel):
    total: int
    items: List[ContaReceberResponse]


# ==================== CUSTOS DE FROTA ====================

class CustoFrotaBase(BaseModel):
    data_referencia: datetime = Field(default_factory=datetime.now, description="Data de referencia do custo")
    categoria: str = Field(..., min_length=2, max_length=80, description="Categoria do custo de frota")
    valor: float = Field(..., gt=0, description="Valor do custo")
    forma_rateio: str = Field(
        default="por_km",
        pattern="^(por_km|por_atendimento|fixo_mensal|hibrido)$",
        description="Regra de rateio para custos sem clinica vinculada",
    )
    km_referencia: Optional[float] = Field(default=None, ge=0, description="KM de referencia do lancamento")
    atendimentos_referencia: Optional[int] = Field(
        default=None,
        ge=0,
        description="Quantidade de atendimentos de referencia do lancamento",
    )
    clinica_id: Optional[int] = Field(default=None, description="Clinica vinculada (opcional)")
    veiculo_id: Optional[int] = Field(default=None, description="Veiculo vinculado (opcional)")
    veiculo: Optional[str] = Field(default=None, max_length=120, description="Identificacao do veiculo")
    descricao: Optional[str] = Field(default=None, max_length=255, description="Descricao curta")
    observacoes: Optional[str] = Field(default=None, description="Observacoes")


class CustoFrotaCreate(CustoFrotaBase):
    pass


class CustoFrotaUpdate(BaseModel):
    data_referencia: Optional[datetime] = None
    categoria: Optional[str] = Field(default=None, min_length=2, max_length=80)
    valor: Optional[float] = Field(default=None, gt=0)
    forma_rateio: Optional[str] = Field(default=None, pattern="^(por_km|por_atendimento|fixo_mensal|hibrido)$")
    km_referencia: Optional[float] = Field(default=None, ge=0)
    atendimentos_referencia: Optional[int] = Field(default=None, ge=0)
    clinica_id: Optional[int] = None
    veiculo_id: Optional[int] = None
    veiculo: Optional[str] = Field(default=None, max_length=120)
    descricao: Optional[str] = Field(default=None, max_length=255)
    observacoes: Optional[str] = None


class CustoFrotaResponse(BaseModel):
    id: int
    data_referencia: datetime
    categoria: str
    valor: float
    forma_rateio: str
    km_referencia: Optional[float]
    atendimentos_referencia: Optional[int]
    clinica_id: Optional[int]
    veiculo_id: Optional[int]
    veiculo: Optional[str]
    descricao: Optional[str]
    observacoes: Optional[str]
    criado_por_id: Optional[int]
    criado_por_nome: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class CustoFrotaLista(BaseModel):
    total: int
    items: List[CustoFrotaResponse]


# ==================== RELATÓRIOS ====================

class ResumoFinanceiro(BaseModel):
    periodo: str
    data_inicio: str
    data_fim: str
    entradas: float
    saidas: float
    saldo: float
    pendente_entrada: float
    pendente_saida: float
    a_receber: float
    a_pagar: float
    taxas_pagamento: float = 0
    creditos_gerados: float = 0


class DadosGrafico(BaseModel):
    labels: List[str]
    entradas: List[float]
    saidas: List[float]


class CategoriaResumo(BaseModel):
    categoria: str
    total: float
    quantidade: int
    percentual: float


class RelatorioCategoria(BaseModel):
    tipo: str  # entrada ou saida
    periodo: str
    total: float
    categorias: List[CategoriaResumo]


class FluxoCaixaItem(BaseModel):
    data: str
    entradas: float
    saidas: float
    saldo_dia: float
    saldo_acumulado: float


class RelatorioFluxoCaixa(BaseModel):
    data_inicio: str
    data_fim: str
    saldo_inicial: float
    total_entradas: float
    total_saidas: float
    saldo_final: float
    items: List[FluxoCaixaItem]


class ComparativoMes(BaseModel):
    mes: str
    ano: int
    entradas: float
    saidas: float
    saldo: float
    variacao_entrada: Optional[float] = None
    variacao_saida: Optional[float] = None


class RelatorioComparativo(BaseModel):
    items: List[ComparativoMes]


class DREItem(BaseModel):
    categoria: str
    valor: float
    percentual_receita: float


class RelatorioDRE(BaseModel):
    """Demonstração do Resultado do Exercício"""
    periodo: str
    data_inicio: str
    data_fim: str
    
    # Receitas
    receita_bruta: float
    impostos: float
    receita_liquida: float
    
    # Custos e Despesas
    custos: List[DREItem]
    despesas_operacionais: List[DREItem]
    despesas_administrativas: List[DREItem]
    despesas_marketing: List[DREItem]
    
    total_custos: float
    total_despesas: float
    
    # Resultados
    lucro_bruto: float
    lucro_operacional: float
    margem_bruta: float
    margem_operacional: float


# ==================== FROTA V2 ====================

class VeiculoFrotaBase(BaseModel):
    nome: str = Field(..., min_length=2, max_length=120)
    placa: Optional[str] = Field(default=None, max_length=20)
    tipo_combustivel: Optional[str] = Field(default=None, max_length=40)
    consumo_km_litro: Optional[float] = Field(default=None, gt=0)
    valor_aquisicao: Optional[float] = Field(default=None, ge=0)
    valor_residual: Optional[float] = Field(default=None, ge=0)
    vida_util_meses: Optional[int] = Field(default=None, ge=1)
    ativo: bool = True


class VeiculoFrotaCreate(VeiculoFrotaBase):
    pass


class VeiculoFrotaUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2, max_length=120)
    placa: Optional[str] = Field(default=None, max_length=20)
    tipo_combustivel: Optional[str] = Field(default=None, max_length=40)
    consumo_km_litro: Optional[float] = Field(default=None, gt=0)
    valor_aquisicao: Optional[float] = Field(default=None, ge=0)
    valor_residual: Optional[float] = Field(default=None, ge=0)
    vida_util_meses: Optional[int] = Field(default=None, ge=1)
    ativo: Optional[bool] = None


class VeiculoFrotaResponse(BaseModel):
    id: int
    nome: str
    placa: Optional[str]
    tipo_combustivel: Optional[str]
    consumo_km_litro: Optional[float]
    valor_aquisicao: Optional[float]
    valor_residual: Optional[float]
    vida_util_meses: Optional[int]
    ativo: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class VeiculoFrotaLista(BaseModel):
    total: int
    items: List[VeiculoFrotaResponse]


class TelemetriaFrotaMensalBase(BaseModel):
    veiculo_id: int = Field(..., ge=1)
    competencia: str = Field(..., pattern="^\\d{4}-\\d{2}$", description="Formato YYYY-MM")
    km_inicial: Optional[float] = Field(default=None, ge=0)
    km_final: Optional[float] = Field(default=None, ge=0)
    km_rodado: Optional[float] = Field(default=None, ge=0)
    litros_consumidos: Optional[float] = Field(default=None, ge=0)
    valor_combustivel: Optional[float] = Field(default=None, ge=0)


class TelemetriaFrotaMensalCreate(TelemetriaFrotaMensalBase):
    pass


class TelemetriaFrotaMensalUpdate(BaseModel):
    competencia: Optional[str] = Field(default=None, pattern="^\\d{4}-\\d{2}$")
    km_inicial: Optional[float] = Field(default=None, ge=0)
    km_final: Optional[float] = Field(default=None, ge=0)
    km_rodado: Optional[float] = Field(default=None, ge=0)
    litros_consumidos: Optional[float] = Field(default=None, ge=0)
    valor_combustivel: Optional[float] = Field(default=None, ge=0)


class TelemetriaFrotaMensalResponse(BaseModel):
    id: int
    veiculo_id: int
    competencia: str
    km_inicial: Optional[float]
    km_final: Optional[float]
    km_rodado: Optional[float]
    litros_consumidos: Optional[float]
    valor_combustivel: Optional[float]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TelemetriaFrotaMensalLista(BaseModel):
    total: int
    items: List[TelemetriaFrotaMensalResponse]


class ConfigRateioFrotaBase(BaseModel):
    peso_km: float = Field(default=0.7, ge=0, le=1)
    peso_atendimento: float = Field(default=0.3, ge=0, le=1)
    auto_gerar_depreciacao: bool = False


class ConfigRateioFrotaUpdate(ConfigRateioFrotaBase):
    pass


class ConfigRateioFrotaResponse(BaseModel):
    id: int
    peso_km: float
    peso_atendimento: float
    auto_gerar_depreciacao: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
