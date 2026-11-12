"""Transport metadata for a private new-echo workspace, not a clinical schema."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class LaudoEditorDraftSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt = Field(ge=0)
    request_id: UUID
    context_key: str = Field(min_length=1, max_length=200, strict=True, pattern=r"^[A-Za-z0-9:_-]+$")
    snapshot: dict[str, Any]


class LaudoEditorDraftClose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt = Field(ge=1)
    request_id: UUID


class LaudoEditorDraftResponse(BaseModel):
    draft_id: str
    revision: int
    context_key: str
    snapshot: dict[str, Any]
    updated_at: str


class LaudoEditorDraftClosedResponse(BaseModel):
    draft_id: str
    revision: int
    closed: bool
    updated_at: str
