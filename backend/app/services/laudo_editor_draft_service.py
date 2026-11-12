"""Raw form recovery with optimistic concurrency and no clinical side effects."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.laudo_editor_draft import LaudoEditorDraft, LaudoEditorDraftRequest
from app.schemas.laudo_editor_draft import LaudoEditorDraftClose, LaudoEditorDraftSave
from app.services.echo_editor_source import existing_snapshot_source, validate_existing_binding


MAX_SNAPSHOT_BYTES = 512 * 1024
MAX_SNAPSHOT_DEPTH = 20
MAX_SNAPSHOT_NODES = 20_000
MAX_SNAPSHOT_KEYS = 10_000
_FORBIDDEN_KEYS = {
    "token", "accesstoken", "refreshtoken", "idtoken", "authorization", "bearer",
    "password", "senha", "secret", "apikey", "cookie", "cookies", "credentials",
    "sessiontoken", "authtoken", "csrftoken",
    "file", "blob", "dataurl", "arraybuffer", "conteudobinario", "base64",
}
_CONFLICT = "O rascunho mudou em outra aba ou requisição. Recarregue a versão salva antes de continuar."
_JWT_VALUE = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def _conflict() -> HTTPException:
    return HTTPException(409, _CONFLICT)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def validate_snapshot(snapshot: dict[str, Any]) -> str:
    """Validate transport bounds only. Never derive or normalize clinical fields."""
    if type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1:
        raise HTTPException(422, "Versão do rascunho não suportada.")
    if snapshot.get("editor") not in {"new-echo", "existing-echo"}:
        raise HTTPException(422, "Editor de rascunho não suportado.")
    existing_snapshot_source(snapshot)
    nodes = keys = 0
    pending: list[tuple[Any, int]] = [(snapshot, 0)]
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > MAX_SNAPSHOT_DEPTH or nodes > MAX_SNAPSHOT_NODES:
            raise HTTPException(422, "Estrutura do rascunho excede o limite permitido.")
        if isinstance(value, dict):
            keys += len(value)
            if keys > MAX_SNAPSHOT_KEYS:
                raise HTTPException(422, "Estrutura do rascunho excede o limite permitido.")
            if "lastModified" in value and {"name", "size", "type"}.issubset(value):
                raise HTTPException(422, "Arquivos devem ser enviados pelo importador de imagens.")
            for key, child in value.items():
                normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
                if normalized in _FORBIDDEN_KEYS or normalized.endswith(("accesstoken", "refreshtoken")):
                    raise HTTPException(422, "O rascunho não aceita credenciais ou conteúdo de arquivos.")
                pending.append((child, depth + 1))
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
        elif isinstance(value, str):
            if (value.lstrip().lower().startswith(("data:", "blob:", "bearer ", "sk-proj-"))
                    or _JWT_VALUE.fullmatch(value.strip())):
                raise HTTPException(422, "O rascunho não aceita credenciais ou conteúdo de arquivos.")
        elif isinstance(value, float) and not math.isfinite(value):
            raise HTTPException(422, "O rascunho contém um valor não serializável.")
        elif value is not None and not isinstance(value, (int, float, bool)):
            raise HTTPException(422, "O rascunho contém um valor não serializável.")
    try:
        serialized = _canonical(snapshot)
    except (TypeError, ValueError, RecursionError):
        raise HTTPException(422, "O rascunho contém um valor não serializável.") from None
    try:
        size = len(serialized.encode("utf-8"))
    except UnicodeEncodeError:
        raise HTTPException(422, "O rascunho contém um texto não serializável.") from None
    if size > MAX_SNAPSHOT_BYTES:
        raise HTTPException(413, "O rascunho excede o limite de 512 KiB.")
    return serialized


def _timestamp(value: datetime) -> str:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()


def _is_write_collision(error: IntegrityError | OperationalError) -> bool:
    if isinstance(error, IntegrityError):
        return True
    original = error.orig
    # Database error codes only: never inspect/log SQL or its clinical values.
    sqlite_code = getattr(original, "sqlite_errorcode", None)
    postgres_code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return (isinstance(sqlite_code, int) and sqlite_code & 0xFF in {5, 6}) or postgres_code in {"40001", "40P01"}


def _owned(db: Session, owner_id: int, draft_id: str) -> LaudoEditorDraft | None:
    return db.query(LaudoEditorDraft).filter(
        LaudoEditorDraft.owner_id == owner_id,
        LaudoEditorDraft.draft_id == draft_id,
    ).first()


def _receipt(db: Session, row_id: int, request_id: str) -> LaudoEditorDraftRequest | None:
    return db.query(LaudoEditorDraftRequest).filter(
        LaudoEditorDraftRequest.draft_row_id == row_id,
        LaudoEditorDraftRequest.request_id == request_id,
    ).first()


def _response(draft_id: str, context_key: str, snapshot: dict, revision: int, updated_at: datetime) -> dict:
    return {
        "draft_id": draft_id, "revision": revision, "context_key": context_key,
        "snapshot": snapshot, "updated_at": _timestamp(updated_at),
    }


def get_editor_draft(db: Session, owner_id: int, draft_id: str) -> dict:
    with db.no_autoflush:
        row = _owned(db, owner_id, draft_id)
        if row is None:
            raise HTTPException(404, "Rascunho não encontrado.")
        snapshot = json.loads(row.snapshot_json)
        source = validate_existing_binding(db, snapshot, row.context_key)
        if row.closed_at is not None:
            if source:
                receipt = db.query(LaudoEditorDraftRequest).filter(
                    LaudoEditorDraftRequest.draft_row_id == row.id,
                    LaudoEditorDraftRequest.operation == "apply",
                ).order_by(LaudoEditorDraftRequest.revision.desc()).first()
                result = ({"id": source["laudo_id"], "request_id": receipt.request_id, "updated": True}
                          if receipt else None)
                raise HTTPException(410, {"code": "EDITOR_DRAFT_CLOSED", "laudo_id": source["laudo_id"], "apply_result": result})
            raise HTTPException(410, "Este rascunho já foi encerrado.")
        return _response(row.draft_id, row.context_key, json.loads(row.snapshot_json), row.revision, row.updated_at)


def save_editor_draft(db: Session, owner_id: int, draft_id: str, data: LaudoEditorDraftSave) -> dict:
    serialized = validate_snapshot(data.snapshot)
    validate_existing_binding(db, data.snapshot, data.context_key)
    fingerprint = hashlib.sha256(_canonical({
        "operation": "save", "expected_revision": data.expected_revision,
        "context_key": data.context_key, "snapshot": data.snapshot,
    }).encode("utf-8")).hexdigest()
    request_id = str(data.request_id)

    def replay(row: LaudoEditorDraft) -> dict | None:
        previous = json.loads(row.snapshot_json)
        validate_existing_binding(db, previous, row.context_key)
        if (previous.get("editor") != data.snapshot.get("editor")
                or (previous.get("editor") == "existing-echo"
                    and (previous.get("source") != data.snapshot.get("source")
                         or previous.get("sessionId") != data.snapshot.get("sessionId")))):
            raise _conflict()
        if row.closed_at is not None:
            raise HTTPException(409, "Este rascunho já foi encerrado.")
        if row.context_key != data.context_key:
            raise _conflict()
        receipt = _receipt(db, row.id, request_id)
        if receipt is None:
            return None
        if receipt.operation != "save" or receipt.payload_hash != fingerprint:
            raise _conflict()
        return _response(draft_id, data.context_key, data.snapshot, receipt.revision, receipt.updated_at)

    row = _owned(db, owner_id, draft_id)
    if row is not None:
        response = replay(row)
        if response is not None:
            return response
        if row.revision != data.expected_revision:
            raise _conflict()
    elif data.expected_revision != 0:
        raise _conflict()

    now = datetime.now(timezone.utc)
    revision = data.expected_revision + 1
    try:
        if row is None:
            row = LaudoEditorDraft(
                owner_id=owner_id, draft_id=draft_id, context_key=data.context_key,
                revision=revision, snapshot_json=serialized, updated_at=now,
            )
            db.add(row)
            db.flush()
        else:
            updated = db.execute(update(LaudoEditorDraft).where(
                LaudoEditorDraft.id == row.id,
                LaudoEditorDraft.owner_id == owner_id,
                LaudoEditorDraft.revision == data.expected_revision,
                LaudoEditorDraft.closed_at.is_(None),
            ).values(revision=revision, snapshot_json=serialized, updated_at=now)
                .execution_options(synchronize_session=False))
            if updated.rowcount != 1:
                db.rollback()
                latest = _owned(db, owner_id, draft_id)
                if latest is not None:
                    response = replay(latest)
                    if response is not None:
                        return response
                raise _conflict()
        db.add(LaudoEditorDraftRequest(
            draft_row_id=row.id, request_id=request_id, operation="save",
            payload_hash=fingerprint, revision=revision, updated_at=now,
        ))
        db.commit()
    except (IntegrityError, OperationalError) as error:
        db.rollback()
        if not _is_write_collision(error):
            raise HTTPException(503, "Não foi possível salvar o rascunho. Tente novamente.") from None
        row = _owned(db, owner_id, draft_id)
        if row is not None:
            response = replay(row)
            if response is not None:
                return response
        raise _conflict() from None
    return _response(draft_id, data.context_key, data.snapshot, revision, now)


def close_editor_draft(db: Session, owner_id: int, draft_id: str, data: LaudoEditorDraftClose) -> dict:
    row = _owned(db, owner_id, draft_id)
    if row is None:
        raise HTTPException(404, "Rascunho não encontrado.")
    validate_existing_binding(db, json.loads(row.snapshot_json), row.context_key)
    request_id = str(data.request_id)
    fingerprint = hashlib.sha256(_canonical({
        "operation": "close", "expected_revision": data.expected_revision,
    }).encode("utf-8")).hexdigest()

    def replay(current: LaudoEditorDraft) -> dict | None:
        receipt = _receipt(db, current.id, request_id)
        if receipt is None:
            return None
        if receipt.operation != "close" or receipt.payload_hash != fingerprint:
            raise _conflict()
        return {"draft_id": draft_id, "revision": receipt.revision, "closed": True,
                "updated_at": _timestamp(receipt.updated_at)}

    response = replay(row)
    if response is not None:
        return response
    if row.closed_at is not None or row.revision != data.expected_revision:
        raise _conflict()
    now = datetime.now(timezone.utc)
    revision = data.expected_revision + 1
    try:
        updated = db.execute(update(LaudoEditorDraft).where(
            LaudoEditorDraft.id == row.id,
            LaudoEditorDraft.owner_id == owner_id,
            LaudoEditorDraft.revision == data.expected_revision,
            LaudoEditorDraft.closed_at.is_(None),
        ).values(revision=revision, closed_at=now, updated_at=now)
            .execution_options(synchronize_session=False))
        if updated.rowcount != 1:
            db.rollback()
            latest = _owned(db, owner_id, draft_id)
            if latest is not None:
                response = replay(latest)
                if response is not None:
                    return response
            raise _conflict()
        db.add(LaudoEditorDraftRequest(
            draft_row_id=row.id, request_id=request_id, operation="close",
            payload_hash=fingerprint, revision=revision, updated_at=now,
        ))
        db.commit()
    except (IntegrityError, OperationalError) as error:
        db.rollback()
        if not _is_write_collision(error):
            raise HTTPException(503, "Não foi possível encerrar o rascunho. Tente novamente.") from None
        row = _owned(db, owner_id, draft_id)
        if row is not None:
            response = replay(row)
            if response is not None:
                return response
        raise _conflict() from None
    return {"draft_id": draft_id, "revision": revision, "closed": True, "updated_at": _timestamp(now)}
