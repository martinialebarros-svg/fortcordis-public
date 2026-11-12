from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Float,
    Enum,
    Boolean,
    UniqueConstraint,
    Index,
)
from sqlalchemy.sql import func
from app.db.database import Base
import enum

class TipoTransacao(str, enum.Enum):
    ENTRADA = "entrada"
    SAIDA = "saida"

class FormaPagamento(str, enum.Enum):
    DINHEIRO = "dinheiro"
    CARTAO_CREDITO = "cartao_credito"
    CARTAO_DEBITO = "cartao_debito"
    PIX = "pix"
    BOLETO = "boleto"
    TRANSFERENCIA = "transferencia"

class CategoriaTransacao(str, enum.Enum):
    CONSULTA = "consulta"
    EXAME = "exame"
    CIRURGIA = "cirurgia"
    MEDICAMENTO = "medicamento"
    BANHO_TOSA = "banho_tosa"
    PRODUTO = "produto"
    OUTROS = "outros"
    # Despesas
    SALARIO = "salario"
    ALUGUEL = "aluguel"
    FORNECEDOR = "fornecedor"
    IMPOSTO = "imposto"
    MANUTENCAO = "manutencao"
    MARKETING = "marketing"

class Transacao(Base):
    __tablename__ = "transacoes"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Tipo: entrada ou saída
    tipo = Column(String, nullable=False)  # entrada, saida
    
    # Categoria
    categoria = Column(String, nullable=False)
    
    # Valores
    valor = Column(Float, nullable=False)
    desconto = Column(Float, default=0)
    valor_final = Column(Float, nullable=False)
    
    # Forma de pagamento
    forma_pagamento = Column(String)
    forma_pagamento_config_id = Column(Integer, nullable=True)
    adquirente_pagamento = Column(String, nullable=True)
    bandeira_pagamento = Column(String, nullable=True)
    taxa_percentual = Column(Float, nullable=False, default=0)
    taxa_fixa = Column(Float, nullable=False, default=0)
    valor_taxa = Column(Float, nullable=False, default=0)
    
    # Status
    status = Column(String, default='Pendente')  # Pendente, Pago, Cancelado
    
    # Relacionamentos (opcionais)
    paciente_id = Column(Integer)
    paciente_nome = Column(String)
    agendamento_id = Column(Integer)

    # Centro de custos (Feature Flag: feature_centro_custos)
    clinica_id = Column(Integer, nullable=True)
    
    # Descrição
    descricao = Column(Text)
    
    # Datas
    data_transacao = Column(DateTime(timezone=True), default=func.now())
    data_vencimento = Column(DateTime(timezone=True))
    data_pagamento = Column(DateTime(timezone=True))
    
    # Parcelas (para cartão)
    parcelas = Column(Integer, default=1)
    parcela_atual = Column(Integer, default=1)
    
    # Observações
    observacoes = Column(Text)
    
    # Auditoria
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer)
    criado_por_nome = Column(String)


class BandeiraCartao(Base):
    __tablename__ = "bandeiras_cartao"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), nullable=False)
    codigo = Column(String(80), unique=True, index=True)
    ativo = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer, nullable=True)
    criado_por_nome = Column(String, nullable=True)


class FormaPagamentoConfiguracao(Base):
    __tablename__ = "formas_pagamento_config"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_formas_pagamento_codigo"),
    )

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(140), nullable=False)
    codigo = Column(String(80), nullable=False, index=True)
    tipo = Column(String(40), nullable=False)  # dinheiro, pix, cartao_credito, ...
    adquirente = Column(String(120), nullable=True)  # Mercado Pago, TON, etc.
    bandeira_id = Column(Integer, nullable=True)
    taxa_percentual = Column(Float, nullable=False, default=0)
    taxa_fixa = Column(Float, nullable=False, default=0)
    ativo = Column(Boolean, nullable=False, default=True)
    ordem_exibicao = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer, nullable=True)
    criado_por_nome = Column(String, nullable=True)


class OrdemServicoPagamento(Base):
    __tablename__ = "ordens_servico_pagamentos"
    __table_args__ = (
        Index("ix_os_pagamentos_os_data", "ordem_servico_id", "data_recebimento"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ordem_servico_id = Column(Integer, nullable=False, index=True)
    transacao_id = Column(Integer, nullable=True, index=True)

    forma_pagamento_config_id = Column(Integer, nullable=True)
    forma_pagamento_codigo = Column(String(80), nullable=False)
    forma_pagamento_nome = Column(String(140), nullable=False)
    adquirente = Column(String(120), nullable=True)
    bandeira_nome = Column(String(120), nullable=True)

    valor_bruto = Column(Float, nullable=False)
    taxa_percentual_aplicada = Column(Float, nullable=False, default=0)
    taxa_fixa_aplicada = Column(Float, nullable=False, default=0)
    valor_taxa = Column(Float, nullable=False, default=0)
    valor_liquido = Column(Float, nullable=False)

    data_recebimento = Column(DateTime(timezone=True), nullable=False)
    observacoes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer, nullable=True)
    criado_por_nome = Column(String, nullable=True)


class CreditoFinanceiro(Base):
    __tablename__ = "creditos_financeiros"
    __table_args__ = (
        Index("ix_creditos_financeiros_destino_data", "tipo_destino", "data_movimento"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tipo_destino = Column(String(20), nullable=False)  # cliente | clinica
    clinica_id = Column(Integer, nullable=True, index=True)
    paciente_id = Column(Integer, nullable=True, index=True)
    tutor_id = Column(Integer, nullable=True, index=True)

    valor = Column(Float, nullable=False)  # positivo para credito gerado, negativo para consumo
    status = Column(String(20), nullable=False, default="Ativo")  # Ativo | Cancelado
    origem = Column(String(40), nullable=False, default="manual")
    descricao = Column(Text, nullable=True)

    ordem_servico_id = Column(Integer, nullable=True, index=True)
    transacao_id = Column(Integer, nullable=True, index=True)
    data_movimento = Column(DateTime(timezone=True), nullable=False, default=func.now())

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer, nullable=True)
    criado_por_nome = Column(String, nullable=True)

class ContaPagar(Base):
    __tablename__ = "contas_pagar"
    
    id = Column(Integer, primary_key=True, index=True)
    
    descricao = Column(String, nullable=False)
    fornecedor = Column(String)
    categoria = Column(String)
    
    valor = Column(Float, nullable=False)
    
    # Datas
    data_vencimento = Column(DateTime(timezone=True), nullable=False)
    data_pagamento = Column(DateTime(timezone=True))
    
    # Status
    status = Column(String, default='Pendente')  # Pendente, Pago, Atrasado
    
    # Observações
    observacoes = Column(Text)
    
    # Auditoria
    created_at = Column(DateTime(timezone=True), default=func.now())
    criado_por_id = Column(Integer)

    # Centro de custos (Feature Flag: feature_centro_custos)
    clinica_id = Column(Integer, nullable=True)

class ContaReceber(Base):
    __tablename__ = "contas_receber"
    
    id = Column(Integer, primary_key=True, index=True)
    
    descricao = Column(String, nullable=False)
    cliente = Column(String)
    categoria = Column(String)
    
    valor = Column(Float, nullable=False)
    
    # Datas
    data_vencimento = Column(DateTime(timezone=True), nullable=False)
    data_recebimento = Column(DateTime(timezone=True))
    
    # Status
    status = Column(String, default='Pendente')  # Pendente, Recebido, Atrasado
    
    # Relacionamentos
    paciente_id = Column(Integer)
    agendamento_id = Column(Integer)

    # Observações
    observacoes = Column(Text)

    # Auditoria
    created_at = Column(DateTime(timezone=True), default=func.now())
    criado_por_id = Column(Integer)

    # Centro de custos (Feature Flag: feature_centro_custos)
    clinica_id = Column(Integer, nullable=True)


class CustoFrota(Base):
    __tablename__ = "custos_frota"

    id = Column(Integer, primary_key=True, index=True)

    # Data de competencia/lancamento
    data_referencia = Column(DateTime(timezone=True), nullable=False, default=func.now())

    # Categoria do custo
    categoria = Column(String, nullable=False)  # combustivel, pedagio, manutencao, seguro...

    # Valor total do lancamento
    valor = Column(Float, nullable=False)

    # Regra de rateio quando nao houver clinica vinculada
    forma_rateio = Column(String, nullable=False, default="por_km")  # por_km, por_atendimento, fixo_mensal, hibrido

    # Base opcional do lancamento (ex.: litros, km, numero de atendimentos)
    km_referencia = Column(Float, nullable=True)
    atendimentos_referencia = Column(Integer, nullable=True)

    # Vinculos opcionais
    clinica_id = Column(Integer, nullable=True)
    veiculo_id = Column(Integer, nullable=True)
    veiculo = Column(String, nullable=True)

    descricao = Column(Text, nullable=True)
    observacoes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer, nullable=True)
    criado_por_nome = Column(String, nullable=True)


class VeiculoFrota(Base):
    __tablename__ = "veiculos_frota"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    placa = Column(String, nullable=True)
    tipo_combustivel = Column(String, nullable=True)
    consumo_km_litro = Column(Float, nullable=True)

    valor_aquisicao = Column(Float, nullable=True)
    valor_residual = Column(Float, nullable=True)
    vida_util_meses = Column(Integer, nullable=True)

    ativo = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer, nullable=True)
    criado_por_nome = Column(String, nullable=True)


class TelemetriaFrotaMensal(Base):
    __tablename__ = "telemetria_frota_mensal"
    __table_args__ = (
        UniqueConstraint("veiculo_id", "competencia", name="uq_telemetria_frota_veiculo_competencia"),
    )

    id = Column(Integer, primary_key=True, index=True)
    veiculo_id = Column(Integer, nullable=False)
    competencia = Column(String(7), nullable=False)  # YYYY-MM

    km_inicial = Column(Float, nullable=True)
    km_final = Column(Float, nullable=True)
    km_rodado = Column(Float, nullable=True)

    litros_consumidos = Column(Float, nullable=True)
    valor_combustivel = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer, nullable=True)
    criado_por_nome = Column(String, nullable=True)


class ConfigRateioFrota(Base):
    __tablename__ = "config_rateio_frota"

    id = Column(Integer, primary_key=True, index=True)
    peso_km = Column(Float, nullable=False, default=0.7)
    peso_atendimento = Column(Float, nullable=False, default=0.3)
    auto_gerar_depreciacao = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer, nullable=True)
    criado_por_nome = Column(String, nullable=True)
