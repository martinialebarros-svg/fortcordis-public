"""Explicit, atomic update of an existing echo; never an autosave payload."""
from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from app.services.echo_editor_source import REVISION_PATTERN


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditorPatientPatch(StrictPayload):
    nome: str | None = Field(default=None, max_length=500)
    especie: str | None = Field(default=None, max_length=200)
    raca: str | None = Field(default=None, max_length=500)
    sexo: str | None = Field(default=None, max_length=100)
    peso_kg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    idade: str | None = Field(default=None, max_length=200)
    idade_informada: str | None = Field(default=None, max_length=200)
    idade_referencia: str | None = Field(default=None, max_length=10)
    idade_fonte: str | None = Field(default=None, max_length=20)
    data_nascimento: str | None = Field(default=None, max_length=10)


class EditorTutorPatch(StrictPayload):
    id: StrictInt | None = Field(default=None, gt=0)
    nome: str | None = Field(default=None, max_length=500)
    telefone: str | None = Field(default=None, max_length=100)
    criar_novo: bool = False


class EditorImageConfig(StrictPayload):
    id: StrictInt = Field(gt=0)
    ordem: StrictInt = Field(ge=0)
    incluir_no_pdf: bool = True
    descricao: str = Field(default="", max_length=5000)


class EditorImagesUpdate(StrictPayload):
    persistidas: list[EditorImageConfig] = Field(default_factory=list, max_length=200)
    removidas_ids: list[StrictInt] = Field(default_factory=list, max_length=200)
    temp_session_id: str | None = Field(default=None, min_length=1, max_length=255)
    temp_config: list[EditorImageConfig] = Field(default_factory=list, max_length=200)


class EchoEditorUpdate(StrictPayload):
    expected_editor_revision: str = Field(pattern=REVISION_PATTERN)
    request_id: UUID
    editor_draft_id: UUID
    expected_draft_revision: StrictInt = Field(ge=1)
    payload_laudo: dict[str, Any]
    paciente: EditorPatientPatch | None = None
    tutor: EditorTutorPatch | None = None
    imagens: EditorImagesUpdate | None = None
