"""Entradas explícitas: vazio é desconhecido, zero é uma declaração do admin."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class EntradaGestao(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ContextoGestao(EntradaGestao):
    data_inicio: date
    data_fim: date
    clinica_id: int | None = Field(default=None, ge=1)
    regiao: str | None = Field(default=None, min_length=1, max_length=150)

    @field_validator("regiao", mode="before")
    @classmethod
    def normalizar_regiao(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @model_validator(mode="after")
    def validar_periodo(self):
        if self.data_fim < self.data_inicio:
            raise ValueError("A data final deve ser igual ou posterior à inicial.")
        if (self.data_fim - self.data_inicio).days >= 366:
            raise ValueError("Selecione até 366 dias por consulta.")
        if self.data_inicio.year < 2001 or self.data_fim.year > 2100:
            raise ValueError("Selecione datas entre 2001 e 2100.")
        return self


class MovimentoPremissa(EntradaGestao):
    data: date
    tipo: Literal["entrada", "saida"]
    valor: float = Field(gt=0, le=1_000_000_000)
    recorrencia: Literal["unica", "mensal"] = "unica"
    descricao: str = Field(min_length=1, max_length=160)

    @field_validator("valor", mode="before")
    @classmethod
    def validar_valor(cls, value):
        if isinstance(value, bool):
            raise ValueError("Informe um valor numérico.")
        return value

    @field_validator("descricao", mode="before")
    @classmethod
    def limpar_descricao(cls, value):
        return value.strip() if isinstance(value, str) else value


class PremissasGestao(EntradaGestao):
    tributos_percentual: float | None = Field(default=None, ge=0, le=100)
    repasses_percentual: float | None = Field(default=None, ge=0, le=100)
    taxas_percentual: float | None = Field(default=None, ge=0, le=100)
    custos_variaveis: float | None = Field(default=None, ge=0, le=1_000_000_000)
    horas_atendimento: float | None = Field(default=None, ge=0, le=100_000)
    horas_laudos: float | None = Field(default=None, ge=0, le=100_000)
    horas_deslocamento: float | None = Field(default=None, ge=0, le=100_000)
    saldo_inicial: float | None = Field(default=None, ge=-1_000_000_000, le=1_000_000_000)
    despesas_completas: StrictBool = False
    movimentos: list[MovimentoPremissa] = Field(default_factory=list, max_length=200)

    @field_validator("tributos_percentual", "repasses_percentual", "taxas_percentual", "custos_variaveis",
                     "horas_atendimento", "horas_laudos", "horas_deslocamento", "saldo_inicial", mode="before")
    @classmethod
    def rejeitar_booleano_como_valor(cls, value):
        if isinstance(value, bool):
            raise ValueError("Informe um número ou deixe o campo vazio.")
        return value


class ConsultaGestao(ContextoGestao):
    premissas: PremissasGestao = Field(default_factory=PremissasGestao)


class SalvarPremissasGestao(EntradaGestao):
    expected_revision: int = Field(ge=0, strict=True)
    contexto: ContextoGestao
    values: PremissasGestao
