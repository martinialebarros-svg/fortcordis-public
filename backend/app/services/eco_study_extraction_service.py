from __future__ import annotations

import io
import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from PIL import Image, ImageOps

from app.services.image_header_import_service import _extract_text_with_tesseract

MAX_ECO_STUDY_IMPORT_SIZE = 30 * 1024 * 1024
MAX_ECO_STUDY_PDF_PAGES = 20
ECO_STUDY_EXTRACTOR_VERSION = "8"
GE_LOGIQ_E_PROFILE = "ge_logiq_e"
GE_VIVID_IQ_PROFILE = "ge_vivid_iq"
ALLOWED_ECO_STUDY_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".pdf",
}

_NUMBER_PATTERN = r"-?\d{1,5}(?:[.,]\d+)?"
_UNIT_PATTERN = r"(?:mmHg|cm/s|m/s|msec|cms|mis|mm|cm|ms|s|%|mlg|mL|ml)?"
_DATE_VALUE_PATTERN = r"(?:\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})"
_BIRTHDATE_LABEL_PATTERN = r"(?:birth\s*date|date\s+of\s+birth|dob|data\s+de\s+nascimento|nascimento)"
_EXAM_DATE_LABEL_PATTERN = r"(?:study\s+date|exam(?:ination)?\s+date|date\s+of\s+exam|data\s+do\s+exame|data\s+exame)"
_LVOT_LABEL = r"(?:VSVE|LVOT|via\s+de\s+saida\s+(?:do\s+)?(?:VE|ventriculo\s+esquerdo))"
_RVOT_LABEL = r"(?:VSVD|RVOT|via\s+de\s+saida\s+(?:do\s+)?(?:VD|ventriculo\s+direito))"
_AORTIC_LABEL = r"(?:AV|Ao|Aorta|fluxo\s+aortico)"
_PULMONARY_LABEL = r"(?:PV|Pulm(?:onar|onic)?|fluxo\s+pulmonar)"
_OUTFLOW_FIELDS = frozenset(
    f"{prefix}_{site}"
    for prefix in ("Vmax", "Grad")
    for site in ("VSVE", "aorta", "VSVD", "pulmonar")
)
_OUTFLOW_SITE_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_])(?:"
    rf"(?P<VSVE>{_LVOT_LABEL})|(?P<aorta>{_AORTIC_LABEL})|"
    rf"(?P<VSVD>{_RVOT_LABEL})|(?P<pulmonar>{_PULMONARY_LABEL})"
    rf")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def _has_ambiguous_outflow_label(line: str) -> bool:
    sites = list(_OUTFLOW_SITE_PATTERN.finditer(line))
    for previous, following in zip(sites, sites[1:]):
        separator = line[previous.end():following.start()]
        if previous.lastgroup != following.lastgroup and re.fullmatch(
            r"(?:\s*[/\\|()\-]\s*|\s+(?:ou|or)\s+)", separator, re.IGNORECASE,
        ):
            return True
    return False


def _outflow_velocity_aliases(site: str) -> tuple[str, ...]:
    site = rf"{site}(?:\s*/\s*{site})*"
    return (rf"Vmax\s*{site}", rf"{site}\s*(?:Vmax|Veloc(?:idade)?\s*max)(?:\s*P)?")


def _outflow_gradient_aliases(site: str) -> tuple[str, ...]:
    site = rf"{site}(?:\s*/\s*{site})*"
    return (
        rf"(?:Grad(?:iente)?\.?(?:\s*max)?|(?:max\s*)?PG)\s*{site}",
        rf"{site}\s*(?:(?:max\s*)?PG|Grad(?:iente)?(?:\s*max)?)",
    )


@dataclass(frozen=True)
class MeasurementDefinition:
    campo: str
    rotulo: str
    aliases: tuple[str, ...]
    unit_kind: str


MEASUREMENT_DEFINITIONS: tuple[MeasurementDefinition, ...] = (
    MeasurementDefinition("AE_Ao", "AE/Ao", (r"(?:AE|LA)\s*/\s*Ao", r"LA\s*Ao\s*Ratio"), "ratio"),
    MeasurementDefinition("AP_Ao", "AP/Ao", (r"(?:AP|PA)\s*/\s*Ao",), "ratio"),
    MeasurementDefinition("E_TRIV", "E/TRIV", (r"(?:Relacao\s*)?E\s*/\s*(?:TRIV|IVRT)", r"E\s*(?:TRIV|IVRT)\s*Ratio"), "ratio"),
    MeasurementDefinition("E_A", "E/A", (r"Relacao\s*E\s*/\s*A\s*VM", r"E\s*/\s*A\s*VM", r"(?:MV\s*)?E\s*/\s*A", r"E\s*A\s*Ratio"), "ratio"),
    MeasurementDefinition("doppler_tecidual_relacao", "e'/a'", (r"e['′]?\s*/\s*a['′]?",), "ratio"),
    MeasurementDefinition("E_E_linha", "E/e'", (r"E\s*/\s*e['′]?",), "ratio"),
    MeasurementDefinition("DIVEd_normalizado", "DIVEd N", (r"DIVEd\s*N", r"DIVdN", r"LVIDd\s*N"), "ratio"),
    MeasurementDefinition("DIVEd", "DIVEd", (r"LVIDd", r"DIVEd", r"LVID\s*d"), "length"),
    MeasurementDefinition("DIVES", "DIVEs", (r"LVIDs", r"DIVES", r"LVID\s*s"), "length"),
    MeasurementDefinition("SIVd", "SIVd", (r"IVSd", r"SIVd"), "length"),
    MeasurementDefinition("SIVs", "SIVs", (r"IVSs", r"SIVs"), "length"),
    MeasurementDefinition("PLVEd", "PLVEd", (r"LVPWd", r"PLVEd", r"PPVEd", r"PWd"), "length"),
    MeasurementDefinition("PLVES", "PLVEs", (r"LVPWs", r"PLVES", r"PPVEs", r"PWs"), "length"),
    MeasurementDefinition("VDF", "VDF", (r"EDV", r"VDF\s*\(?Teich\)?", r"VDF"), "volume"),
    MeasurementDefinition("VSF", "VSF", (r"ESV", r"VSF\s*\(?Teich\)?", r"VSF"), "volume"),
    MeasurementDefinition("FE_Teicholz", "FE", (r"EF\s*\(?Teich(?:holz)?\)?", r"FE\s*\(?Teich(?:holz)?\)?", r"\bEF\b", r"\bFE\b"), "percent"),
    MeasurementDefinition("DeltaD_FS", "FS", (r"FS", r"(?:%\s*)?Delta\s*D", r"FEnc"), "percent"),
    MeasurementDefinition("TAPSE", "TAPSE", (r"TAPSE",), "length"),
    MeasurementDefinition("MAPSE", "MAPSE", (r"MAPSE",), "length"),
    MeasurementDefinition("Atrio_esquerdo", "Atrio esquerdo", (r"LA\s*(?:Diam(?:eter)?|Dimension)", r"(?:Diam|Diametro)\s*AE", r"D\.?\s*AE", r"AE\s*(?:Diam|Dimensao)", r"Atrio\s*Esquerdo"), "length"),
    MeasurementDefinition("AE_diametro_max", "AE diametro maximo", (r"LAD\s*max", r"(?:AE|LA)\s*(?:Diam(?:etro|eter)?|Dimensao|Dimension)\s*max"), "length"),
    MeasurementDefinition("AE_diametro_min", "AE diametro minimo", (r"LAD\s*min", r"(?:AE|LA)\s*(?:Diam(?:etro|eter)?|Dimensao|Dimension)\s*min"), "length"),
    MeasurementDefinition("Fracao_encurtamento_AE", "Fracao encurtamento AE", (r"(?:LA|AE)[-\s]*FS", r"LAFS", r"Fracao\s*de\s*encurtamento\s*(?:do\s*)?AE"), "percent"),
    MeasurementDefinition("Fluxo_auricular", "Velocidade apendice atrial esquerdo", (r"(?:LAA|LAapp)\s*(?:max|peak|Vmax)", r"(?:Apendice|Auricula)\s*Atrial\s*Esquerda\s*(?:Vmax|Veloc(?:idade)?)"), "velocity"),
    MeasurementDefinition("Aorta", "Aorta", (r"D\.?\s*Raiz\s*Ao", r"(?:Diametro\s*)?Raiz\s*Ao", r"Ao\s*(?:Diam(?:eter)?|Dimension)", r"Aorta"), "length"),
    MeasurementDefinition("Onda_E", "Onda E", (r"Veloc(?:id)?\.?\s*E\s*VM", r"MV\s*E(?:\s*Vel(?:ocity)?)?", r"Onda\s*E"), "velocity"),
    MeasurementDefinition("Onda_A", "Onda A", (r"Veloc(?:id)?\.?\s*A\s*VM", r"MV\s*A(?:\s*Vel(?:ocity)?)?", r"Onda\s*A"), "velocity"),
    MeasurementDefinition("TD", "TD", (r"T\.?\s*des(?:ac)?\.?\s*VM", r"MV\s*DT", r"Decel(?:eration)?\s*Time", r"\bTD\b"), "time"),
    MeasurementDefinition("TRIV", "TRIV", (r"IVRT", r"(?<!/)TRIV"), "time"),
    MeasurementDefinition("e_doppler", "e'", (r"TDI\s*e['′]?", r"e['′]\s*(?:Vel(?:ocity)?)?"), "velocity"),
    MeasurementDefinition("a_doppler", "a'", (r"TDI\s*a['′]?", r"a['′]\s*(?:Vel(?:ocity)?)?", r"(?:^|\d\s*)a['′]?"), "velocity"),
    MeasurementDefinition("IM_Vmax", "IM Vmax", (r"(?:MR|RM|IM)\s*Vmax", r"Vmax\s*(?:MR|RM|IM)"), "velocity"),
    MeasurementDefinition(
        "IT_Vmax",
        "IT Vmax",
        (r"(?:TR|IT|RT)\s*Vmax", r"Vmax\s*(?:TR|IT|RT)"),
        "velocity",
    ),
    MeasurementDefinition("IA_Vmax", "IA Vmax", (r"(?:AR|IA)\s*Vmax",), "velocity"),
    MeasurementDefinition("IP_Vmax", "IP Vmax", (r"(?:PR|IP)\s*Vmax",), "velocity"),
    MeasurementDefinition("Vmax_VSVE", "Vmax via de saida VE", _outflow_velocity_aliases(_LVOT_LABEL), "velocity"),
    MeasurementDefinition("Grad_VSVE", "Gradiente via de saida VE", _outflow_gradient_aliases(_LVOT_LABEL), "pressure"),
    MeasurementDefinition("Vmax_aorta", "Vmax aorta", _outflow_velocity_aliases(_AORTIC_LABEL), "velocity"),
    MeasurementDefinition("Grad_aorta", "Gradiente aorta", _outflow_gradient_aliases(_AORTIC_LABEL), "pressure"),
    MeasurementDefinition("Vmax_VSVD", "Vmax via de saida VD", _outflow_velocity_aliases(_RVOT_LABEL), "velocity"),
    MeasurementDefinition("Grad_VSVD", "Gradiente via de saida VD", _outflow_gradient_aliases(_RVOT_LABEL), "pressure"),
    MeasurementDefinition("Vmax_pulmonar", "Vmax pulmonar", _outflow_velocity_aliases(_PULMONARY_LABEL), "velocity"),
    MeasurementDefinition("Grad_pulmonar", "Gradiente pulmonar", _outflow_gradient_aliases(_PULMONARY_LABEL), "pressure"),
)

_LV_TECHNIQUE_FIELDS = {
    "DIVEd",
    "DIVEd_normalizado",
    "DIVES",
    "SIVd",
    "SIVs",
    "PLVEd",
    "PLVES",
    "VDF",
    "VSF",
    "FE_Teicholz",
    "DeltaD_FS",
}


def _detect_lv_measurement_technique(text: str) -> str | None:
    normalized = re.sub(
        r"\s+",
        " ",
        _remove_diacritics(text or "").lower(),
    ).strip()
    if re.fullmatch(r"(?:modo\s*)?2d", normalized) or re.search(
        r"(?:^|[^a-z0-9])(?:2d\s*/|modo\s*2d\b|2d\s+)",
        normalized,
    ):
        return "2d"
    if re.fullmatch(r"(?:m-?mode|modo\s*m|mm)", normalized) or re.search(
        r"(?:^|[^a-z0-9])(?:mm\s*/|m-?mode\b|modo\s*m\b|mm\s+)",
        normalized,
    ):
        return "modo_m"
    return None


def _ends_lv_measurement_section(text: str) -> bool:
    normalized = re.sub(
        r"\s+",
        " ",
        _remove_diacritics(text or "").lower(),
    ).strip(" :-")
    return bool(
        re.fullmatch(
            r"(?:doppler|funcao\s+diastolica|diastolica|regurgitacoes?|"
            r"valvas?|achados?|conclusoes?)",
            normalized,
        )
    )


def normalize_eco_study_filename(filename: str | None) -> str:
    return os.path.basename((filename or "").strip()) or "estudo.png"


def validate_eco_study_filename(filename: str | None) -> str:
    normalized = normalize_eco_study_filename(filename)
    extension = os.path.splitext(normalized)[1].lower()
    if extension not in ALLOWED_ECO_STUDY_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_ECO_STUDY_EXTENSIONS))
        raise ValueError(f"Arquivo deve ser imagem ou PDF ({allowed})")
    return normalized


def validate_eco_study_size(content: bytes) -> None:
    if len(content) > MAX_ECO_STUDY_IMPORT_SIZE:
        raise ValueError("Estudo excede o limite de 30MB")


def _remove_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    without_diacritics = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    apostrophes = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})
    return without_diacritics.translate(apostrophes)


def _empty_patient_payload() -> dict[str, str]:
    return {
        "nome": "",
        "tutor": "",
        "raca": "",
        "especie": "",
        "peso": "",
        "idade": "",
        "sexo": "",
        "telefone": "",
        "data_exame": "",
    }


def _parse_date_value(
    value: str,
    *,
    upper_bound: date | None = None,
) -> date | None:
    parts = re.split(r"[./-]", (value or "").strip())
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None

    first, second, third = (int(part) for part in parts)
    if len(parts[0]) == 4:
        candidates = [(first, second, third)]
    else:
        year = third + (2000 if third < 100 else 0)
        if first > 12:
            candidates = [(year, second, first)]
        elif second > 12:
            candidates = [(year, first, second)]
        else:
            # Brazilian reports normally use day/month/year. The second option
            # still supports month/day/year when only that interpretation is
            # compatible with the reference date.
            candidates = [(year, second, first), (year, first, second)]

    parsed: list[date] = []
    for year, month, day in candidates:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if upper_bound is None or candidate <= upper_bound:
            parsed.append(candidate)
    return parsed[0] if parsed else None


def _find_labeled_date(
    text: str,
    label_pattern: str,
    *,
    upper_bound: date | None = None,
) -> tuple[date | None, tuple[int, int] | None]:
    match = re.search(
        rf"\b{label_pattern}\b\s*[:=-]?\s*(?P<value>{_DATE_VALUE_PATTERN})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return _parse_date_value(match.group("value"), upper_bound=upper_bound), match.span()


def _extract_exam_date(text: str, *, upper_bound: date | None = None) -> date | None:
    limit = upper_bound or date.today()
    labeled, _ = _find_labeled_date(
        text,
        _EXAM_DATE_LABEL_PATTERN,
        upper_bound=limit,
    )
    if labeled:
        return labeled

    # LOGIQ headers often show the examination date without a label. Remove a
    # labeled birthdate before falling back to the first remaining date so it
    # can never be mistaken for the study date.
    _, birthdate_span = _find_labeled_date(text, _BIRTHDATE_LABEL_PATTERN)
    remaining = text
    if birthdate_span:
        start, end = birthdate_span
        remaining = f"{text[:start]} {text[end:]}"
    for match in re.finditer(_DATE_VALUE_PATTERN, remaining):
        parsed = _parse_date_value(match.group(0), upper_bound=limit)
        if parsed:
            return parsed
    return None


def _format_age_from_birthdate(birthdate: date, reference_date: date) -> str:
    if birthdate > reference_date:
        return ""

    years = reference_date.year - birthdate.year
    if (reference_date.month, reference_date.day) < (birthdate.month, birthdate.day):
        years -= 1
    if years >= 1:
        return f"{years} ano" if years == 1 else f"{years} anos"

    months = (reference_date.year - birthdate.year) * 12
    months += reference_date.month - birthdate.month
    if reference_date.day < birthdate.day:
        months -= 1
    months = max(0, months)
    return f"{months} mês" if months == 1 else f"{months} meses"


def parse_patient_age_weight(
    text: str,
    *,
    reference_date: date | None = None,
) -> dict[str, str]:
    """Extract patient weight and calculate age from a labeled birthdate.

    The study import also sees Doppler measurements in kilograms and years in
    free text. Restricting the match to the usual demographic labels prevents
    those clinical values from being copied into the patient record.
    """
    normalized_text = _remove_diacritics(text or "")
    effective_reference = (
        _extract_exam_date(normalized_text, upper_bound=reference_date or date.today())
        or reference_date
        or date.today()
    )
    birthdate, _ = _find_labeled_date(
        normalized_text,
        _BIRTHDATE_LABEL_PATTERN,
        upper_bound=effective_reference,
    )
    age_match = re.search(
        r"\b(?:idade|age)\s*[:=-]?\s*(\d{1,2})\s*(?:anos?|ano|a|years?|year|y)\b",
        normalized_text,
        re.IGNORECASE,
    )
    weight_match = re.search(
        r"\b(?:peso(?:\s+corporal)?|weight|wt)\s*[:=-]?\s*(\d{1,3}(?:[.,]\d{1,3})?)\s*(?:kg|kgs?)\b",
        normalized_text,
        re.IGNORECASE,
    )

    weight = ""
    if weight_match:
        value = _parse_number(weight_match.group(1))
        if 0 < value <= 300:
            weight = str(int(value)) if value.is_integer() else f"{value:g}"

    age = _format_age_from_birthdate(birthdate, effective_reference) if birthdate else ""
    if not age and age_match:
        years = int(age_match.group(1))
        age = f"{years} ano" if years == 1 else f"{years} anos"

    return {
        "idade": age,
        "peso": weight,
        # Preserve observed birthdate: a calculated age is not a declaration.
        **({"data_nascimento": birthdate.isoformat()} if birthdate else {}),
    }


def _merge_patient_age_weight(patient: dict[str, Any], text: str) -> dict[str, Any]:
    merged = dict(patient or _empty_patient_payload())
    exam_date = _extract_exam_date(_remove_diacritics(text or ""))
    if exam_date and not merged.get("data_exame"):
        merged["data_exame"] = exam_date.isoformat()
    reference_date = exam_date
    if merged.get("data_exame"):
        try:
            reference_date = date.fromisoformat(str(merged["data_exame"])[:10])
        except ValueError:
            pass
    demographics = parse_patient_age_weight(text, reference_date=reference_date)
    for field, value in demographics.items():
        if value and (field == "idade" or not merged.get(field)):
            merged[field] = value
    return merged


def _ge_vivid_iq_profile_payload() -> dict[str, Any]:
    return {
        "paciente": _empty_patient_payload(),
        "clinica": "",
        "veterinario_solicitante": "",
        "fc": "",
        "perfil": GE_VIVID_IQ_PROFILE,
        "fabricante": "GE",
        "modelo_equipamento": "Vivid IQ",
    }


def parse_ge_vivid_iq_report_text(text: str) -> dict[str, Any] | None:
    normalized_text = _remove_diacritics(text or "")
    upper_text = normalized_text.upper()
    if "GE HEALTHCARE" not in upper_text or "CARDIAC REPORT" not in upper_text:
        return None
    report_markers = (
        "D.RAIZ AO",
        "MAXPG VSVE",
        "VELOC. E VM",
        "T.DES. VM",
        "DIVED",
    )
    if sum(marker in upper_text for marker in report_markers) < 2:
        return None
    return _ge_vivid_iq_profile_payload()


def _looks_like_ge_vivid_iq_screen_text(text: str) -> bool:
    normalized_text = _remove_diacritics(text or "").upper()
    words = re.sub(r"[^A-Z0-9]+", " ", normalized_text)
    if "NOVAMENTE" in words and "REPROD" in words:
        return True

    markers = (
        r"\bD\s+RAIZ\s*AO\b",
        r"\bMAX\s*PG\s*VSVE\b",
        r"\bMAX\s*PG\s*VSVD\b",
        r"\bVELOC\s+E\s+VM\b",
        r"\bT\s+DES\s+VM\b",
        r"\bDIVDN\b",
        r"\bDIVES\b",
        r"\bSIVS\b",
        r"\bPPVED\b",
        r"\bPPVES\b",
    )
    return sum(bool(re.search(marker, words)) for marker in markers) >= 2


def parse_ge_logiq_e_header_text(text: str) -> dict[str, Any] | None:
    normalized_text = _remove_diacritics(text or "")
    if "VET WORLD" not in normalized_text.upper():
        return None

    lines = [re.sub(r"\s+", " ", line).strip() for line in normalized_text.splitlines()]
    identity_line = next(
        (
            line
            for line in lines
            if "," in line
            and "VET WORLD" not in line.upper()
            and not re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", line)
        ),
        "",
    )
    if not identity_line:
        identity_match = re.search(
            r"VET\s+WORLD\s+([A-Z][A-Z\s'-]{1,40},\s*[A-Z][A-Z\s'-]{1,60}?)(?=\s+MI\s*\d|\s+TIs|\s+6S|\n|$)",
            normalized_text,
            re.IGNORECASE,
        )
        identity_line = identity_match.group(1).strip() if identity_match else ""

    patient_name = ""
    tutor_name = ""
    if identity_line and "," in identity_line:
        patient_name, tutor_name = [part.strip().title() for part in identity_line.split(",", 1)]

    parsed_exam_date = _extract_exam_date(normalized_text)
    exam_date = parsed_exam_date.isoformat() if parsed_exam_date else ""

    species = "Canina" if re.search(r"CAO[_\s-]*P", normalized_text, re.IGNORECASE) else ""
    patient = _merge_patient_age_weight(
        {
            "nome": patient_name,
            "tutor": tutor_name,
            "raca": "",
            "especie": species,
            "peso": "",
            "idade": "",
            "sexo": "",
            "telefone": "",
            "data_exame": exam_date,
        },
        normalized_text,
    )
    return {
        "paciente": patient,
        "clinica": "VET WORLD",
        "veterinario_solicitante": "",
        "fc": "",
        "perfil": GE_LOGIQ_E_PROFILE,
        "fabricante": "GE",
        "modelo_equipamento": "LOGIQ e",
    }


def _parse_number(value: str) -> float:
    return float((value or "").replace(" ", "").replace(",", "."))


def _normalize_unit(unit: str) -> str:
    normalized = (unit or "").strip().lower().replace("msec", "ms")
    if normalized == "mmhg":
        return "mmHg"
    if normalized == "mis":
        return "m/s"
    if normalized == "cms":
        return "cm"
    if normalized == "mlg":
        return "mL"
    if normalized == "ml":
        return "mL"
    return normalized


def _normalize_measurement_value(value: float, unit: str, unit_kind: str) -> tuple[float, str]:
    normalized_unit = _normalize_unit(unit)

    if unit_kind == "length":
        if normalized_unit == "cm":
            return value * 10.0, "mm"
        return value, "mm" if normalized_unit in {"", "mm"} else normalized_unit
    if unit_kind == "velocity":
        if normalized_unit == "cm/s":
            return value / 100.0, "m/s"
        return value, "m/s" if normalized_unit in {"", "m/s"} else normalized_unit
    if unit_kind == "time":
        if normalized_unit == "s":
            return value * 1000.0, "ms"
        return value, "ms" if normalized_unit in {"", "ms"} else normalized_unit
    if unit_kind == "percent":
        return value, "%"
    if unit_kind == "volume":
        return value, "mL" if normalized_unit in {"", "mL"} else normalized_unit
    if unit_kind == "pressure":
        return value, "mmHg" if not normalized_unit else normalized_unit
    return value, ""


def _round_measurement(value: float) -> float:
    rounded = round(value, 3)
    return int(rounded) if rounded.is_integer() else rounded


def _augment_ocr_lines(lines: list[str]) -> list[str]:
    augmented = list(lines)
    for index in range(len(lines) - 1):
        current = lines[index]
        following = lines[index + 1]
        if not re.search(r"[A-Za-z]", current):
            continue
        if re.match(rf"^\s*{_NUMBER_PATTERN}\s*{_UNIT_PATTERN}\s*$", following, re.IGNORECASE):
            augmented.append(f"{current} {following}")
    return augmented


def extract_measurements_from_text(
    text: str,
    *,
    page: int = 1,
    source: str = "ocr",
    confidence: float = 0.82,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
    if source.startswith("ocr"):
        lines = _augment_ocr_lines([line for line in lines if line])

    active_lv_technique: str | None = None
    for raw_line in lines:
        if not raw_line:
            continue
        line_technique = _detect_lv_measurement_technique(raw_line)
        if line_technique is not None:
            active_lv_technique = line_technique
        elif _ends_lv_measurement_section(raw_line):
            active_lv_technique = None
        line = _remove_diacritics(raw_line)
        ambiguous_outflow_label = _has_ambiguous_outflow_label(line)
        for definition in MEASUREMENT_DEFINITIONS:
            if definition.campo in _OUTFLOW_FIELDS and ambiguous_outflow_label:
                # A combined RVOT/Pulmonic (or LVOT/Aorta) label does not
                # establish which acquisition site supports the value.
                continue
            matched = False
            for alias in definition.aliases:
                pattern = re.compile(
                    rf"(?<![A-Za-z0-9_])(?P<label>{alias})(?![A-Za-z0-9_])"
                    rf"\s*(?:[:=\-]|\s)\s*(?P<value>{_NUMBER_PATTERN})\s*(?P<unit>{_UNIT_PATTERN})",
                    re.IGNORECASE,
                )
                match = pattern.search(line)
                if not match:
                    continue

                original_value = _parse_number(match.group("value"))
                original_unit = _normalize_unit(match.group("unit"))
                if definition.campo == "Aorta" and (
                    original_unit not in {"", "mm", "cm"}
                    or re.search(
                        r"(?:Vmax|(?:max\s*)?PG|Grad(?:iente)?\.?(?:\s*max)?)\s*$",
                        line[:match.start("label")],
                        re.IGNORECASE,
                    )
                ):
                    # A generic anatomical label must not duplicate an
                    # explicitly labeled flow velocity or gradient.
                    continue
                if definition.unit_kind == "velocity" and original_unit not in {"m/s", "cm/s"}:
                    continue
                normalized_value, normalized_unit = _normalize_measurement_value(
                    original_value,
                    original_unit,
                    definition.unit_kind,
                )
                technique = (
                    line_technique or active_lv_technique
                    if definition.campo in _LV_TECHNIQUE_FIELDS
                    else None
                )
                target_field = (
                    f"{definition.campo}_2D"
                    if technique == "2d"
                    else definition.campo
                )
                candidates.append(
                    {
                        "campo": target_field,
                        "rotulo": (
                            f"{definition.rotulo} (2D)"
                            if technique == "2d"
                            else (
                                f"{definition.rotulo} (Modo M)"
                                if technique == "modo_m"
                                else definition.rotulo
                            )
                        ),
                        "valor": (
                            normalized_value
                            if definition.campo in _OUTFLOW_FIELDS
                            else _round_measurement(normalized_value)
                        ),
                        "unidade": normalized_unit,
                        "valor_original": (
                            original_value
                            if definition.campo in _OUTFLOW_FIELDS
                            else _round_measurement(original_value)
                        ),
                        "unidade_original": original_unit,
                        "confianca": round(max(0.0, min(1.0, confidence)), 3),
                        "pagina": page,
                        "texto_origem": raw_line,
                        "rotulo_origem": raw_line[match.start("label"):match.end("label")],
                        "origem": source,
                        "tecnica": technique,
                        "status": "candidata",
                    }
                )
                matched = True
                break
            if matched:
                continue

    return candidates


def _candidate_values_compatible(values: Iterable[float]) -> bool:
    items = [float(value) for value in values]
    if len(items) <= 1:
        return True
    lower = min(items)
    upper = max(items)
    tolerance = max(0.02, abs(lower) * 0.01)
    return upper - lower <= tolerance


def consolidate_measurement_candidates(
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, float], list[dict[str, Any]], int]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[str(candidate["campo"])].append(dict(candidate))

    measurements: dict[str, float] = {}
    consolidated: list[dict[str, Any]] = []
    conflict_count = 0

    for field, items in grouped.items():
        compatible = _candidate_values_compatible(float(item["valor"]) for item in items)
        ranked = sorted(items, key=lambda item: float(item.get("confianca", 0)), reverse=True)
        if compatible:
            selected = ranked[0]
            selected["status"] = "sugerida"
            measurements[field] = selected["valor"]
            consolidated.append(selected)
            for duplicate in ranked[1:]:
                duplicate["status"] = "duplicada"
                consolidated.append(duplicate)
        else:
            conflict_count += 1
            for item in ranked:
                item["status"] = "conflito"
                consolidated.append(item)

    consolidated.sort(key=lambda item: (int(item.get("pagina") or 1), str(item.get("campo"))))
    return measurements, consolidated, conflict_count


def _build_ocr_variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    base = ImageOps.exif_transpose(image).convert("RGB")
    gray = ImageOps.grayscale(base)
    width, height = gray.size
    scale = 2 if max(width, height) < 2600 else 1
    upscaled = gray.resize((width * scale, height * scale)) if scale > 1 else gray
    inverted = ImageOps.invert(upscaled)
    binary = inverted.point(lambda px: 255 if px > 150 else 0, mode="1").convert("L")
    return [("gray", upscaled), ("inverted", inverted), ("binary", binary)]


def _build_measurement_regions(image: Image.Image) -> list[tuple[str, Image.Image]]:
    base = ImageOps.exif_transpose(image).convert("RGB")
    width, height = base.size
    if width < 500 or height < 350:
        return []
    return [
        (
            "left_top",
            base.crop((0, max(0, int(height * 0.09)), min(width, int(width * 0.43)), min(height, int(height * 0.68)))),
        ),
        (
            "left_bottom",
            base.crop((0, max(0, int(height * 0.77)), min(width, int(width * 0.43)), height)),
        ),
    ]


def _extract_ge_logiq_e_header_from_image(image: Image.Image) -> dict[str, Any] | None:
    base = ImageOps.exif_transpose(image).convert("RGB")
    width, height = base.size
    if width < 500 or height < 300:
        return None
    header_height = max(45, min(height, int(height * 0.10)))
    header = base.crop((0, 0, width, header_height)).resize((width * 3, header_height * 3))
    prepared = ImageOps.autocontrast(ImageOps.grayscale(header))
    try:
        text = _extract_text_with_tesseract(prepared, psm=11)
    except Exception:
        return None
    return parse_ge_logiq_e_header_text(text)


def _extract_ge_vivid_iq_report_from_image(image: Image.Image) -> dict[str, Any] | None:
    base = ImageOps.exif_transpose(image).convert("RGB")
    width, height = base.size
    if width < 500 or height < 500:
        return None
    header_height = min(height, int(height * 0.28))
    header = base.crop((0, 0, width, header_height)).resize((width * 2, header_height * 2))
    prepared = ImageOps.autocontrast(ImageOps.grayscale(header))
    try:
        text = _extract_text_with_tesseract(prepared, psm=11)
    except Exception:
        return None
    return parse_ge_vivid_iq_report_text(text)


def _extract_patient_age_weight_from_image(image: Image.Image) -> dict[str, str]:
    """Best-effort OCR for demographics when a PDF has no usable text layer."""
    base = ImageOps.exif_transpose(image).convert("RGB")
    width, height = base.size
    if width < 500 or height < 300:
        return {}
    scale = 2 if max(width, height) < 2600 else 1
    prepared = ImageOps.autocontrast(ImageOps.grayscale(base.resize((width * scale, height * scale))))
    try:
        return parse_patient_age_weight(_extract_text_with_tesseract(prepared, psm=11))
    except Exception:
        return {}


def _extract_ge_vivid_iq_screen_candidates(
    image: Image.Image,
    *,
    page: int,
) -> tuple[bool, list[dict[str, Any]], str]:
    base = ImageOps.exif_transpose(image).convert("RGB")
    width, height = base.size
    if width < 500 or height < 350:
        return False, [], ""

    panel = base.crop((0, 0, min(width, int(width * 0.32)), height))
    panel_scale = 3 if max(panel.size) < 1800 else 2
    panel = panel.resize((panel.width * panel_scale, panel.height * panel_scale))
    panel_gray = ImageOps.autocontrast(ImageOps.grayscale(panel))
    try:
        panel_text = _extract_text_with_tesseract(panel_gray, psm=11)
    except Exception:
        return False, [], ""
    if not _looks_like_ge_vivid_iq_screen_text(panel_text):
        return False, [], ""

    candidates = extract_measurements_from_text(
        panel_text,
        page=page,
        source="ocr:vivid_iq:left_panel_gray_psm11",
        confidence=0.98,
    )
    variants = ["vivid_iq:left_panel_gray_psm11"]

    measurement_box = base.crop(
        (
            0,
            max(0, int(height * 0.06)),
            min(width, int(width * 0.31)),
            min(height, int(height * 0.45)),
        )
    )
    measurement_box = measurement_box.resize(
        (measurement_box.width * 5, measurement_box.height * 5)
    )
    measurement_box_gray = ImageOps.autocontrast(ImageOps.grayscale(measurement_box))
    try:
        box_text = _extract_text_with_tesseract(measurement_box_gray, psm=6)
    except Exception:
        box_text = ""
    if box_text:
        candidates.extend(
            extract_measurements_from_text(
                box_text,
                page=page,
                source="ocr:vivid_iq:measurement_box_gray_psm6",
                confidence=0.96,
            )
        )
        variants.append("vivid_iq:measurement_box_gray_psm6")

    return True, _keep_most_reliable_candidates(candidates), ",".join(variants)


def _build_region_ocr_passes(region: Image.Image) -> list[tuple[str, Image.Image, int, float]]:
    width, height = region.size
    scale = 5 if height < 220 else (4 if max(width, height) < 800 else 2)
    resized = region.resize((max(1, width * scale), max(1, height * scale)))
    gray = ImageOps.autocontrast(ImageOps.grayscale(resized))
    inverted = ImageOps.invert(gray)
    blue = ImageOps.autocontrast(resized.getchannel("B"))
    binary = inverted.point(lambda px: 255 if px > 150 else 0, mode="1").convert("L")
    inverted_threshold_120 = inverted.point(lambda px: 255 if px > 120 else 0, mode="1").convert("L")
    gray_threshold_180 = gray.point(lambda px: 255 if px > 180 else 0, mode="1").convert("L")
    return [
        ("inverted_psm6", inverted, 6, 0.93),
        ("gray_psm6", gray, 6, 0.90),
        ("gray_psm12", gray, 12, 0.89),
        ("blue_psm11", blue, 11, 0.86),
        ("inverted_threshold120_psm6", inverted_threshold_120, 6, 0.88),
        ("gray_threshold180_psm6", gray_threshold_180, 6, 0.84),
        ("binary_psm6", binary, 6, 0.78),
    ]


def _keep_most_reliable_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[str(candidate["campo"])].append(candidate)

    selected: list[dict[str, Any]] = []
    for field, items in grouped.items():
        # E/e' is displayed with two decimals by this profile. High-contrast OCR
        # can erase only the last digit, so preserve a complete lower-confidence read.
        if field == "E_E_linha":
            decimal_places = [
                len(str(item.get("valor_original", "")).partition(".")[2].rstrip("0"))
                for item in items
            ]
            if max(decimal_places, default=0) >= 2:
                items = [item for item, places in zip(items, decimal_places) if places >= 2]
        highest_confidence = max(float(item.get("confianca", 0)) for item in items)
        selected.extend(
            item
            for item in items
            if abs(float(item.get("confianca", 0)) - highest_confidence) < 0.001
        )
    return selected


def _extract_candidates_from_region(
    region: Image.Image,
    *,
    page: int,
    region_name: str,
) -> tuple[list[dict[str, Any]], list[str], Exception | None]:
    collected: list[dict[str, Any]] = []
    successful_passes: list[str] = []
    last_error: Exception | None = None
    for pass_name, variant, psm, confidence in _build_region_ocr_passes(region):
        try:
            text = _extract_text_with_tesseract(variant, psm=psm)
        except Exception as exc:
            last_error = exc
            continue
        candidates = extract_measurements_from_text(
            text,
            page=page,
            source=f"ocr:{region_name}:{pass_name}",
            confidence=confidence,
        )
        if candidates:
            successful_passes.append(pass_name)
            collected.extend(candidates)
    return _keep_most_reliable_candidates(collected), successful_passes, last_error


def _extract_candidates_from_image(image: Image.Image, *, page: int) -> tuple[list[dict[str, Any]], str]:
    region_candidates: list[dict[str, Any]] = []
    region_variants: list[str] = []
    last_error: Exception | None = None
    for region_name, region in _build_measurement_regions(image):
        candidates, passes, region_error = _extract_candidates_from_region(
            region,
            page=page,
            region_name=region_name,
        )
        region_candidates.extend(candidates)
        region_variants.extend(f"{region_name}:{pass_name}" for pass_name in passes)
        last_error = region_error or last_error

    if region_candidates:
        return _keep_most_reliable_candidates(region_candidates), ",".join(region_variants)

    best_candidates: list[dict[str, Any]] = []
    best_variant = ""
    for variant_name, variant in _build_ocr_variants(image):
        try:
            text = _extract_text_with_tesseract(variant)
        except Exception as exc:
            last_error = exc
            continue
        candidates = extract_measurements_from_text(
            text,
            page=page,
            source=f"ocr:{variant_name}",
            confidence=0.82,
        )
        if len(candidates) > len(best_candidates):
            best_candidates = candidates
            best_variant = variant_name

    if not best_candidates and last_error:
        raise ValueError(str(last_error)) from last_error
    return best_candidates, best_variant


def _open_image(content: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
        return image
    except Exception as exc:
        raise ValueError("Nao foi possivel abrir a imagem do estudo.") from exc


def _extract_pdf_text_pages(content: bytes) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("Dependencia pypdf nao instalada no servidor.") from exc

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise ValueError("Nao foi possivel abrir o PDF do estudo.") from exc
    if len(reader.pages) > MAX_ECO_STUDY_PDF_PAGES:
        raise ValueError("PDF excede o limite de 20 paginas")
    return [page.extract_text() or "" for page in reader.pages]


def _render_pdf_pages(content: bytes) -> list[Image.Image]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ValueError("Dependencia pypdfium2 nao instalada no servidor.") from exc

    try:
        document = pdfium.PdfDocument(content)
    except Exception as exc:
        raise ValueError("Nao foi possivel renderizar o PDF do estudo.") from exc
    if len(document) > MAX_ECO_STUDY_PDF_PAGES:
        raise ValueError("PDF excede o limite de 20 paginas")

    images: list[Image.Image] = []
    for page in document:
        bitmap = page.render(scale=2.2)
        images.append(bitmap.to_pil())
    return images


def parse_eco_study_import_content(filename: str | None, content: bytes) -> dict[str, Any]:
    normalized_filename = validate_eco_study_filename(filename)
    validate_eco_study_size(content)
    extension = os.path.splitext(normalized_filename)[1].lower()
    candidates: list[dict[str, Any]] = []
    ocr_variants: dict[str, str] = {}
    page_count = 1
    header_payload: dict[str, Any] | None = None

    if extension == ".pdf":
        text_pages = _extract_pdf_text_pages(content)
        page_count = len(text_pages)
        if text_pages:
            header_payload = parse_ge_logiq_e_header_text(text_pages[0]) or parse_ge_vivid_iq_report_text(
                text_pages[0]
            )
            base_patient = (header_payload or {}).get("paciente") or _empty_patient_payload()
            patient = _merge_patient_age_weight(base_patient, text_pages[0])
            if any(patient.values()):
                header_payload = {**(header_payload or {}), "paciente": patient}
        pages_needing_ocr: list[int] = []
        for index, text in enumerate(text_pages, start=1):
            page_candidates = extract_measurements_from_text(
                text,
                page=index,
                source="pdf:text",
                confidence=0.98,
            )
            candidates.extend(page_candidates)
            if not page_candidates:
                pages_needing_ocr.append(index)

        patient = (header_payload or {}).get("paciente") or _empty_patient_payload()
        needs_demographic_ocr = not patient.get("idade") or not patient.get("peso")
        rendered_pages: list[Image.Image] = []
        if pages_needing_ocr or needs_demographic_ocr:
            try:
                rendered_pages = _render_pdf_pages(content)
            except ValueError:
                if pages_needing_ocr:
                    raise
        if rendered_pages:
            if rendered_pages and not header_payload:
                header_payload = _extract_ge_logiq_e_header_from_image(
                    rendered_pages[0]
                ) or _extract_ge_vivid_iq_report_from_image(rendered_pages[0])
            base_patient = (header_payload or {}).get("paciente") or _empty_patient_payload()
            image_demographics = _extract_patient_age_weight_from_image(rendered_pages[0])
            patient = {**base_patient}
            for field, value in image_demographics.items():
                if value and (field == "idade" or not patient.get(field)):
                    patient[field] = value
            if any(patient.values()):
                header_payload = {**(header_payload or {}), "paciente": patient}
            for page_number in pages_needing_ocr:
                page_candidates, variant = _extract_candidates_from_image(
                    rendered_pages[page_number - 1],
                    page=page_number,
                )
                candidates.extend(page_candidates)
                if variant:
                    ocr_variants[str(page_number)] = variant
    else:
        image = _open_image(content)
        header_payload = _extract_ge_logiq_e_header_from_image(image)
        vivid_candidates: list[dict[str, Any]] = []
        vivid_variant = ""
        if not header_payload:
            vivid_detected, vivid_candidates, vivid_variant = _extract_ge_vivid_iq_screen_candidates(
                image,
                page=1,
            )
            if vivid_detected:
                header_payload = _ge_vivid_iq_profile_payload()
        base_patient = (header_payload or {}).get("paciente") or _empty_patient_payload()
        image_demographics = _extract_patient_age_weight_from_image(image)
        patient = {**base_patient}
        for field, value in image_demographics.items():
            if value and (field == "idade" or not patient.get(field)):
                patient[field] = value
        if any(patient.values()):
            header_payload = {**(header_payload or {}), "paciente": patient}
        page_candidates, variant = _extract_candidates_from_image(image, page=1)
        candidates.extend(_keep_most_reliable_candidates(vivid_candidates + page_candidates))
        combined_variants = ",".join(item for item in (vivid_variant, variant) if item)
        if combined_variants:
            ocr_variants["1"] = combined_variants

    measurements, consolidated, conflicts = consolidate_measurement_candidates(candidates)
    if not consolidated:
        raise ValueError("Nenhuma medida ecocardiografica reconhecida no estudo.")

    detected_lv_techniques = sorted(
        {
            str(item.get("tecnica"))
            for item in consolidated
            if item.get("tecnica") in {"modo_m", "2d"}
        }
    )
    measurements_payload: dict[str, Any] = dict(measurements)
    for item in consolidated:
        field = str(item["campo"])
        if field in _OUTFLOW_FIELDS and item.get("status") == "sugerida":
            measurements_payload[f"{field}_origem"] = "importado"
            measurements_payload[f"{field}_rotulo_origem"] = item["rotulo_origem"]
        elif field in _OUTFLOW_FIELDS and item.get("status") == "conflito":
            # A conflict is explicit unresolved evidence, not a missing value:
            # retain a nonnumeric marker so later layers cannot derive a new
            # gradient over competing imported measurements.
            measurements_payload[field] = "Conflito de medidas no exame de origem"
            measurements_payload[f"{field}_origem"] = "importado"
            label_key = f"{field}_rotulo_origem"
            labels = [
                candidate["rotulo_origem"]
                for candidate in consolidated
                if candidate["campo"] == field and candidate.get("status") == "conflito"
            ]
            measurements_payload[label_key] = " | ".join(dict.fromkeys(labels))
    if len(detected_lv_techniques) == 1:
        measurements_payload["VE_tecnica_relatorio"] = detected_lv_techniques[0]

    default_patient = _empty_patient_payload()
    return {
        "paciente": (header_payload or {}).get("paciente") or default_patient,
        "medidas": measurements_payload,
        "medidas_extraidas": consolidated,
        "clinica": (header_payload or {}).get("clinica", ""),
        "veterinario_solicitante": (header_payload or {}).get("veterinario_solicitante", ""),
        "fc": (header_payload or {}).get("fc", ""),
        "meta_importacao_estudo": {
            "versao_extrator": ECO_STUDY_EXTRACTOR_VERSION,
            "formato": extension.lstrip("."),
            "arquivo": normalized_filename,
            "paginas": page_count,
            "medidas_sugeridas": len(measurements),
            "candidatos": len(consolidated),
            "conflitos": conflicts,
            "tecnicas_ve_detectadas": detected_lv_techniques,
            "variantes_ocr": ocr_variants,
            "perfil": (header_payload or {}).get("perfil", "generico"),
            "fabricante": (header_payload or {}).get("fabricante", ""),
            "modelo_equipamento": (header_payload or {}).get("modelo_equipamento", ""),
        },
    }
