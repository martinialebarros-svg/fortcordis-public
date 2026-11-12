from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AssistenteIAChatRequest(BaseModel):
    mensagem: str = Field(..., min_length=1, max_length=6000)
    conversa_id: Optional[str] = Field(default=None, min_length=36, max_length=36)


class AssistenteIAAcaoDecisaoRequest(BaseModel):
    decisao: Literal["approve", "reject"]
    observacao: Optional[str] = Field(default=None, max_length=500)


class AssistenteIAMemoriaCreateRequest(BaseModel):
    titulo: str = Field(..., min_length=3, max_length=180)
    conteudo: str = Field(..., min_length=3, max_length=8000)
    categoria: str = Field(default="operacao", min_length=2, max_length=60)


class AssistenteIAMemoriaDecisaoRequest(BaseModel):
    decisao: Literal["approve", "reject"]


class AssistenteIAAprendizadoCreateRequest(BaseModel):
    titulo: str = Field(..., min_length=3, max_length=180)
    conteudo: str = Field(..., min_length=3, max_length=8000)
    categoria: str = Field(default="operacao", min_length=2, max_length=60)
    memoria_alvo_id: Optional[str] = Field(default=None, min_length=36, max_length=36)


class AssistenteIAAprendizadoDecisaoRequest(BaseModel):
    decisao: Literal["approve", "reject"]
    titulo: Optional[str] = Field(default=None, min_length=3, max_length=180)
    conteudo: Optional[str] = Field(default=None, min_length=3, max_length=8000)
    categoria: Optional[str] = Field(default=None, min_length=2, max_length=60)


class AssistenteIAMemoriaRollbackRequest(BaseModel):
    versao: int = Field(..., ge=1)


class AssistenteIAConhecimentoCreateRequest(BaseModel):
    titulo: str = Field(..., min_length=3, max_length=220)
    conteudo: str = Field(..., min_length=20, max_length=250_000)
    categoria: str = Field(default="manual", min_length=2, max_length=60)
    fonte: Optional[str] = Field(default=None, max_length=500)
    indexar_semanticamente: bool = False


class AssistenteIAMissaoCreateRequest(BaseModel):
    titulo: str = Field(..., min_length=3, max_length=180)
    tipo: Literal[
        "radar",
        "executive_summary",
        "billing_trend",
        "overdue_debts",
        "clinic_360",
        "eval_lab",
    ]
    configuracao: dict = Field(default_factory=dict)
    recorrencia: Literal["daily", "weekly"] = "daily"
    horario_local: str = Field(default="07:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    dias_semana: list[int] = Field(default_factory=list, max_length=7)
    enabled: bool = True


class AssistenteIAMissaoUpdateRequest(BaseModel):
    titulo: Optional[str] = Field(default=None, min_length=3, max_length=180)
    configuracao: Optional[dict] = None
    recorrencia: Optional[Literal["daily", "weekly"]] = None
    horario_local: Optional[str] = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    dias_semana: Optional[list[int]] = Field(default=None, max_length=7)
    enabled: Optional[bool] = None


class AssistenteIAFeedbackCreateRequest(BaseModel):
    mensagem_id: int = Field(..., ge=1)
    avaliacao: Literal["positive", "negative"]
    categoria: Optional[str] = Field(default=None, max_length=60)
    comentario: Optional[str] = Field(default=None, max_length=2000)
    correcao_esperada: Optional[str] = Field(default=None, max_length=6000)
