from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LaudoComparacaoSnapshot(BaseModel):
    id: int
    paciente_id: int
    status: str
    data_exame: str | None
    medidas: dict[str, str] = Field(default_factory=dict)


class LaudoComparacaoOpcao(BaseModel):
    id: int
    data_exame: str


class LaudoComparacaoAnteriorResponse(BaseModel):
    estado: Literal[
        "disponivel",
        "sem_anterior",
        "data_atual_ausente",
        "data_anterior_ambigua",
        "tipo_nao_suportado",
    ]
    paciente_id: int
    atual: LaudoComparacaoSnapshot
    anterior: LaudoComparacaoSnapshot | None = None
    opcoes: list[LaudoComparacaoOpcao] = Field(default_factory=list)
