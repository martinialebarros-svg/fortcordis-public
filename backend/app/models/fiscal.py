"""Modelo para o módulo fiscal (Notas Fiscais de Serviço)"""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, LargeBinary, String, Text, Numeric, Float, UniqueConstraint
from app.db.database import Base


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class NotaFiscal(Base):
    __tablename__ = "notas_fiscais"

    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String(50), unique=True)
    serie = Column(String(10), default="1")
    os_id = Column(Integer)

    # Tipo de cliente: PF (Pessoa Física) ou PJ (Pessoa Jurídica)
    tipo_cliente = Column(String(2))  # 'PF' ou 'PJ'

    # Dados do cliente/tomador
    cliente_nome = Column(Text)
    cliente_documento = Column(Text)  # CPF ou CNPJ
    cliente_endereco = Column(Text)
    cliente_bairro = Column(Text)
    cliente_cidade = Column(Text)
    cliente_estado = Column(Text)
    cliente_cep = Column(Text)
    cliente_telefone = Column(Text)
    cliente_email = Column(Text)

    # Valores
    valor_servico = Column(Numeric(12, 2), default=0)
    valor_desconto = Column(Numeric(12, 2), default=0)
    valor_final = Column(Numeric(12, 2), default=0)
    aliquota_iss = Column(Float, default=5.0)  # Percentual ISS (padrão 5%)
    valor_iss = Column(Numeric(12, 2), default=0)

    # Dados do serviço
    atividade_cnae = Column(Text)
    descricao_servico = Column(Text)
    observacoes = Column(Text)

    # Dados fiscais complementares
    natureza_operacao = Column(Text, default="Tributação no município")
    codigo_municipio = Column(Text)
    regime_tributario = Column(Integer)  # 1=MEI, 2=Simples, 3=Lucro Presumido, 4=Lucro Real

    # Status e exportação
    formato_exportado = Column(String(10))  # 'pdf', 'csv', 'xlsx'
    status = Column(String(20), default="rascunho")  # 'rascunho', 'exportado', 'cancelado'

    # Auditoria
    created_at = Column(Text, default=_now_str)
    updated_at = Column(Text)


class FiscalNumeroSequencia(Base):
    __tablename__ = "fiscal_numero_sequencias"

    ano = Column(Integer, primary_key=True)
    ultimo_numero = Column(Integer, nullable=False, default=0)
    updated_at = Column(Text, default=_now_str)


class RelatorioFiscalEmissao(Base):
    """Trilha de auditoria dos relatórios contábeis efetivamente exportados."""

    __tablename__ = "relatorios_fiscais_emissoes"

    id = Column(Integer, primary_key=True, index=True)
    formato = Column(String(10), nullable=False)
    modo = Column(String(20), nullable=False)
    tipo_emissao = Column(String(30), nullable=False, default="fechamento_periodo")
    data_inicio = Column(String(10))
    data_fim = Column(String(10))
    quantidade_os = Column(Integer, nullable=False, default=0)
    valor_total = Column(Numeric(12, 2), nullable=False, default=0)
    clinicas_json = Column(Text, nullable=False, default="[]")
    os_ids_json = Column(Text, nullable=False, default="[]")
    descricao_servico = Column(Text)
    arquivo_nome = Column(Text)
    usuario_id = Column(Integer)
    usuario_nome = Column(Text)
    emitido_em = Column(Text, nullable=False, default=_now_str)


class FiscalFechamento(Base):
    """Pacote informativo imutável preparado para o contador, sem emissão de NF."""

    __tablename__ = "fiscal_fechamentos"

    id = Column(Integer, primary_key=True)
    competencia = Column(String(7), nullable=False, index=True)
    chave_idempotencia = Column(String(36), nullable=False, unique=True)
    fingerprint = Column(String(64), nullable=False)
    data_inicio = Column(String(10), nullable=False)
    data_fim = Column(String(10), nullable=False)
    quantidade_os = Column(Integer, nullable=False)
    valor_total = Column(Numeric(12, 2), nullable=False)
    snapshot_json = Column(Text, nullable=False)
    arquivo_nome = Column(Text, nullable=False)
    pacote_bytes = Column(LargeBinary, nullable=False)
    checksum = Column(String(64), nullable=False)
    usuario_id = Column(Integer)
    usuario_nome = Column(Text)
    preparado_em = Column(Text, nullable=False)


class FiscalFechamentoOS(Base):
    """Uma OS pertence a um único pacote; segunda via reutiliza o pacote original."""

    __tablename__ = "fiscal_fechamentos_os"

    os_id = Column(Integer, primary_key=True)
    fechamento_id = Column(Integer, ForeignKey("fiscal_fechamentos.id"), nullable=False, index=True)


class FiscalRotinaPreferencia(Base):
    """Preferência explícita; defaults operacionais são resolvidos sem inserir dados."""

    __tablename__ = "fiscal_rotinas_clinicas"
    __table_args__ = (
        CheckConstraint("modo IN ('semanal', 'por_servico')", name="ck_fiscal_rotina_modo"),
        CheckConstraint("versao > 0", name="ck_fiscal_rotina_versao"),
    )

    clinica_id = Column(Integer, ForeignKey("clinicas.id"), primary_key=True)
    modo = Column(String(20), nullable=False)
    pagamento_depende_nf = Column(Boolean, nullable=False, default=False)
    versao = Column(Integer, nullable=False, default=1)
    atualizado_em = Column(Text, nullable=False)
    usuario_id = Column(Integer)
    usuario_nome = Column(Text)


class FiscalAndamentoEvento(Base):
    """Confirmações manuais append-only, independentes da existência da OS viva."""

    __tablename__ = "fiscal_andamento_eventos"
    __table_args__ = (
        UniqueConstraint("os_id", "versao", name="uq_fiscal_andamento_os_versao"),
        CheckConstraint("versao > 0", name="ck_fiscal_andamento_versao"),
        CheckConstraint(
            "(etapa_anterior = 'preparado' AND destino = 'enviado_contador') OR "
            "(etapa_anterior = 'enviado_contador' AND destino = 'nota_recebida') OR "
            "(etapa_anterior = 'nota_recebida' AND destino = 'nota_encaminhada')",
            name="ck_fiscal_andamento_transicao",
        ),
    )

    id = Column(Integer, primary_key=True)
    os_id = Column(Integer, ForeignKey("fiscal_fechamentos_os.os_id"), nullable=False)
    versao = Column(Integer, nullable=False)
    etapa_anterior = Column(String(32), nullable=False)
    destino = Column(String(32), nullable=False)
    referencia_nota = Column(String(200))
    observacao = Column(Text)
    chave_idempotencia = Column(String(36), nullable=False, unique=True)
    fingerprint = Column(String(64), nullable=False)
    registrado_em = Column(Text, nullable=False, index=True)
    usuario_id = Column(Integer)
    usuario_nome = Column(Text)
