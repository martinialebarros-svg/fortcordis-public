from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from typing import Final

from app.core.config import settings


class AttachmentValidationError(ValueError):
    """Base para erros de validacao de upload de anexo."""


class AttachmentTypeError(AttachmentValidationError):
    """Arquivo com tipo/extensao invalido para upload."""


class AttachmentTooLargeError(AttachmentValidationError):
    """Arquivo acima do limite permitido para upload."""


MAX_ATENDIMENTO_ATTACHMENT_SIZE: Final[int] = 25 * 1024 * 1024
ALLOWED_ATENDIMENTO_ATTACHMENT_EXTENSIONS: Final[set[str]] = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}
ALLOWED_ATENDIMENTO_ATTACHMENT_MIME_TYPES: Final[set[str]] = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}

_MIME_ALIASES: Final[dict[str, str]] = {
    "image/jpg": "image/jpeg",
}
_EXTENSION_MIME_MAP: Final[dict[str, str]] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_MIME_ALLOWED_EXTENSIONS: Final[dict[str, set[str]]] = {
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
}


def _fallback_storage_dir() -> str:
    return os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "generated",
            "atendimentos_uploads",
        )
    )


def get_atendimento_upload_storage_dir(atendimento_id: int) -> str:
    preferred = str(settings.UPLOAD_DIR or "").strip()
    if os.name == "nt" and preferred.startswith("/"):
        preferred = ""
    candidate = os.path.join(preferred, "atendimentos", str(atendimento_id)) if preferred else ""

    for path in [candidate, os.path.join(_fallback_storage_dir(), str(atendimento_id))]:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            continue

    raise RuntimeError("Nao foi possivel criar diretorio para anexos do atendimento.")


def normalize_attachment_filename(filename: str | None, fallback: str = "anexo.bin") -> str:
    raw_name = os.path.basename((filename or "").strip()) or fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    return cleaned or fallback


def _normalize_content_type(content_type: str | None) -> str:
    normalized = (content_type or "").strip().lower()
    if ";" in normalized:
        normalized = normalized.split(";", 1)[0].strip()
    return _MIME_ALIASES.get(normalized, normalized)


def _allowed_extensions_display() -> str:
    return ", ".join(sorted(ALLOWED_ATENDIMENTO_ATTACHMENT_EXTENSIONS))


def validate_attachment_type(filename: str | None, content_type: str | None) -> str:
    normalized_name = normalize_attachment_filename(filename)
    extension = os.path.splitext(normalized_name)[1].lower()
    if extension not in ALLOWED_ATENDIMENTO_ATTACHMENT_EXTENSIONS:
        raise AttachmentTypeError(
            f"Tipo de arquivo nao permitido. Use: {_allowed_extensions_display()}"
        )

    normalized_content_type = _normalize_content_type(content_type)
    if not normalized_content_type or normalized_content_type == "application/octet-stream":
        return _EXTENSION_MIME_MAP[extension]

    if normalized_content_type not in ALLOWED_ATENDIMENTO_ATTACHMENT_MIME_TYPES:
        raise AttachmentTypeError(
            f"Tipo MIME nao permitido: {normalized_content_type}. "
            f"Use: {', '.join(sorted(ALLOWED_ATENDIMENTO_ATTACHMENT_MIME_TYPES))}"
        )

    allowed_extensions = _MIME_ALLOWED_EXTENSIONS.get(normalized_content_type, set())
    if extension not in allowed_extensions:
        raise AttachmentTypeError("Extensao do arquivo nao corresponde ao tipo MIME informado.")

    return normalized_content_type


def validate_attachment_size(content: bytes) -> None:
    if len(content) > MAX_ATENDIMENTO_ATTACHMENT_SIZE:
        raise AttachmentTooLargeError("Arquivo excede o limite de 25MB")


def calculate_attachment_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_upload_dedupe_key(exame_id: int | None, arquivo_hash: str) -> str:
    scope = f"exame:{exame_id}" if exame_id is not None else "exame:none"
    return f"{scope}|sha256:{(arquivo_hash or '').strip().lower()}"


def store_atendimento_attachment_file(
    atendimento_id: int,
    filename: str | None,
    content: bytes,
    content_type: str | None = None,
) -> tuple[str, str, str]:
    normalized_name = normalize_attachment_filename(filename)
    normalized_mime_type = validate_attachment_type(normalized_name, content_type)
    validate_attachment_size(content)

    storage_dir = get_atendimento_upload_storage_dir(atendimento_id)
    unique_prefix = uuid.uuid4().hex[:12]
    target_name = f"{unique_prefix}_{normalized_name}"
    target_path = os.path.join(storage_dir, target_name)

    fd, tmp_path = tempfile.mkstemp(
        suffix=os.path.splitext(normalized_name)[1] or ".bin",
        prefix="anexo_",
        dir=storage_dir,
    )
    try:
        with os.fdopen(fd, "wb") as file_obj:
            file_obj.write(content)
        os.replace(tmp_path, target_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return target_path, normalized_name, normalized_mime_type


def remove_atendimento_attachment_file(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError:
        return
