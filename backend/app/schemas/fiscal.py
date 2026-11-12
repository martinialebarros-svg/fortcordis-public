"""Schemas Pydantic para o módulo fiscal"""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator


# ─── CNPJ Consulta ─────────────────────────────────────────────────────────────

class CNPJConsultaResponse(BaseModel):
    """Resposta da consulta CNPJ na Receita WS."""
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    cnpj: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    cep: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    cnae_principal: Optional[str] = None
    situacao: Optional[str] = None
    error: Optional[str] = None


# ─── Nota Fiscal ──────────────────────────────────────────────────────────────

class NotaFiscalCreate(BaseModel):
    """Payload para criar uma nota fiscal."""
    os_id: Optional[int] = None
    tipo_cliente: str = Field(..., pattern="^(PF|PJ)$")
    cliente_nome: str
    cliente_documento: str
    cliente_endereco: Optional[str] = None
    cliente_bairro: Optional[str] = None
    cliente_cidade: Optional[str] = None
    cliente_estado: Optional[str] = None
    cliente_cep: Optional[str] = None
    cliente_telefone: Optional[str] = None
    cliente_email: Optional[str] = None
    valor_servico: float = 0
    valor_desconto: float = 0
    atividade_cnae: Optional[str] = None
    descricao_servico: Optional[str] = None
    observacoes: Optional[str] = None
    natureza_operacao: str = "Tributação no município"
    aliquota_iss: float = 5.0


class NotaFiscalUpdate(BaseModel):
    """Payload para atualizar uma nota fiscal."""
    numero: Optional[str] = None
    serie: Optional[str] = None
    cliente_nome: Optional[str] = None
    cliente_documento: Optional[str] = None
    cliente_endereco: Optional[str] = None
    cliente_bairro: Optional[str] = None
    cliente_cidade: Optional[str] = None
    cliente_estado: Optional[str] = None
    cliente_cep: Optional[str] = None
    cliente_telefone: Optional[str] = None
    cliente_email: Optional[str] = None
    valor_servico: Optional[float] = None
    valor_desconto: Optional[float] = None
    atividade_cnae: Optional[str] = None
    descricao_servico: Optional[str] = None
    observacoes: Optional[str] = None
    natureza_operacao: Optional[str] = None
    aliquota_iss: Optional[float] = None
    status: Optional[str] = None


class NotaFiscalResponse(BaseModel):
    """Resposta completa de uma nota fiscal."""
    id: int
    numero: Optional[str]
    serie: str
    os_id: Optional[int]
    tipo_cliente: str
    cliente_nome: str
    cliente_documento: str
    cliente_endereco: Optional[str]
    cliente_bairro: Optional[str]
    cliente_cidade: Optional[str]
    cliente_estado: Optional[str]
    cliente_cep: Optional[str]
    cliente_telefone: Optional[str]
    cliente_email: Optional[str]
    valor_servico: float
    valor_desconto: float
    valor_final: float
    aliquota_iss: float
    valor_iss: float
    atividade_cnae: Optional[str]
    descricao_servico: Optional[str]
    observacoes: Optional[str]
    natureza_operacao: str
    codigo_municipio: Optional[str]
    regime_tributario: Optional[int]
    formato_exportado: Optional[str]
    status: str
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class NotaFiscalListResponse(BaseModel):
    total: int
    items: list[NotaFiscalResponse]


class RelatorioFiscalEmissaoResponse(BaseModel):
    """Metadados seguros de uma exportação contábil concluída."""

    id: int
    formato: str
    modo: str
    tipo_emissao: str
    data_inicio: Optional[str]
    data_fim: Optional[str]
    quantidade_os: int
    valor_total: float
    clinicas: list[dict]
    descricao_servico: Optional[str]
    arquivo_nome: Optional[str]
    usuario_nome: Optional[str]
    emitido_em: str


class RelatorioFiscalEmissaoListResponse(BaseModel):
    total: int
    items: list[RelatorioFiscalEmissaoResponse]


class FiscalFechamentoCreate(BaseModel):
    competencia: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    os_ids: list[StrictInt] = Field(..., min_length=1, max_length=2000)
    chave_idempotencia: UUID
    confirmar_datas_prestacao: bool
    confirmar_exportacoes_anteriores: bool = False

    @field_validator("os_ids")
    @classmethod
    def validar_os_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("IDs de OS devem ser positivos.")
        if len(values) != len(set(values)):
            raise ValueError("A seleção contém IDs de OS repetidos.")
        return values


class FiscalRotinaPreferenciaUpdate(BaseModel):
    modo: Literal["semanal", "por_servico"]
    pagamento_depende_nf: StrictBool
    versao_esperada: StrictInt = Field(..., ge=0)


class FiscalRotinaPrepararRequest(FiscalFechamentoCreate):
    modo: Literal["semanal", "por_servico"]
    data_corte: Optional[str] = None
    clinica_id: Optional[StrictInt] = Field(None, gt=0)


class FiscalAndamentoUpdate(BaseModel):
    destino: Literal["enviado_contador", "nota_recebida", "nota_encaminhada"]
    versao_esperada: StrictInt = Field(..., ge=0)
    chave_idempotencia: UUID
    confirmar_acao_manual: StrictBool
    referencia_nota: Optional[str] = Field(None, max_length=200)
    observacao: Optional[str] = Field(None, max_length=2000)
