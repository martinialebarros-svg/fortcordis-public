"""Authoritative echo editing snapshots, independent of private autosave data."""
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re

from fastapi import HTTPException
from sqlalchemy.orm import defer

from app.models.imagem_laudo import ImagemLaudo
from app.models.laudo import Laudo
from app.models.paciente import Paciente
from app.models.tutor import Tutor

REVISION_PATTERN = r"^echo-v1:[0-9a-f]{64}$"
SOURCE_CONFLICT = "O laudo original mudou. Confira a versão atual antes de aplicar seu rascunho."


def _value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _record(record, *, exclude=()):
    if record is None:
        return None
    return {column.key: _value(getattr(record, column.key))
            for column in record.__table__.columns if column.key not in exclude}


@dataclass
class EchoEditorSource:
    laudo: Laudo
    paciente: Paciente | None
    tutor: Tutor | None
    imagens: list[ImagemLaudo]
    revision: str


def load_echo_editor_source(db, laudo_id: int, *, lock: bool = False) -> EchoEditorSource:
    """Lock in consistent order; binary image contents are immutable through APIs.

    Include every image ID and metadata, including soft-deleted rows. Do not
    transfer potentially tens of megabytes of image bytes to hash each GET.
    """
    def query(model):
        result = db.query(model).populate_existing()
        return result.with_for_update() if lock else result

    with db.no_autoflush:
        laudo = query(Laudo).filter(Laudo.id == laudo_id).first()
        if laudo is None:
            raise HTTPException(404, "Laudo não encontrado.")
        if (laudo.tipo or "").strip().lower() != "ecocardiograma":
            raise HTTPException(422, "Este editor aceita somente ecocardiogramas existentes.")
        paciente = query(Paciente).filter(Paciente.id == laudo.paciente_id).first()
        tutor = query(Tutor).filter(Tutor.id == paciente.tutor_id).first() if paciente and paciente.tutor_id else None
        imagens = query(ImagemLaudo).options(defer(ImagemLaudo.conteudo)).filter(
            ImagemLaudo.laudo_id == laudo_id).order_by(ImagemLaudo.id).all()
        content = {"laudo": _record(laudo), "paciente": _record(paciente),
                   "tutor": _record(tutor),
                   "imagens": [_record(image, exclude=("conteudo",)) for image in imagens]}
        serialized = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        revision = "echo-v1:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return EchoEditorSource(laudo, paciente, tutor, imagens, revision)


def existing_snapshot_source(snapshot: dict, context_key: str | None = None):
    if snapshot.get("editor") != "existing-echo":
        return None
    source = snapshot.get("source")
    session_id = snapshot.get("sessionId")
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,255}", session_id):
        raise HTTPException(422, "Sessão do rascunho existente inválida.")
    if (not isinstance(source, dict) or set(source) != {"laudo_id", "editor_revision"}
            or type(source.get("laudo_id")) is not int or source["laudo_id"] <= 0
            or not isinstance(source.get("editor_revision"), str)
            or not re.fullmatch(REVISION_PATTERN, source["editor_revision"])):
        raise HTTPException(422, "Origem do rascunho existente inválida.")
    if context_key is not None and context_key != f"edit:laudo:{source['laudo_id']}":
        raise HTTPException(422, "O contexto não corresponde ao laudo do rascunho.")
    return source


def validate_existing_binding(db, snapshot: dict, context_key: str):
    source = existing_snapshot_source(snapshot, context_key)
    if source:
        # Preserve stale private notes. Only the explicit apply performs CAS.
        with db.no_autoflush:
            row = db.query(Laudo.id, Laudo.tipo).filter(Laudo.id == source["laudo_id"]).first()
        if row is None:
            raise HTTPException(404, "Laudo não encontrado.")
        if (row[1] or "").strip().lower() != "ecocardiograma":
            raise HTTPException(422, "Este editor aceita somente ecocardiogramas existentes.")
    return source
