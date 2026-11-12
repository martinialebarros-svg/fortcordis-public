from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import unicodedata
from datetime import date
from typing import Any

from PIL import Image, ImageOps

from app.services.tesseract_runtime import resolve_tesseract_command

MAX_IMAGE_HEADER_IMPORT_SIZE = 15 * 1024 * 1024
ALLOWED_IMAGE_HEADER_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
}

_NA_VALUES = {
    "",
    "n/a",
    "na",
    "n a",
    "n\\a",
    "n.a",
    "none",
    "null",
    "-",
}

_NEXT_LABEL_RE = re.compile(
    r"\b(?:"
    r"owner|idade|species|breed|g\S?nero|gender|sex|"
    r"data\s*do\s*exame|exam\s*date|study\s*date|"
    r"perf\.?\s*physician|ref\.?\s*physician|"
    r"operador|operator|"
    r"id\s*do\s*paciente|patient\s*id|nome"
    r")\b",
    re.IGNORECASE,
)

_RESAMPLING_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def _resolve_tesseract_command() -> str:
    return resolve_tesseract_command()


def _resolve_tessdata_dir() -> str | None:
    explicit_dir = (os.getenv("TESSDATA_DIR") or os.getenv("TESSDATA_PREFIX") or "").strip()
    if explicit_dir and os.path.isdir(explicit_dir):
        return explicit_dir

    local_dir = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "generated",
            "tessdata",
        )
    )
    if os.path.isdir(local_dir):
        return local_dir

    common_windows_dir = r"C:\Program Files\Tesseract-OCR\tessdata"
    if os.name == "nt" and os.path.isdir(common_windows_dir):
        return common_windows_dir

    return None


def normalize_image_import_filename(filename: str | None) -> str:
    raw_name = os.path.basename((filename or "").strip())
    return raw_name or "cabecalho.png"


def validate_image_import_filename(filename: str | None) -> str:
    normalized = normalize_image_import_filename(filename)
    extension = os.path.splitext(normalized)[1].lower()
    if extension not in ALLOWED_IMAGE_HEADER_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_HEADER_EXTENSIONS))
        raise ValueError(f"Arquivo deve ser uma imagem ({allowed})")
    return normalized


def validate_image_import_size(content: bytes) -> None:
    if len(content) > MAX_IMAGE_HEADER_IMPORT_SIZE:
        raise ValueError("Imagem excede o limite de 15MB")


def _remove_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_for_match(text: str) -> str:
    normalized = _remove_diacritics(text).lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _clean_field_value(value: str, *, allow_numeric_only: bool = False) -> str:
    cleaned = (value or "").strip()
    cleaned = re.sub(r"^[\s:;.\-]+", "", cleaned)
    cleaned = _NEXT_LABEL_RE.split(cleaned, maxsplit=1)[0].strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return ""

    normalized = _normalize_for_match(cleaned)
    if normalized in _NA_VALUES:
        return ""

    if not allow_numeric_only and re.fullmatch(r"[0-9\s.,/:-]+", cleaned):
        return ""

    return cleaned


def _extract_field_value(
    lines: list[str],
    patterns: list[str],
    *,
    allow_numeric_only: bool = False,
) -> str:
    for line in lines:
        for pattern in patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if not match:
                continue
            value = _clean_field_value(
                match.group(1),
                allow_numeric_only=allow_numeric_only,
            )
            if value:
                return value
    return ""


def _normalizar_especie(value: str) -> str:
    cleaned = _clean_field_value(value)
    if not cleaned:
        return ""

    normalized = _normalize_for_match(cleaned)
    if any(token in normalized for token in ("canina", "canino", "cao", "dog", "canine")):
        return "Canina"
    if any(token in normalized for token in ("felina", "felino", "gato", "cat", "feline")):
        return "Felina"
    if any(token in normalized for token in ("equina", "equino", "horse", "equine")):
        return "Equina"
    return cleaned.title()


def _normalizar_sexo(value: str) -> str:
    cleaned = _clean_field_value(value)
    if not cleaned:
        return ""

    normalized = _normalize_for_match(cleaned)
    if normalized in {"f", "female", "femea", "femea inteira", "femea castrada"}:
        return "Femea"
    if normalized in {"m", "male", "macho", "macho inteiro", "macho castrado"}:
        return "Macho"

    if "fem" in normalized:
        return "Femea"
    if "mach" in normalized:
        return "Macho"
    return ""


def _normalizar_idade(value: str) -> str:
    cleaned = _clean_field_value(value, allow_numeric_only=True)
    if not cleaned:
        return ""

    normalized = _normalize_for_match(cleaned)

    years_match = re.match(r"^(\d{1,2})\s*(?:a|ano|anos|y|yr|yrs|year|years)\b", normalized)
    if years_match:
        return f"{years_match.group(1)} anos"

    months_match = re.match(r"^(\d{1,2})\s*(?:m|mes|meses|mo|mos|month|months)\b", normalized)
    if months_match:
        return f"{months_match.group(1)} meses"

    if re.fullmatch(r"\d{1,2}", normalized):
        return f"{normalized} anos"

    return cleaned


def _safe_iso_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _normalizar_data_exame(value: str) -> str:
    cleaned = _clean_field_value(value, allow_numeric_only=True)
    if not cleaned:
        return ""

    ddmmyyyy = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", cleaned)
    if ddmmyyyy:
        day, month, year = [int(item) for item in ddmmyyyy.groups()]
        return _safe_iso_date(year, month, day)

    yyyymmdd = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", cleaned)
    if yyyymmdd:
        year, month, day = [int(item) for item in yyyymmdd.groups()]
        return _safe_iso_date(year, month, day)

    return ""


def _extract_clinic(lines: list[str]) -> str:
    info_index: int | None = None
    for idx, line in enumerate(lines):
        normalized = _normalize_for_match(line)
        if "informacao paciente" in normalized:
            info_index = idx
            break

    header_lines = lines[:info_index] if info_index is not None else lines[:3]
    candidates: list[str] = []

    for line in header_lines:
        cleaned = re.sub(r"\s+", " ", line).strip()
        normalized = _normalize_for_match(cleaned)
        if not cleaned:
            continue
        if normalized in {"ultrassonografia", "ultrasound", "informacao paciente"}:
            continue
        if len(re.sub(r"[^A-Za-z]", "", cleaned)) < 3:
            continue
        candidates.append(cleaned)

    return candidates[-1] if candidates else ""


def _prepare_header_lines(text: str) -> list[str]:
    lines = [re.sub(r"\s+", " ", item).strip() for item in (text or "").splitlines()]
    lines = [line for line in lines if line]

    if not lines:
        return []

    cutoff = len(lines)
    for idx, line in enumerate(lines):
        normalized = _normalize_for_match(line)
        if "medida" in normalized or normalized.startswith("imagem"):
            cutoff = idx
            break

    header_lines = lines[:cutoff] if cutoff > 0 else lines
    return header_lines or lines


def parse_image_header_text(text: str) -> dict[str, Any]:
    lines = _prepare_header_lines(text)

    nome = _extract_field_value(
        lines,
        [
            r"\bnome\s*[:;\-]\s*(.+)$",
            r"^\s*nome\s+(.+)$",
        ],
    )
    id_paciente = _extract_field_value(
        lines,
        [
            r"\bid\s*do\s*paciente\s*[:;\-]?\s*(.+)$",
            r"\bpatient\s*id\s*[:;\-]?\s*(.+)$",
        ],
        allow_numeric_only=True,
    )
    owner = _extract_field_value(
        lines,
        [
            r"\bowner\s*[:;\-]?\s*(.+)$",
            r"\btutor\s*[:;\-]?\s*(.+)$",
        ],
    )
    idade = _extract_field_value(
        lines,
        [
            r"\bidade\s*[:;\-]?\s*(.+)$",
            r"\bage\s*[:;\-]?\s*(.+)$",
        ],
        allow_numeric_only=True,
    )
    species = _extract_field_value(
        lines,
        [
            r"\bspecies\s*[:;\-]?\s*(.+)$",
            r"\besp\S?cie\s*[:;\-]?\s*(.+)$",
            r"\bespecie\s*[:;\-]?\s*(.+)$",
        ],
    )
    breed = _extract_field_value(
        lines,
        [
            r"\bbreed\s*[:;\-]?\s*(.+)$",
            r"\bra\S?a\s*[:;\-]?\s*(.+)$",
            r"\braca\s*[:;\-]?\s*(.+)$",
        ],
    )
    genero = _extract_field_value(
        lines,
        [
            r"\bg\S?nero\s*[:;\-]?\s*(.+)$",
            r"\bgender\s*[:;\-]?\s*(.+)$",
            r"\bsex\s*[:;\-]?\s*(.+)$",
        ],
    )
    data_exame = _extract_field_value(
        lines,
        [
            r"\bdata\s*do\s*exame\s*[:;\-]?\s*(.+)$",
            r"\bexam\s*date\s*[:;\-]?\s*(.+)$",
            r"\bstudy\s*date\s*[:;\-]?\s*(.+)$",
        ],
        allow_numeric_only=True,
    )
    perf_physician = _extract_field_value(lines, [r"\bperf\.?\s*physician\s*[:;\-]?\s*(.+)$"])
    ref_physician = _extract_field_value(lines, [r"\bref\.?\s*physician\s*[:;\-]?\s*(.+)$"])
    operator = _extract_field_value(
        lines,
        [
            r"\boperador\s*[:;\-]?\s*(.+)$",
            r"\boperator\s*[:;\-]?\s*(.+)$",
        ],
    )

    paciente_nome = nome or id_paciente
    tutor = owner or (id_paciente if paciente_nome != id_paciente else "")

    clinic = _extract_clinic(lines)
    vet = perf_physician or ref_physician

    payload: dict[str, Any] = {
        "paciente": {
            "nome": paciente_nome,
            "tutor": tutor,
            "raca": _clean_field_value(breed),
            "especie": _normalizar_especie(species),
            "peso": "",
            "idade": _normalizar_idade(idade),
            "sexo": _normalizar_sexo(genero),
            "telefone": "",
            "data_exame": _normalizar_data_exame(data_exame),
        },
        "medidas": {},
        "clinica": clinic,
        "veterinario_solicitante": vet,
        "fc": "",
        "campos_detectados": {
            "nome": nome,
            "id_paciente": id_paciente,
            "owner": owner,
            "idade": idade,
            "species": species,
            "breed": breed,
            "genero": genero,
            "data_exame": data_exame,
            "perf_physician": perf_physician,
            "ref_physician": ref_physician,
            "operator": operator,
        },
    }
    return payload


def _run_tesseract(image_path: str, language: str, *, psm: int = 6) -> str:
    executable = _resolve_tesseract_command()
    tessdata_dir = _resolve_tessdata_dir()
    command = [
        executable,
        image_path,
        "stdout",
        "--oem",
        "1",
        "--psm",
        str(psm),
        "-l",
        language,
        "-c",
        "preserve_interword_spaces=1",
    ]
    if tessdata_dir:
        command.extend(["--tessdata-dir", tessdata_dir])

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise ValueError(
            f"Tesseract OCR nao encontrado no servidor (comando: {executable}). Instale o Tesseract para habilitar importacao por imagem."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Tempo limite excedido ao executar OCR da imagem.") from exc

    stdout = result.stdout.decode("utf-8", errors="ignore")
    stderr = result.stderr.decode("utf-8", errors="ignore").strip()

    if result.returncode != 0:
        raise RuntimeError(stderr or "Falha ao executar OCR com Tesseract.")
    return stdout


def _extract_text_with_tesseract(image: Image.Image, *, psm: int = 6) -> str:
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        image.save(tmp_path, format="PNG")

        last_error: Exception | None = None
        for language in ("por+eng", "eng"):
            try:
                return _run_tesseract(tmp_path, language, psm=psm)
            except RuntimeError as exc:
                last_error = exc
                lowered = str(exc).lower()
                if "failed loading language" in lowered or "error opening data file" in lowered:
                    continue
                if language == "por+eng":
                    continue
                break

        if last_error:
            raise ValueError(f"Falha ao executar OCR: {last_error}") from last_error
        raise ValueError("Falha ao executar OCR com Tesseract.")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _build_image_variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    base = ImageOps.exif_transpose(image).convert("RGB")
    width, height = base.size

    crop_height = max(int(height * 0.45), min(height, 500))
    header_crop = base.crop((0, 0, width, crop_height))
    header_gray = ImageOps.grayscale(header_crop)
    header_upscaled = header_gray.resize(
        (max(1, header_gray.width * 2), max(1, header_gray.height * 2)),
        resample=_RESAMPLING_LANCZOS,
    )
    header_binary = header_upscaled.point(lambda px: 255 if px > 178 else 0, mode="1").convert("L")

    full_gray = ImageOps.grayscale(base)
    return [
        ("header_upscaled", header_upscaled),
        ("header_binary", header_binary),
        ("full_gray", full_gray),
    ]


def _payload_score(payload: dict[str, Any]) -> int:
    paciente = payload.get("paciente", {}) if isinstance(payload, dict) else {}
    if not isinstance(paciente, dict):
        return 0

    keys = ("nome", "tutor", "data_exame", "especie", "raca", "sexo", "idade")
    return sum(1 for key in keys if str(paciente.get(key, "")).strip())


def parse_image_header_import_content(filename: str | None, content: bytes) -> dict[str, Any]:
    validate_image_import_filename(filename)
    validate_image_import_size(content)

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception as exc:
        raise ValueError("Nao foi possivel abrir a imagem enviada.") from exc

    best_payload: dict[str, Any] | None = None
    best_score = -1
    best_variant = ""
    last_error: Exception | None = None

    for variant_name, variant_image in _build_image_variants(image):
        try:
            ocr_text = _extract_text_with_tesseract(variant_image)
        except ValueError as exc:
            if "tesseract ocr nao encontrado" in str(exc).lower():
                raise
            last_error = exc
            continue

        if not ocr_text.strip():
            continue

        payload = parse_image_header_text(ocr_text)
        score = _payload_score(payload)
        if score > best_score:
            best_payload = payload
            best_score = score
            best_variant = variant_name

    if not best_payload:
        if last_error:
            raise ValueError(str(last_error)) from last_error
        raise ValueError("Nao foi possivel reconhecer texto na imagem.")

    paciente = best_payload.get("paciente", {}) if isinstance(best_payload, dict) else {}
    has_header_fields = bool(
        str(paciente.get("nome", "")).strip()
        or str(paciente.get("tutor", "")).strip()
        or str(paciente.get("data_exame", "")).strip()
    )
    if not has_header_fields:
        raise ValueError("Nao foi possivel identificar os campos do cabecalho na imagem.")

    best_payload["meta_importacao_imagem"] = {
        "score": best_score,
        "variant": best_variant,
    }
    return best_payload
