"""A read-only projection of the exact editor emission/update intent."""
from typing import Any

from pydantic import ConfigDict, BaseModel, Field, StrictInt

from app.schemas.echo_editor_update import EditorImagesUpdate, EditorPatientPatch, EditorTutorPatch


class EchoPdfPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt = Field(ge=1)
    payload_laudo: dict[str, Any]
    paciente: EditorPatientPatch | None = None
    tutor: EditorTutorPatch | None = None
    imagens: EditorImagesUpdate
