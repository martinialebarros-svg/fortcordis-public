from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import get_current_user
from app.models.user import User
from app.services.frontend_performance import (
    build_frontend_performance_sample,
    persist_frontend_performance_sample,
)

router = APIRouter()


class FrontendPerformanceSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_group: Literal["/dashboard", "/atendimento", "/laudos", "/configuracoes"]
    navigation_type: Literal["initial", "client"]
    outcome: Literal["ready", "partial", "error", "timeout", "cancelled"]
    shell_ms: float = Field(..., ge=0, le=120_000)
    content_ms: Optional[float] = Field(default=None, ge=0, le=120_000)


@router.post("/frontend-performance", status_code=status.HTTP_202_ACCEPTED)
def registrar_desempenho_frontend(
    payload: FrontendPerformanceSample,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Aceita apenas RUM agregado e nunca persiste identidade ou URL completa."""

    _ = current_user
    try:
        sample = build_frontend_performance_sample(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    background_tasks.add_task(persist_frontend_performance_sample, sample)
    return {"accepted": True}
