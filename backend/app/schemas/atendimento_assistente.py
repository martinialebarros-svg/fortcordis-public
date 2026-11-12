"""Draft-only clinical AI contract: generated content is never a record update."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CampoSugerido(StrictOutput):
    campo: Literal["queixa_principal", "anamnese", "exame_fisico", "dados_clinicos", "observacoes"]
    texto: str = Field(min_length=1, max_length=8000)
    fonte: str = Field(min_length=1, max_length=180)
    evidencia: str = Field(min_length=1, max_length=4000)


class FonteExame(StrictOutput):
    arquivo: str = Field(min_length=1, max_length=180)
    paciente_nome: str | None
    especie: str | None
    data_exame: str | None
    identidade: Literal["compativel", "divergente", "nao_confirmada"]
    motivo: str = Field(max_length=2000)


class AchadoExame(StrictOutput):
    arquivo: str = Field(min_length=1, max_length=180)
    pagina: int | None = Field(ge=1, le=100)
    descricao: str = Field(min_length=1, max_length=2000)
    valor: str | None
    unidade: str | None
    referencia: str | None
    confianca: Literal["alta", "media", "baixa"]
    alertas: list[str] = Field(max_length=20)
    evidencia: str = Field(min_length=1, max_length=4000)


class SugestaoConduta(StrictOutput):
    titulo: str = Field(min_length=1, max_length=500)
    justificativa: str = Field(min_length=1, max_length=4000)
    conduta: str = Field(min_length=1, max_length=4000)
    limitacoes: list[str] = Field(max_length=20)


class AnaliseClinica(StrictOutput):
    campos: list[CampoSugerido] = Field(max_length=30)
    fontes: list[FonteExame] = Field(max_length=5)
    achados_exames: list[AchadoExame] = Field(max_length=100)
    sugestoes: list[SugestaoConduta] = Field(max_length=15)
    pendencias: list[str] = Field(max_length=40)
    avisos: list[str] = Field(max_length=40)
