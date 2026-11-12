from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AlertaInternoResponse(BaseModel):
    id: int
    tipo: str
    nivel: str
    titulo: str
    mensagem: str
    entidade_tipo: Optional[str] = None
    entidade_id: Optional[int] = None
    clinica_id: Optional[int] = None
    lido: bool
    lido_por_nome: Optional[str] = None
    lido_em: Optional[datetime] = None
    criado_em: datetime


class AlertaInternoListResponse(BaseModel):
    total_nao_lidos: int = 0
    items: list[AlertaInternoResponse] = Field(default_factory=list)


class AlertaInternoAckResponse(BaseModel):
    status: str = "ok"
