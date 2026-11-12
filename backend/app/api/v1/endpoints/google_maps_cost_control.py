"""Consent quotes are read-only with respect to Google; config/history are admin-only."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy.orm import Session
from app.db.database import get_db

from app.core.security import get_current_user, require_papel
from app.models.user import User
from app.services.google_maps_cost_control import (
    CostConfiguration, confirm_preview, create_preview, get_status, update_configuration,
    identify_action, agenda_cache_first_enabled, emergency_release_enabled, GoogleMapsCostBlocked,
)

router = APIRouter()


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str = Field(min_length=3, max_length=10)
    path: str = Field(min_length=1, max_length=500, pattern=r"^/api/v1/")
    query: str | dict[str, Any] | None = None
    body: Any = None
    paid_call_required: StrictBool = False


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: str = Field(min_length=20, max_length=64)


class ConfigRequest(CostConfiguration):
    expected_revision: StrictInt = Field(ge=0)


@router.post("/preview")
def preview(payload: PreviewRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.google_maps_agenda_estimate import SEARCH_MODELS, estimate_search
    estimate = None
    spec = identify_action(payload.method, payload.path, payload.query, payload.body)
    if payload.paid_call_required and agenda_cache_first_enabled(spec) and spec.key in SEARCH_MODELS and not emergency_release_enabled():
        try:
            with db.no_autoflush:
                estimate = estimate_search(db, spec.key, payload.body)
        except HTTPException:
            raise
        except Exception:
            raise GoogleMapsCostBlocked("estimate_unavailable", status_code=503) from None
    return create_preview(current_user.id, **payload.model_dump(), route_estimate=estimate)


@router.post("/confirm")
def confirm(payload: ConfirmRequest, current_user: User = Depends(get_current_user)):
    return confirm_preview(current_user.id, payload.quote_id)


@router.get("/status")
def status(current_user: User = Depends(require_papel("admin"))):
    return get_status()


@router.put("/config")
def configure(payload: ConfigRequest, current_user: User = Depends(require_papel("admin"))):
    config = CostConfiguration.model_validate(payload.model_dump(exclude={"expected_revision"}))
    return update_configuration(current_user.id, config, payload.expected_revision)
