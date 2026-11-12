from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.schemas.ai_echo import (
    EchoClinicalStructureOutput,
    EchoFieldSuggestionOutput,
    EchoClinicalWarningOutput,
    EchoMeasurementOutput,
)
from app.services.ai_echo_context import ECHO_MEASUREMENT_UNITS


@dataclass(frozen=True)
class MeasurementPattern:
    label_pattern: str
    canonical_name: str
    display_name: str
    unit: Optional[str]
    target_field_key: Optional[str]
    percentage: bool = False


MEASUREMENT_PATTERNS = (
    MeasurementPattern(
        r"(?:rela[cç][aã]o\s+)?(?:[aá]trio\s+esquerdo\s+(?:(?:a|sobre)\s+|/\s*)?aorta|ae\s*/\s*ao)",
        "la_ao",
        "AE/Ao",
        None,
        "AE_Ao",
    ),
    MeasurementPattern(
        r"(?:dived\s*(?:normalizado|n)|di[aâ]metro\s+interno\s+do\s+ventr[ií]culo\s+esquerdo\s+em\s+di[aá]stole\s+normalizado)",
        "lviddn",
        "DIVEdN",
        None,
        "DIVEd_normalizado",
    ),
    MeasurementPattern(
        r"(?:velocidade\s+(?:m[aá]xima\s+)?d[oa]\s+)?(?:refluxo|regurgita[cç][aã]o|insufici[eê]ncia)\s+tric[uú]spide",
        "tricuspid_regurgitation_velocity",
        "Velocidade do refluxo tricúspide",
        "m/s",
        "IT_Vmax",
    ),
    MeasurementPattern(
        r"gradiente(?:\s+(?:estimado|tric[uú]spide|de\s+press[aã]o))?",
        "tricuspid_gradient",
        "Gradiente estimado",
        "mmHg",
        None,
    ),
    MeasurementPattern(
        r"(?:fe|fra[cç][aã]o\s+de\s+eje[cç][aã]o)",
        "ejection_fraction",
        "Fração de ejeção",
        "%",
        "FE_Teicholz",
        True,
    ),
    MeasurementPattern(
        r"(?:fs|fra[cç][aã]o\s+de\s+encurtamento)",
        "fractional_shortening",
        "Fração de encurtamento",
        "%",
        "DeltaD_FS",
        True,
    ),
    MeasurementPattern(r"tapse", "tapse", "TAPSE", "mm", "TAPSE"),
    MeasurementPattern(r"mapse", "mapse", "MAPSE", "mm", "MAPSE"),
    MeasurementPattern(
        r"(?:velocidade\s+d[ae]\s+)?onda\s+e",
        "mitral_e_velocity",
        "Velocidade da onda E",
        "m/s",
        "Onda_E",
    ),
    MeasurementPattern(
        r"(?:velocidade\s+d[ae]\s+)?onda\s+a",
        "mitral_a_velocity",
        "Velocidade da onda A",
        "m/s",
        "Onda_A",
    ),
    MeasurementPattern(
        r"(?:rela[cç][aã]o\s+)?e\s*/\s*a",
        "mitral_e_a_ratio",
        "E/A",
        None,
        "E_A",
    ),
    MeasurementPattern(
        r"(?:rela[cç][aã]o\s+)?e\s*/\s*(?:triv|ivrt)",
        "mitral_e_triv_ratio",
        "E/TRIV",
        None,
        "E_TRIV",
    ),
    MeasurementPattern(r"(?<!/)triv", "ivrt", "TRIV", "ms", "TRIV"),
    MeasurementPattern(
        r"(?:paat\s*/\s*pet|rela[cç][aã]o\s+paat\s+pet)",
        "paat_pet",
        "PAAT/PET",
        None,
        None,
    ),
    MeasurementPattern(
        r"(?:di[aâ]metro\s+d[oa]\s+)?ducto\s+arterioso",
        "ductus_diameter",
        "Diâmetro do ducto arterioso",
        "mm",
        None,
    ),
)

_NUMBER_WORDS = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
    "cem": 100,
    "cento": 100,
}
_NUMBER_TOKEN_PATTERN = (
    r"-?\d+(?:[,.]\d+)?|"
    r"(?:zero|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|"
    r"onze|doze|treze|quatorze|catorze|quinze|dezesseis|dezessete|dezoito|"
    r"dezenove|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|"
    r"cem|cento|e|v[ií]rgula|ponto)\b(?:[\s-]+(?:zero|um|uma|dois|duas|tr[eê]s|"
    r"quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|quatorze|catorze|"
    r"quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|quarenta|"
    r"cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|e|v[ií]rgula|ponto)\b){0,10}"
)

_EXPECTED_UNITS = {
    "tricuspid_regurgitation_velocity": "m/s",
    "tricuspid_gradient": "mmHg",
    "ejection_fraction": "%",
    "fractional_shortening": "%",
    "tapse": "mm",
    "mapse": "mm",
    "mitral_e_velocity": "m/s",
    "mitral_a_velocity": "m/s",
    "ivrt": "ms",
    "ductus_diameter": "mm",
}

_NORMAL_FIELD_SUGGESTIONS = {
    "valva_mitral": "Valva mitral com morfologia e mobilidade preservadas, sem evidências de refluxo ou estenose significativa.",
    "valva_aortica": "Valva aórtica com morfologia e mobilidade preservadas, sem evidências de refluxo ou estenose significativa.",
    "valva_tricuspide": "Valva tricúspide com morfologia e mobilidade preservadas, sem evidências de refluxo ou estenose significativa.",
    "valva_pulmonar": "Valva pulmonar com morfologia e mobilidade preservadas, sem evidências de refluxo ou estenose significativa.",
    "atrio_esquerdo": "Átrio esquerdo com dimensões preservadas, sem evidências de aumento atrial.",
    "ventriculo_esquerdo": "Ventrículo esquerdo com dimensões e espessuras preservadas, sem sinais de remodelamento.",
    "funcao_sistolica_ve": "Função sistólica global do ventrículo esquerdo preservada.",
    "funcao_diastolica": "Função diastólica preservada, com padrão de enchimento ventricular dentro da normalidade.",
    "atrio_direito": "Átrio direito com dimensões preservadas, sem alterações ecocardiográficas relevantes.",
    "ventriculo_direito": "Ventrículo direito com dimensões e função preservadas, sem sinais de sobrecarga.",
    "septos": "Septos interatrial e interventricular íntegros, sem alterações ecocardiográficas relevantes.",
    "aorta": "Aorta com dimensões preservadas, sem alterações ecocardiográficas relevantes.",
    "arteria_pulmonar": "Artéria pulmonar com calibre preservado, sem alterações ecocardiográficas relevantes.",
    "pericardio": "Pericárdio sem alterações ecocardiográficas relevantes e sem derrame pericárdico.",
}

_GLOBAL_NORMAL_PATTERNS = (
    r"\bexame\s+(?:esta\s+)?normal\b",
    r"\bsem\s+alteracoes?\s+ecocardiograficas?\b",
    r"\bdemais\s+parametros?\s+ecocardiograficos?\s+(?:estao\s+)?(?:dentro\s+da\s+normalidade|normais?)\b",
    r"\brestante\s+(?:do\s+exame\s+)?(?:esta\s+)?(?:dentro\s+da\s+normalidade|normal)\b",
    r"\b(?:o\s+)?resto\s+dos?\s+parametros?\s+ecocardiograficos?(?:\s+avaliados?)?\s+(?:esta\s+|estao\s+)?(?:dentro\s+da\s+normalidade|normal|normais)\b",
)

_REMAINING_NORMAL_PATTERNS = (
    r"\bdemais\s+parametros?\s+ecocardiograficos?\s+(?:estao\s+)?(?:dentro\s+da\s+normalidade|normais?)\b",
    r"\brestante\s+(?:do\s+exame\s+)?(?:esta\s+)?(?:dentro\s+da\s+normalidade|normal)\b",
    r"\b(?:o\s+)?resto\s+dos?\s+parametros?\s+ecocardiograficos?(?:\s+avaliados?)?\s+(?:esta\s+|estao\s+)?(?:dentro\s+da\s+normalidade|normal|normais)\b",
)

_DIASTOLIC_GRADE_ONE_PATTERN = re.compile(
    r"\bdisfuncao\s+diastolica\s+(?:de\s+)?grau\s+(?:1|i|um)\b",
)
_MITRAL_MILD_THICKENING_PATTERN = re.compile(
    r"\b(?:valva\s+)?mitral\b.*\b(?:folhetos?\s+)?espessad|\bespessamento\b.*\bmitral\b"
)
_MITRAL_MILD_REGURGITATION_PATTERN = re.compile(
    r"\b(?:refluxo|regurgitacao)\s+(?:mitral\s+)?leve\b"
    r"|\bmitral\b.*\b(?:refluxo|regurgitacao)\s+leve\b"
)
_MITRAL_B1_PATTERN = re.compile(
    r"\b(?:classificacao|estagio)?\s*b1\b|\bendocardiose\b.*\bmitral\b.*\bb1\b"
)
_PULMONARY_MILD_REGURGITATION_PATTERN = re.compile(
    r"\b(?:refluxo|regurgitacao|insuficiencia)\b[^.;\n]{0,50}"
    r"\b(?:(?:valva|valvula)\s+)?pulmonar\b[^.;\n]{0,30}"
    r"\b(?:leve|discret[ao])\b"
    r"|\b(?:refluxo|regurgitacao|insuficiencia)\b[^.;\n]{0,25}"
    r"\b(?:leve|discret[ao])\b[^.;\n]{0,35}"
    r"\b(?:(?:valva|valvula)\s+)?pulmonar\b"
    r"|\b(?:(?:valva|valvula)\s+)?pulmonar\b[^.;\n]{0,50}"
    r"\b(?:refluxo|regurgitacao|insuficiencia)\b[^.;\n]{0,30}"
    r"\b(?:leve|discret[ao])\b"
)
_PULMONARY_NORMAL_MORPHOLOGY_PATTERN = re.compile(
    r"\b(?:(?:valva|valvula)\s+)?pulmonar\b[^.;\n]{0,60}\b(?:"
    r"morfologicamente\s+normal|morfologia\s+(?:normal|preservada)|"
    r"morfologia\s+e\s+mobilidade\s+preservadas?)\b"
)
_NO_HEMODYNAMIC_REPERCUSSION_PATTERN = re.compile(
    r"\bsem\s+repercuss(?:ao|oes)\s+hemodinamicas?"
    r"(?:\s+significativas?)?\b"
)
_MITRAL_DISEASE_PATTERN = re.compile(
    r"\b(?:endocardiose|degeneracao\s+mixomatosa|doenca\s+valvar\s+mixomatosa)"
    r"\b.*\bmitral\b|\bmitral\b.*\b(?:endocardiose|mixomatosa)\b"
)
_MITRAL_STAGE_C_PATTERN = re.compile(
    r"\b(?:estagio|classificacao|grau|classe)?\s*c\b"
    r"|\b(?:estagio|classificacao|grau|classe)\s+(?:acvim\s+)?c\b"
)
_MITRAL_IMPORTANT_REGURGITATION_PATTERN = re.compile(
    r"\b(?:refluxo|regurgitacao|insuficiencia)\s+(?:mitral\s+)?"
    r"(?:importante|acentuad[ao]|grave|sever[ao])\b"
    r"|\bmitral\b.*\b(?:refluxo|regurgitacao|insuficiencia)\b.*"
    r"\b(?:importante|acentuad[ao]|grave|sever[ao])\b"
)
_TRICUSPID_REGURGITATION_PATTERN = re.compile(
    r"\b(?:refluxo|regurgitacao|insuficiencia)\s+(?:da\s+valva\s+)?tricuspide\b"
    r"|\btricuspide\b.*\b(?:refluxo|regurgitacao|insuficiencia)\b"
)
_RIGHT_CHAMBER_REPERCUSSION_PATTERN = re.compile(
    r"\b(?:repercussao|dilatacao|remodelamento|sobrecarga)\b.*"
    r"\b(?:camaras?\s+direitas?|atrio\s+direito|ventriculo\s+direito)\b"
)
_PULMONARY_CONGESTION_PATTERN = re.compile(
    r"\b(?:congestao\s+venosa\s+pulmonar|edema\s+pulmonar(?:\s+cardiogenico)?|"
    r"insuficiencia\s+cardiaca\s+congestiva|icc)\b"
)
_CLINICAL_SIGNS_PATTERN = re.compile(
    r"\b(?:animal\s+)?(?:tem|apresenta|apresentando|apresentou)\s+"
    r"sinais?\s+clinicos?\b"
    r"|\b(?:dispneia|taquipneia|intolerancia\s+ao\s+exercicio|sincope|"
    r"dificuldade\s+respiratoria)\b"
)
_RIGHT_ATRIAL_REMODELING_SEVERITY_PATTERNS = (
    re.compile(
        r"\b(?:remodelamento|dilatacao|aumento)\s+"
        r"(?P<severity>leve|discret[oa]|moderad[oa]|important[ea]|"
        r"acentuad[oa]|grave|sever[oa])\s+(?:do|de|das?)\s+"
        r"(?:atrio\s+direito|camaras?\s+direitas?)\b"
    ),
    re.compile(
        r"\b(?:atrio\s+direito|camaras?\s+direitas?)\b.{0,45}\b"
        r"(?P<severity>leve|discret[oa]|moderad[oa]|important[ea]|"
        r"acentuad[oa]|grave|sever[oa])\b"
    ),
)
_RIGHT_VENTRICULAR_PH_PATTERN = re.compile(
    r"\b(?:ventriculo\s+direito|vd)\b.*\b"
    r"(?:dilatacao|aumento|remodelamento|hipertrofia|sobrecarga)\b"
    r"|\b(?:achatamento|movimento\s+paradoxal)\b.*\bsepto\b"
)
_PULMONARY_ARTERY_PH_PATTERN = re.compile(
    r"\b(?:arteria\s+pulmonar|ap)\b.*\b(?:dilatad|aument|remodel)\w*\b"
    r"|\b(?:tempo\s+de\s+aceleracao|paat|at\s*/\s*et|notching)\b"
    r"|\bregurgitacao\s+pulmonar\b"
)
_RIGHT_ATRIUM_CAVA_PH_PATTERN = re.compile(
    r"\b(?:atrio\s+direito|veia\s+cava|cava\s+caudal)\b.*\b"
    r"(?:dilatad|aument|remodel|distendid)\w*\b"
)
_STRUCTURED_PHRASES_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "frases_ecocardiograma_estruturado_teste.json"
)


def _normal_preset_suggestions(species: str | None) -> dict[str, str]:
    normalized_species = _strip_accents(str(species or ""))
    preset_key = "normal_gato" if any(
        token in normalized_species for token in ("felina", "felino", "gato")
    ) else "normal_cao"
    try:
        payload = json.loads(_STRUCTURED_PHRASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_NORMAL_FIELD_SUGGESTIONS)

    aspects = {
        str(item.get("key") or ""): item
        for item in payload.get("aspectos", [])
        if isinstance(item, dict)
    }
    preset = next(
        (
            item
            for item in payload.get("presets", [])
            if isinstance(item, dict)
            and str(item.get("key") or "") == preset_key
            and item.get("ativo", 1)
        ),
        None,
    )
    if not preset:
        return dict(_NORMAL_FIELD_SUGGESTIONS)

    resolved: dict[str, str] = {}
    for selection in preset.get("selecoes", []):
        if not isinstance(selection, dict):
            continue
        field_key = str(selection.get("aspecto") or "")
        title = str(selection.get("frase_titulo") or "")
        aspect = aspects.get(field_key) or {}
        phrase = next(
            (
                item
                for item in aspect.get("frases", [])
                if isinstance(item, dict)
                and str(item.get("titulo") or "") == title
                and item.get("ativo", 1)
            ),
            None,
        )
        text = str((phrase or {}).get("texto") or "").strip()
        if field_key and text:
            resolved[field_key] = text
    return resolved or dict(_NORMAL_FIELD_SUGGESTIONS)


def _normalize_unit(value: str | None) -> str:
    normalized = _strip_accents(str(value or "")).replace(" ", "").lower()
    aliases = {
        "m/s": "m/s",
        "mps": "m/s",
        "metrosporsegundo": "m/s",
        "mmhg": "mmHg",
        "milimetrosdemercurio": "mmHg",
        "%": "%",
        "porcento": "%",
        "mm": "mm",
        "milimetro": "mm",
        "milimetros": "mm",
        "ms": "ms",
        "milissegundo": "ms",
        "milissegundos": "ms",
    }
    return aliases.get(normalized, str(value or "").strip())


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(char) != "Mn"
    )


def can_recover_normality_deterministically(transcript: str) -> bool:
    """Allow a safe fallback only when every dictated clause is already covered."""
    normalized = _strip_accents(str(transcript or ""))
    if not any(re.search(pattern, normalized) for pattern in _GLOBAL_NORMAL_PATTERNS):
        return False
    remaining_only = any(
        re.search(pattern, normalized) for pattern in _REMAINING_NORMAL_PATTERNS
    )
    pulmonary_mild_regurgitation = bool(
        _PULMONARY_MILD_REGURGITATION_PATTERN.search(normalized)
    )

    remaining = normalized
    for pattern in _GLOBAL_NORMAL_PATTERNS:
        remaining = re.sub(pattern, " ", remaining)

    clauses = [
        re.sub(r"^(?:e|tambem|animal)\s+", "", clause).strip(" ,:-")
        for clause in re.split(r"[.;\n]+", remaining)
    ]
    clauses = [clause for clause in clauses if clause]
    if remaining_only and not clauses:
        return False
    for clause in clauses:
        if _DIASTOLIC_GRADE_ONE_PATTERN.search(clause):
            continue
        if pulmonary_mild_regurgitation and any(
            pattern.search(clause)
            for pattern in (
                _PULMONARY_MILD_REGURGITATION_PATTERN,
                _PULMONARY_NORMAL_MORPHOLOGY_PATTERN,
                _NO_HEMODYNAMIC_REPERCUSSION_PATTERN,
            )
        ):
            continue
        if "mitral" not in clause:
            return False
        if re.search(
            r"\b(?:moderad[ao]s?|important[ea]s?|acentuad[ao]s?|graves?|"
            r"sever[ao]s?|massa|trombo|ruptura|prolapso|dilatacao)\b"
            r"|\b(?:estagio|classe)\s+(?:b2|c|d)\b",
            clause,
        ):
            return False
        mild_thickening = "espessamento" in clause and "leve" in clause
        mild_regurgitation = bool(
            re.search(r"\b(?:refluxo|regurgitacao)\s+leve\b", clause)
        )
        mitral_b1 = "b1" in clause and bool(
            re.search(r"\b(?:endocardiose|mixomatosa|classificad[ao])\b", clause)
        )
        if not any((mild_thickening, mild_regurgitation, mitral_b1)):
            return False
    return True


def build_deterministic_known_case_output(
    exam_context: dict | None,
) -> EchoClinicalStructureOutput:
    context = exam_context if isinstance(exam_context, dict) else {}
    raw_weight = context.get("weight_kg")
    try:
        weight_kg = float(raw_weight) if raw_weight not in (None, "") else None
    except (TypeError, ValueError):
        weight_kg = None
    if weight_kg is not None and weight_kg <= 0:
        weight_kg = None
    return EchoClinicalStructureOutput.model_validate(
        {
            "exam_context": {
                "species": str(context.get("species") or "").strip() or None,
                "breed": str(context.get("breed") or "").strip() or None,
                "age": str(context.get("age") or "").strip() or None,
                "weight_kg": weight_kg,
            },
            "measurements": [],
            "field_suggestions": [],
            "conclusion_suggestion": [],
            "warnings": [
                {
                    "warning_type": "known_case_structured_deterministically",
                    "severity": "info",
                    "message": (
                        "Este caso conhecido foi estruturado pelas regras clínicas "
                        "e pelo preset do sistema. Revise as sugestões antes de aplicar."
                    ),
                    "related_fields": ["conclusao"],
                }
            ],
            "missing_information": [],
        }
    )


def _parse_integer_words(value: str) -> Optional[int]:
    words = [word for word in _strip_accents(value).replace("-", " ").split() if word != "e"]
    if not words or any(word not in _NUMBER_WORDS for word in words):
        return None
    total = 0
    for word in words:
        total += _NUMBER_WORDS[word]
    return total


def parse_spoken_number(value: str) -> Optional[tuple[float, str]]:
    raw = str(value or "").strip(" \t\r\n.,;:")
    if not raw:
        return None
    compact = raw.replace(" ", "")
    if re.fullmatch(r"-?\d+(?:[,.]\d+)?", compact):
        normalized = compact.replace(",", ".")
        return float(normalized), normalized

    normalized_words = _strip_accents(raw)
    decimal_parts = re.split(r"\b(?:virgula|ponto)\b", normalized_words, maxsplit=1)
    integer_value = _parse_integer_words(decimal_parts[0])
    if integer_value is None:
        return None
    if len(decimal_parts) == 1:
        return float(integer_value), str(integer_value)

    fraction_words = [
        word for word in decimal_parts[1].replace("-", " ").split() if word != "e"
    ]
    if not fraction_words:
        return None
    if all(word in {"zero", "um", "uma", "dois", "duas", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove"} for word in fraction_words):
        fraction_digits = "".join(str(_NUMBER_WORDS[word]) for word in fraction_words)
    else:
        fraction_value = _parse_integer_words(decimal_parts[1])
        if fraction_value is None:
            return None
        fraction_digits = str(fraction_value)
    exact = f"{integer_value}.{fraction_digits}"
    return float(exact), exact


def extract_measurements_from_transcript(
    transcript: str,
) -> tuple[list[EchoMeasurementOutput], list[EchoClinicalWarningOutput]]:
    measurements: list[EchoMeasurementOutput] = []
    warnings: list[EchoClinicalWarningOutput] = []
    text = str(transcript or "")

    for definition in MEASUREMENT_PATTERNS:
        for label_match in re.finditer(definition.label_pattern, text, flags=re.IGNORECASE):
            tail = text[label_match.end() : label_match.end() + 140]
            number_match = re.search(
                rf"(?:\s*(?:de|em|igual\s+a|medindo)\s*)?({_NUMBER_TOKEN_PATTERN})",
                tail,
                flags=re.IGNORECASE,
            )
            if not number_match:
                continue
            parsed = parse_spoken_number(number_match.group(1))
            if parsed is None:
                continue
            numeric_value, raw_value = parsed
            source_end = label_match.end() + number_match.end()
            source_text = text[label_match.start() : source_end].strip()

            if numeric_value < 0:
                warnings.append(
                    EchoClinicalWarningOutput(
                        warning_type="negative_measurement",
                        severity="critical",
                        message=f"{definition.display_name} foi ditada com valor negativo e não pode ser aplicada.",
                        related_fields=[definition.canonical_name],
                    )
                )
                continue

            measurements.append(
                EchoMeasurementOutput(
                    canonical_name=definition.canonical_name,
                    display_name=definition.display_name,
                    value=numeric_value,
                    raw_value=raw_value,
                    unit=definition.unit,
                    target_field_key=definition.target_field_key,
                    source_text=source_text,
                    confidence=1.0,
                )
            )
            if definition.percentage and numeric_value > 100:
                warnings.append(
                    EchoClinicalWarningOutput(
                        warning_type="percentage_out_of_range",
                        severity="critical",
                        message=f"{definition.display_name} acima de 100%; revisar transcrição e unidade.",
                        related_fields=[definition.canonical_name],
                    )
                )

    return measurements, warnings


def _warning_key(warning: EchoClinicalWarningOutput) -> tuple[str, str]:
    return warning.warning_type, warning.message


def _warning_concept(warning: EchoClinicalWarningOutput) -> str:
    normalized = _strip_accents(
        f"{warning.warning_type} {warning.message}"
    )
    if "estagio c" in normalized or "stage_c" in normalized:
        return "stage_c_requires_chf_evidence"
    if "regurgitacao tricuspide" in normalized or "tr_velocity" in normalized:
        return "tr_velocity_requires_ph_context"
    if "unidade" in normalized:
        return "measurement_units"
    if "referencia" in normalized:
        return "reference_context"
    if any(
        token in normalized
        for token in ("raca", "idade", "especie", "peso")
    ) and any(token in normalized for token in ("ausente", "sem ", "nao ")):
        return "patient_context"
    return f"{warning.warning_type}:{warning.message}"


def _filter_contextual_provider_warnings(
    warnings: list[EchoClinicalWarningOutput],
    *,
    transcript: str,
    current_measurements: dict[str, str] | None,
    exam_context: dict | None,
    reference_context: dict | None,
) -> list[EchoClinicalWarningOutput]:
    known_measurement_units = any(
        key in ECHO_MEASUREMENT_UNITS
        and bool(str(value or "").strip())
        for key, value in (current_measurements or {}).items()
    )
    context = exam_context or {}
    has_patient_context = all(
        context.get(key) not in (None, "")
        for key in ("species", "breed", "age", "weight_kg")
    )
    has_reference = bool(
        isinstance(reference_context, dict)
        and reference_context.get("ranges")
    )
    filtered: list[EchoClinicalWarningOutput] = []
    clinical_signs_described = bool(
        _CLINICAL_SIGNS_PATTERN.search(_strip_accents(transcript))
    )
    for warning in warnings:
        normalized = _strip_accents(
            f"{warning.warning_type} {warning.message}"
        )
        if known_measurement_units and "unidade" in normalized and any(
            token in normalized
            for token in ("ausente", "sem unidade", "nao informad", "missing")
        ):
            continue
        if has_reference and "referencia" in normalized and any(
            token in normalized
            for token in ("ausente", "sem referencia", "nao e possivel", "missing")
        ):
            continue
        if has_patient_context and any(
            token in normalized
            for token in ("raca", "idade", "especie", "peso")
        ) and any(
            token in normalized
            for token in ("ausente", "nao informad", "sem ", "missing")
        ):
            continue
        if clinical_signs_described and any(
            token in normalized
            for token in (
                "sinais clinicos nao foram descritos",
                "sem sinais clinicos",
                "nao descreve sinais clinicos",
            )
        ):
            continue
        filtered.append(warning)
    return filtered


def _consolidate_field_suggestions(
    suggestions: list[EchoFieldSuggestionOutput],
) -> tuple[list[EchoFieldSuggestionOutput], list[EchoClinicalWarningOutput]]:
    """Keep one reviewable suggestion per form field without hiding duplication."""
    consolidated: list[EchoFieldSuggestionOutput] = []
    index_by_field: dict[str, int] = {}
    duplicated_fields: set[str] = set()

    for suggestion in suggestions:
        field_key = str(suggestion.field_key)
        existing_index = index_by_field.get(field_key)
        if existing_index is None:
            index_by_field[field_key] = len(consolidated)
            consolidated.append(suggestion)
            continue

        duplicated_fields.add(field_key)
        existing = consolidated[existing_index]
        if suggestion.confidence > existing.confidence:
            consolidated[existing_index] = suggestion

    warnings = [
        EchoClinicalWarningOutput(
            warning_type="duplicate_field_suggestion",
            severity="warning",
            message=(
                f"A IA retornou mais de uma sugestão para o campo {field_key}; "
                "foi mantida somente a de maior confiança para revisão."
            ),
            related_fields=[field_key],
        )
        for field_key in sorted(duplicated_fields)
    ]
    return consolidated, warnings


def _expand_asserted_normality(
    *,
    transcript: str,
    suggestions: list[EchoFieldSuggestionOutput],
    species: str | None,
) -> tuple[list[EchoFieldSuggestionOutput], list[EchoClinicalWarningOutput]]:
    normalized = _strip_accents(transcript)
    if not any(re.search(pattern, normalized) for pattern in _GLOBAL_NORMAL_PATTERNS):
        return suggestions, []

    remaining_only = any(
        re.search(pattern, normalized) for pattern in _REMAINING_NORMAL_PATTERNS
    )
    source = (
        "demais parâmetros ecocardiográficos dentro da normalidade"
        if remaining_only
        else "exame normal, sem alterações ecocardiográficas"
    )
    preset_suggestions = _normal_preset_suggestions(species)
    if remaining_only:
        expanded = [
            item
            for item in suggestions
            if not item.source_spans
            or not all(
                any(
                    re.search(pattern, _strip_accents(span))
                    for pattern in _GLOBAL_NORMAL_PATTERNS
                )
                for span in item.source_spans
            )
        ]
    else:
        expanded = []
    existing_fields = {str(item.field_key) for item in expanded}

    diastolic_grade_one = bool(_DIASTOLIC_GRADE_ONE_PATTERN.search(normalized))
    mitral_mild_disease = bool(
        _MITRAL_MILD_THICKENING_PATTERN.search(normalized)
        and _MITRAL_MILD_REGURGITATION_PATTERN.search(normalized)
    )
    mitral_b1 = mitral_mild_disease and bool(_MITRAL_B1_PATTERN.search(normalized))
    pulmonary_mild_regurgitation = bool(
        _PULMONARY_MILD_REGURGITATION_PATTERN.search(normalized)
    )
    pulmonary_without_repercussion = bool(
        _NO_HEMODYNAMIC_REPERCUSSION_PATTERN.search(normalized)
    )
    if mitral_mild_disease:
        expanded = [
            item for item in expanded if str(item.field_key) != "valva_mitral"
        ]
        existing_fields.discard("valva_mitral")
        expanded.append(
            EchoFieldSuggestionOutput(
                field_key="valva_mitral",
                text=(
                    "Valva mitral com espessamento leve dos folhetos, "
                    "predominando no folheto septal. Refluxo mitral de grau leve ao "
                    "Doppler colorido, com jato estreito restrito à porção proximal "
                    "do átrio esquerdo."
                ),
                confidence=1.0,
                source_spans=[
                    "valva mitral com folhetos espessados e refluxo leve"
                ],
                evidence_type="fact",
            )
        )
        existing_fields.add("valva_mitral")

    if diastolic_grade_one:
        expanded = [
            item
            for item in expanded
            if str(item.field_key) not in {"funcao_diastolica", "conclusao"}
        ]
        existing_fields.difference_update({"funcao_diastolica", "conclusao"})
        expanded.append(
            EchoFieldSuggestionOutput(
                field_key="funcao_diastolica",
                text="Disfunção diastólica grau I (padrão senil).",
                confidence=1.0,
                source_spans=["disfunção diastólica grau 1, padrão senil"],
                evidence_type="fact",
            )
        )
        existing_fields.add("funcao_diastolica")

    pulmonary_field_text = ""
    pulmonary_conclusion_text = ""
    if pulmonary_mild_regurgitation:
        pulmonary_field_text = (
            "Valva pulmonar com morfologia preservada, apresentando regurgitação "
            "de grau leve"
        )
        pulmonary_conclusion_text = "Regurgitação pulmonar de grau leve"
        if pulmonary_without_repercussion:
            pulmonary_field_text += ", sem repercussão hemodinâmica"
            pulmonary_conclusion_text += ", sem repercussão hemodinâmica"
        pulmonary_field_text += "."
        pulmonary_conclusion_text += "."
        expanded = [
            item for item in expanded if str(item.field_key) != "valva_pulmonar"
        ]
        existing_fields.discard("valva_pulmonar")
        expanded.append(
            EchoFieldSuggestionOutput(
                field_key="valva_pulmonar",
                text=pulmonary_field_text,
                confidence=1.0,
                source_spans=[
                    (
                        "refluxo em valva pulmonar leve, sem repercussão "
                        "hemodinâmica"
                        if pulmonary_without_repercussion
                        else "refluxo em valva pulmonar leve"
                    )
                ],
                evidence_type="fact",
            )
        )
        existing_fields.add("valva_pulmonar")

    for field_key, text in preset_suggestions.items():
        if field_key in existing_fields:
            continue
        expanded.append(
            EchoFieldSuggestionOutput(
                field_key=field_key,
                text=text,
                confidence=0.95,
                source_spans=[source],
                evidence_type="fact",
            )
        )
        existing_fields.add(field_key)

    if mitral_b1:
        expanded = [
            item for item in expanded if str(item.field_key) != "conclusao"
        ]
        conclusion_parts = [
            (
                "Achados ecocardiográficos compatíveis com degeneração "
                "mixomatosa da valva mitral, com refluxo de grau leve e sem "
                "remodelamento cardíaco significativo. Estágio B1 (ACVIM)."
            )
        ]
        source_spans = ["endocardiose mitral B1 com refluxo leve"]
        if diastolic_grade_one:
            conclusion_parts.append(
                "Disfunção diastólica grau I (padrão senil)."
            )
            source_spans.append(
                "disfunção diastólica grau 1, padrão senil"
            )
        if pulmonary_conclusion_text:
            conclusion_parts.append(pulmonary_conclusion_text)
            source_spans.append("refluxo em valva pulmonar leve")
        expanded.append(
            EchoFieldSuggestionOutput(
                field_key="conclusao",
                text=" ".join(conclusion_parts),
                confidence=1.0,
                source_spans=source_spans,
                evidence_type="diagnostic_suggestion",
            )
        )
    elif diastolic_grade_one:
        conclusion_parts = ["Disfunção diastólica grau I (padrão senil)."]
        source_spans = ["disfunção diastólica grau 1, padrão senil"]
        if pulmonary_conclusion_text:
            conclusion_parts.append(pulmonary_conclusion_text)
            source_spans.append("refluxo em valva pulmonar leve")
        expanded.append(
            EchoFieldSuggestionOutput(
                field_key="conclusao",
                text=" ".join(conclusion_parts),
                confidence=1.0,
                source_spans=source_spans,
                evidence_type="diagnostic_suggestion",
            )
        )
    elif pulmonary_conclusion_text:
        expanded = [
            item for item in expanded if str(item.field_key) != "conclusao"
        ]
        expanded.append(
            EchoFieldSuggestionOutput(
                field_key="conclusao",
                text=pulmonary_conclusion_text,
                confidence=1.0,
                source_spans=["refluxo em valva pulmonar leve"],
                evidence_type="diagnostic_suggestion",
            )
        )
    elif "conclusao" not in existing_fields:
        expanded.append(
            EchoFieldSuggestionOutput(
                field_key="conclusao",
                text="Ecocardiograma dentro dos limites da normalidade.",
                confidence=0.95,
                source_spans=[source],
                evidence_type="diagnostic_suggestion",
            )
        )

    return expanded, [
        EchoClinicalWarningOutput(
            warning_type="global_normality_expanded",
            severity="info",
            message=(
                "A afirmação global de normalidade foi expandida para os campos sem "
                "alteração específica. Revise as sugestões antes de aplicá-las."
            ),
            related_fields=sorted(preset_suggestions),
        )
    ]


def _enrich_from_current_measurements(
    suggestions: list[EchoFieldSuggestionOutput],
    warnings: list[EchoClinicalWarningOutput],
    current_measurements: dict[str, str] | None,
    species: str | None,
) -> tuple[list[EchoFieldSuggestionOutput], list[EchoClinicalWarningOutput]]:
    normalized_species = _strip_accents(str(species or ""))
    if any(token in normalized_species for token in ("felina", "felino", "gato")):
        return suggestions, warnings
    raw_la_ao = str((current_measurements or {}).get("AE_Ao") or "").strip()
    if not raw_la_ao:
        return suggestions, warnings
    try:
        la_ao = float(raw_la_ao.replace(",", "."))
    except ValueError:
        return suggestions, warnings
    if la_ao < 1.6:
        return suggestions, warnings

    important = la_ao > 2.3
    atrial_text = (
        "Átrio esquerdo com aumento importante de suas dimensões. "
        "Relação AE/Ao com aumento importante."
        if important
        else "Átrio esquerdo com aumento de suas dimensões. Relação AE/Ao aumentada."
    )
    conclusion_part = (
        "Dilatação atrial esquerda importante, com repercussão hemodinâmica significativa."
        if important
        else "Dilatação atrial esquerda."
    )
    enriched = [
        item
        for item in suggestions
        if str(item.field_key) not in {"atrio_esquerdo", "conclusao"}
    ]
    previous_conclusion = next(
        (
            item.text.strip()
            for item in suggestions
            if str(item.field_key) == "conclusao" and item.text.strip()
        ),
        "",
    )
    previous_conclusion = re.sub(
        r"\s*(?:e\s+)?sem remodelamento card[ií]aco significativo\.\s*"
        r"Est[aá]gio B1 \(ACVIM\)\.",
        ".",
        previous_conclusion,
        flags=re.IGNORECASE,
    )
    previous_conclusion = re.sub(r"\.{2,}", ".", previous_conclusion).strip()
    enriched.append(
        EchoFieldSuggestionOutput(
            field_key="atrio_esquerdo",
            text=atrial_text,
            confidence=1.0,
            source_spans=[f"Medida do formulário: AE/Ao {raw_la_ao}"],
            evidence_type="inference",
        )
    )
    enriched.append(
        EchoFieldSuggestionOutput(
            field_key="conclusao",
            text=" ".join(part for part in (previous_conclusion, conclusion_part) if part),
            confidence=0.95,
            source_spans=[f"Medida do formulário: AE/Ao {raw_la_ao}"],
            evidence_type="diagnostic_suggestion",
        )
    )
    return enriched, warnings


def _measurement_float(
    current_measurements: dict[str, str] | None,
    field_key: str,
) -> float | None:
    raw = str((current_measurements or {}).get(field_key) or "").strip()
    match = re.search(r"-?\d+(?:[,.]\d+)?", raw)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _reference_bounds(
    reference_context: dict | None,
    field_key: str,
) -> tuple[float | None, float | None]:
    ranges = (
        reference_context.get("ranges", {})
        if isinstance(reference_context, dict)
        else {}
    )
    item = ranges.get(field_key)
    if not isinstance(item, dict):
        return None, None

    def parsed(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return parsed(item.get("min")), parsed(item.get("max"))


def _above_reference(
    value: float | None,
    reference_context: dict | None,
    field_key: str,
    *,
    fallback_max: float | None = None,
) -> bool:
    if value is None:
        return False
    _, maximum = _reference_bounds(reference_context, field_key)
    effective_maximum = maximum if maximum is not None else fallback_max
    return effective_maximum is not None and value > effective_maximum


def _systolic_indices_support_normal_language(
    current_measurements: dict[str, str] | None,
    reference_context: dict | None,
) -> bool:
    measurements = current_measurements or {}
    selected_technique = str(
        measurements.get("VE_tecnica_relatorio") or ""
    ).strip().lower()
    if selected_technique == "2d":
        field_pairs = (("FE_Teicholz_2D", "DeltaD_FS_2D"),)
    elif selected_technique == "modo_m":
        field_pairs = (("FE_Teicholz", "DeltaD_FS"),)
    else:
        field_pairs = (
            ("FE_Teicholz", "DeltaD_FS"),
            ("FE_Teicholz_2D", "DeltaD_FS_2D"),
        )

    evaluated_pairs: list[bool] = []
    for field_pair in field_pairs:
        pair_results: list[bool] = []
        for field_key in field_pair:
            value = _measurement_float(measurements, field_key)
            minimum, maximum = _reference_bounds(reference_context, field_key)
            if value is None or (minimum is None and maximum is None):
                pair_results = []
                break
            rounding_margin = 1.0 if field_key.startswith("DeltaD_FS") else 0.0
            pair_results.append(
                (minimum is None or value >= minimum)
                and (maximum is None or value <= maximum + rounding_margin)
            )
        if pair_results:
            evaluated_pairs.append(all(pair_results))
    return bool(evaluated_pairs) and all(evaluated_pairs)


def _remove_internal_reference_wording(text: str) -> str:
    sanitized = re.sub(
        r"\b(intervalos?\s+de\s+refer[eê]ncia)\s+carregados?\b",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"\b((?:tabela|faixa)\s+de\s+refer[eê]ncia)\s+carregada\b",
        r"\1",
        sanitized,
        flags=re.IGNORECASE,
    )


def _normalize_clinical_reference_language(
    suggestions: list[EchoFieldSuggestionOutput],
    *,
    current_measurements: dict[str, str] | None,
    reference_context: dict | None,
) -> list[EchoFieldSuggestionOutput]:
    normal_systolic_language = _systolic_indices_support_normal_language(
        current_measurements,
        reference_context,
    )
    normalized_suggestions: list[EchoFieldSuggestionOutput] = []
    for item in suggestions:
        original_text = str(item.text or "")
        normalized_text = _strip_accents(original_text)
        if (
            str(item.field_key) == "funcao_sistolica_ve"
            and normal_systolic_language
            and "funcao sistolica global preservada" in normalized_text
            and "fracao de encurtamento" in normalized_text
        ):
            text = (
                "Função sistólica global preservada, com fração de encurtamento "
                "e fração de ejeção dentro dos intervalos de referência normais."
            )
        else:
            text = _remove_internal_reference_wording(original_text)
        normalized_suggestions.append(
            item if text == original_text else item.model_copy(update={"text": text})
        )
    return normalized_suggestions


def _replace_field_suggestion(
    suggestions: list[EchoFieldSuggestionOutput],
    *,
    field_key: str,
    text: str,
    source_spans: list[str],
    evidence_type: str,
    confidence: float = 0.95,
) -> list[EchoFieldSuggestionOutput]:
    return [
        item for item in suggestions if str(item.field_key) != field_key
    ] + [
        EchoFieldSuggestionOutput(
            field_key=field_key,
            text=text,
            confidence=confidence,
            source_spans=source_spans,
            evidence_type=evidence_type,
        )
    ]


def _enrich_advanced_mitral_multimodal(
    suggestions: list[EchoFieldSuggestionOutput],
    warnings: list[EchoClinicalWarningOutput],
    *,
    transcript: str,
    current_measurements: dict[str, str] | None,
    species: str | None,
    reference_context: dict | None,
) -> tuple[list[EchoFieldSuggestionOutput], list[EchoClinicalWarningOutput]]:
    normalized_species = _strip_accents(str(species or ""))
    normalized = _strip_accents(transcript)
    if any(token in normalized_species for token in ("felina", "felino", "gato")):
        return suggestions, warnings
    mitral_disease_in_audio = bool(_MITRAL_DISEASE_PATTERN.search(normalized))
    stage_c = bool(_MITRAL_STAGE_C_PATTERN.search(normalized))
    important_mr_in_audio = bool(
        _MITRAL_IMPORTANT_REGURGITATION_PATTERN.search(normalized)
    )
    tricuspid_regurgitation_in_audio = bool(
        _TRICUSPID_REGURGITATION_PATTERN.search(normalized)
    )
    right_chamber_repercussion = bool(
        _RIGHT_CHAMBER_REPERCUSSION_PATTERN.search(normalized)
    )
    pulmonary_congestion = bool(_PULMONARY_CONGESTION_PATTERN.search(normalized))
    clinical_signs_described = bool(_CLINICAL_SIGNS_PATTERN.search(normalized))

    la_ao = _measurement_float(current_measurements, "AE_Ao")
    lvidd = _measurement_float(current_measurements, "DIVEd")
    lviddn = _measurement_float(current_measurements, "DIVEd_normalizado")
    e_wave = _measurement_float(current_measurements, "Onda_E")
    e_a = _measurement_float(current_measurements, "E_A")
    e_e_prime = _measurement_float(current_measurements, "E_E_linha")
    mr_vmax = _measurement_float(current_measurements, "IM_Vmax")
    tr_vmax = _measurement_float(current_measurements, "IT_Vmax")

    la_enlarged = bool(
        (la_ao is not None and la_ao >= 1.6)
        or _above_reference(
            la_ao,
            reference_context,
            "AE_Ao",
            fallback_max=1.6,
        )
    )
    la_important = bool(la_ao is not None and la_ao > 2.3)
    lv_dilated = bool(
        (lviddn is not None and lviddn >= 1.7)
        or _above_reference(lvidd, reference_context, "DIVEd")
    )
    filling_pressure_support = bool(
        _above_reference(
            e_wave,
            reference_context,
            "Onda_E",
            fallback_max=1.2,
        )
        or _above_reference(
            e_a,
            reference_context,
            "E_A",
            fallback_max=2.0,
        )
        or _above_reference(
            e_e_prime,
            reference_context,
            "E_E_linha",
            fallback_max=12.0,
        )
    )
    advanced_measurement_pattern = bool(
        la_enlarged
        and lv_dilated
        and filling_pressure_support
        and mr_vmax is not None
    )
    partial_measurement_pattern = sum(
        (la_enlarged, lv_dilated, filling_pressure_support, mr_vmax is not None)
    ) >= 2
    advanced_mitral_pattern = advanced_measurement_pattern or bool(
        mitral_disease_in_audio
        and (
            stage_c
            or important_mr_in_audio
            or partial_measurement_pattern
        )
    )
    if not advanced_mitral_pattern and not tricuspid_regurgitation_in_audio:
        return suggestions, warnings

    important_mr = important_mr_in_audio or advanced_measurement_pattern
    tricuspid_regurgitation = (
        tricuspid_regurgitation_in_audio or tr_vmax is not None
    )
    enriched = list(suggestions)
    evidence_sources: list[str] = []
    if mitral_disease_in_audio:
        evidence_sources.append("Ditado: doença mixomatosa/endocardiose mitral")
    if advanced_measurement_pattern:
        evidence_sources.append(
            "Correlação: regurgitação mitral, aumento atrial esquerdo, "
            "dilatação ventricular esquerda e pressão de enchimento elevada"
        )

    if advanced_mitral_pattern:
        mitral_text = (
            "Valva mitral com espessamento e aspecto mixomatoso dos folhetos, "
            "associada a regurgitação mitral importante e repercussão hemodinâmica."
            if important_mr
            else (
                "Valva mitral com espessamento e aspecto mixomatoso dos folhetos, "
                "associada a regurgitação mitral."
            )
        )
        enriched = _replace_field_suggestion(
            enriched,
            field_key="valva_mitral",
            text=mitral_text,
            source_spans=[
                *evidence_sources,
                *(
                    [f"Medida do formulário: IM Vmax {mr_vmax:g} m/s"]
                    if mr_vmax is not None
                    else []
                ),
            ],
            evidence_type=(
                "fact" if important_mr_in_audio else "diagnostic_suggestion"
            ),
            confidence=0.96 if important_mr_in_audio else 0.88,
        )

    if la_enlarged:
        enriched = _replace_field_suggestion(
            enriched,
            field_key="atrio_esquerdo",
            text=(
                "Átrio esquerdo com aumento importante de suas dimensões. "
                "Relação AE/Ao com aumento importante."
                if la_important
                else "Átrio esquerdo com aumento de suas dimensões. Relação AE/Ao aumentada."
            ),
            source_spans=[
                f"Medida do formulário: AE/Ao {la_ao:g}"
                if la_ao is not None
                else "Medida do formulário: relação AE/Ao acima da referência"
            ],
            evidence_type="inference",
        )

    if lv_dilated:
        lv_sources: list[str] = []
        if lviddn is not None:
            lv_sources.append(f"Medida do formulário: DIVEd normalizado {lviddn:g}")
        if lvidd is not None:
            lv_sources.append(f"Medida do formulário: DIVEd {lvidd:g} mm")
        enriched = _replace_field_suggestion(
            enriched,
            field_key="ventriculo_esquerdo",
            text=(
                "Diâmetro interno do ventrículo esquerdo com aumento importante, "
                "compatível com sobrecarga volumétrica crônica."
            ),
            source_spans=lv_sources,
            evidence_type="inference",
        )

    if filling_pressure_support:
        doppler_values: list[str] = []
        if e_wave is not None:
            doppler_values.append(f"onda E {e_wave:g} m/s")
        if e_a is not None:
            doppler_values.append(f"relação E/A {e_a:g}")
        if e_e_prime is not None:
            doppler_values.append(f"E/E' {e_e_prime:g}")
        enriched = _replace_field_suggestion(
            enriched,
            field_key="funcao_diastolica",
            text=(
                "Fluxo transmitral compatível com elevação das pressões de "
                "enchimento do ventrículo esquerdo."
            ),
            source_spans=[
                f"Medidas do formulário: {', '.join(doppler_values)}",
            ],
            evidence_type="inference",
        )

    if tricuspid_regurgitation:
        enriched = _replace_field_suggestion(
            enriched,
            field_key="valva_tricuspide",
            text=(
                "Regurgitação tricúspide com velocidade elevada, achado que requer "
                "correlação com sinais anatômicos e o contexto clínico."
                if tr_vmax is not None and tr_vmax >= 3.0
                else "Regurgitação tricúspide identificada ao Doppler colorido."
            ),
            source_spans=[
                *(
                    ["Ditado: regurgitação tricúspide"]
                    if tricuspid_regurgitation_in_audio
                    else []
                ),
                *(
                    [f"Medida do formulário: IT Vmax {tr_vmax:g} m/s"]
                    if tr_vmax is not None
                    else []
                ),
            ],
            evidence_type=(
                "fact" if tricuspid_regurgitation_in_audio else "inference"
            ),
        )

    if right_chamber_repercussion:
        enriched = _replace_field_suggestion(
            enriched,
            field_key="atrio_direito",
            text="Átrio direito com dilatação associada à repercussão hemodinâmica descrita.",
            source_spans=["Ditado: repercussão em câmaras direitas"],
            evidence_type="fact",
        )
        enriched = _replace_field_suggestion(
            enriched,
            field_key="ventriculo_direito",
            text="Ventrículo direito com sinais de sobrecarga/remodelamento, conforme descrito no ditado.",
            source_spans=["Ditado: repercussão em câmaras direitas"],
            evidence_type="fact",
        )

    if advanced_mitral_pattern:
        conclusion_parts: list[str] = []
        conclusion_parts.append(
            "Espessamento da valva mitral com regurgitação importante"
            if important_mr
            else "Espessamento da valva mitral com regurgitação"
        )
        if la_enlarged and lv_dilated:
            conclusion_parts.append(
                "dilatação importante do átrio e do ventrículo esquerdos"
                if la_important
                else "dilatação do átrio e do ventrículo esquerdos"
            )
        elif la_enlarged:
            conclusion_parts.append("dilatação do átrio esquerdo")
        elif lv_dilated:
            conclusion_parts.append("dilatação do ventrículo esquerdo")
        if filling_pressure_support:
            conclusion_parts.append(
                "elevadas pressões de enchimento do ventrículo esquerdo"
            )
        conclusion = ", ".join(conclusion_parts) + ". "
        if pulmonary_congestion:
            conclusion += (
                "Achados compatíveis com endocardiose da valva mitral em estágio C "
                "(ACVIM), com sinais de congestão venosa pulmonar."
            )
        elif stage_c and clinical_signs_described:
            conclusion += (
                "Padrão ecocardiográfico compatível com doença valvar mixomatosa "
                "mitral avançada. O estágio C (ACVIM) foi informado em conjunto "
                "com sinais clínicos e deve ser correlacionado com evidência atual "
                "ou histórica de insuficiência cardíaca congestiva."
            )
        elif stage_c:
            conclusion += (
                "Padrão ecocardiográfico compatível com doença valvar mixomatosa "
                "mitral avançada; o estágio C (ACVIM) informado requer confirmação "
                "de insuficiência cardíaca congestiva atual ou prévia."
            )
        else:
            conclusion += (
                "Achados ecocardiográficos compatíveis com doença valvar mixomatosa "
                "mitral avançada, podendo corresponder ao estágio C (ACVIM) caso "
                "existam sinais atuais ou prévios de insuficiência cardíaca congestiva."
            )
        enriched = _replace_field_suggestion(
            enriched,
            field_key="conclusao",
            text=conclusion,
            source_spans=[
                *evidence_sources,
                *(
                    ["Ditado: estágio C (ACVIM)"]
                    if stage_c
                    else []
                ),
                *(
                    ["Ditado: congestão venosa pulmonar/ICC"]
                    if pulmonary_congestion
                    else []
                ),
            ],
            evidence_type="diagnostic_suggestion",
            confidence=0.94 if mitral_disease_in_audio else 0.86,
        )

    enriched_warnings = list(warnings)
    if stage_c and not pulmonary_congestion and not clinical_signs_described:
        enriched_warnings.append(
            EchoClinicalWarningOutput(
                warning_type="stage_c_requires_chf_evidence",
                severity="warning",
                message=(
                    "O estágio C foi informado no ditado, mas congestão atual ou "
                    "histórico prévio de insuficiência cardíaca não foram descritos. "
                    "Confirme sinais clínicos e/ou evidência radiográfica."
                ),
                related_fields=["conclusao"],
            )
        )
    elif stage_c and clinical_signs_described and not pulmonary_congestion:
        enriched_warnings.append(
            EchoClinicalWarningOutput(
                warning_type="stage_c_clinical_signs_need_chf_correlation",
                severity="info",
                message=(
                    "O ditado descreve sinais clínicos e informa estágio C. "
                    "Correlacione os sinais com evidência atual ou histórica de "
                    "insuficiência cardíaca congestiva antes de confirmar o estágio."
                ),
                related_fields=["conclusao"],
            )
        )
    if tr_vmax is not None and tr_vmax >= 3.0:
        enriched_warnings.append(
            EchoClinicalWarningOutput(
                warning_type="tr_velocity_requires_ph_context",
                severity="warning",
                message=(
                    "A velocidade da regurgitação tricúspide está elevada. A "
                    "probabilidade de hipertensão pulmonar requer correlação com "
                    "sinais anatômicos adicionais e o contexto clínico."
                ),
                related_fields=["IT_Vmax", "valva_tricuspide", "ventriculo_direito"],
            )
        )
    return enriched, enriched_warnings


def _right_atrial_remodeling_from_transcript(transcript: str) -> str | None:
    normalized = _strip_accents(transcript)
    for pattern in _RIGHT_ATRIAL_REMODELING_SEVERITY_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        severity = match.group("severity")
        if severity.startswith(("moderad",)):
            return "moderado"
        if severity.startswith(("important", "acentuad", "grave", "sever")):
            return "importante"
        return "leve"
    return None


def _tricuspid_velocity_from_transcript(transcript: str) -> float | None:
    extracted, _ = extract_measurements_from_transcript(transcript)
    return next(
        (
            item.value
            for item in extracted
            if item.canonical_name == "tricuspid_regurgitation_velocity"
            and item.value is not None
        ),
        None,
    )


def _pulmonary_hypertension_anatomic_sites(transcript: str) -> list[str]:
    normalized = _strip_accents(transcript)
    sites: set[str] = set()
    if _RIGHT_VENTRICULAR_PH_PATTERN.search(normalized):
        sites.add("ventriculo_direito")
    if _PULMONARY_ARTERY_PH_PATTERN.search(normalized):
        sites.add("arteria_pulmonar")
    if _RIGHT_ATRIUM_CAVA_PH_PATTERN.search(normalized):
        sites.add("atrio_direito_veia_cava")
    if _RIGHT_CHAMBER_REPERCUSSION_PATTERN.search(normalized):
        sites.update({"ventriculo_direito", "atrio_direito_veia_cava"})
    return sorted(sites)


def _canine_ph_probability(tr_velocity: float, anatomic_sites: int) -> str:
    if tr_velocity <= 3.0:
        return "intermediaria" if anatomic_sites >= 2 else "baixa"
    if tr_velocity <= 3.4:
        if anatomic_sites == 0:
            return "baixa"
        return "alta" if anatomic_sites >= 2 else "intermediaria"
    return "alta" if anatomic_sites >= 1 else "intermediaria"


def _feline_ph_probability(tr_velocity: float, anatomic_sites: int) -> str:
    if tr_velocity <= 2.7:
        return "intermediaria" if anatomic_sites >= 2 else "baixa"
    return "alta" if anatomic_sites >= 1 else "intermediaria"


def _enrich_pulmonary_hypertension_probability(
    suggestions: list[EchoFieldSuggestionOutput],
    warnings: list[EchoClinicalWarningOutput],
    *,
    transcript: str,
    current_measurements: dict[str, str] | None,
    species: str | None,
) -> tuple[list[EchoFieldSuggestionOutput], list[EchoClinicalWarningOutput]]:
    tr_velocity = _measurement_float(current_measurements, "IT_Vmax")
    if tr_velocity is None:
        tr_velocity = _tricuspid_velocity_from_transcript(transcript)
    if tr_velocity is None or tr_velocity <= 0:
        return suggestions, warnings

    sites = _pulmonary_hypertension_anatomic_sites(transcript)
    normalized_species = _strip_accents(str(species or ""))
    feline = any(
        token in normalized_species for token in ("felina", "felino", "gato")
    )
    probability = (
        _feline_ph_probability(tr_velocity, len(sites))
        if feline
        else _canine_ph_probability(tr_velocity, len(sites))
    )
    labels = {
        "baixa": "baixa",
        "intermediaria": "intermediária",
        "alta": "alta",
    }
    probability_label = labels[probability]
    evidence = [
        f"Velocidade da regurgitação tricúspide: {tr_velocity:g} m/s",
        *(
            [f"Locais anatômicos de suporte: {', '.join(sites)}"]
            if sites
            else ["Sem local anatômico adicional descrito"]
        ),
    ]

    enriched = _replace_field_suggestion(
        suggestions,
        field_key="valva_tricuspide",
        text=(
            "Regurgitação tricúspide com velocidade elevada. O conjunto dos "
            f"achados sustenta {probability_label} probabilidade ecocardiográfica "
            "de hipertensão pulmonar."
        ),
        source_spans=evidence,
        evidence_type="inference",
        confidence=0.93 if probability == "alta" else 0.86,
    )
    previous_conclusion = next(
        (
            item.text.strip()
            for item in enriched
            if str(item.field_key) == "conclusao" and item.text.strip()
        ),
        "",
    )
    previous_conclusion = re.sub(
        r"\s*(?:Conjunto|Achados)\s+compat[ií]ve(?:l|is)\s+com\s+"
        r"(?:baixa|intermedi[aá]ria|alta)\s+(?:probabilidade|suspeita)"
        r".*?hipertens[aã]o\s+pulmonar\.\s*",
        " ",
        previous_conclusion,
        flags=re.IGNORECASE,
    ).strip()
    ph_term = "suspeita ecocardiográfica" if feline else "probabilidade ecocardiográfica"
    ph_conclusion = (
        f"Conjunto compatível com {probability_label} {ph_term} de "
        "hipertensão pulmonar."
    )
    enriched = _replace_field_suggestion(
        enriched,
        field_key="conclusao",
        text=" ".join(part for part in (previous_conclusion, ph_conclusion) if part),
        source_spans=evidence,
        evidence_type="diagnostic_suggestion",
        confidence=0.93 if probability == "alta" else 0.84,
    )

    enriched_warnings = [
        warning
        for warning in warnings
        if not (
            warning.warning_type == "tr_velocity_requires_ph_context"
            and len(sites) >= 1
        )
    ]
    if feline:
        enriched_warnings.append(
            EchoClinicalWarningOutput(
                warning_type="feline_ph_framework_limited",
                severity="info",
                message=(
                    "Em gatos, a classificação foi apresentada como suspeita "
                    "ecocardiográfica orientativa; os critérios de probabilidade "
                    "caninos não devem ser transferidos diretamente."
                ),
                related_fields=["IT_Vmax", "conclusao"],
            )
        )
    return enriched, enriched_warnings


def _derived_right_heart_measurements(
    transcript: str,
    current_measurements: dict[str, str] | None,
) -> list[EchoMeasurementOutput]:
    remodeling = (
        _right_atrial_remodeling_from_transcript(transcript)
        or str((current_measurements or {}).get("Remodelamento_AD") or "").strip().lower()
        or None
    )
    if remodeling not in {"ausente", "leve", "moderado", "importante"}:
        return []

    rap_by_remodeling = {
        "ausente": 5.0,
        "leve": 5.0,
        "moderado": 10.0,
        "importante": 15.0,
    }
    source = f"Remodelamento do átrio direito: {remodeling}"
    outputs = [
        EchoMeasurementOutput(
            canonical_name="right_atrial_remodeling",
            display_name="Remodelamento do átrio direito",
            value=None,
            raw_value=remodeling,
            unit=None,
            target_field_key="Remodelamento_AD",
            source_text=source,
            confidence=0.97,
        )
    ]
    tr_velocity = _measurement_float(current_measurements, "IT_Vmax")
    if tr_velocity is None:
        tr_velocity = _tricuspid_velocity_from_transcript(transcript)
    if tr_velocity is None or tr_velocity <= 0:
        return outputs

    gradient = 4 * tr_velocity**2
    rap = rap_by_remodeling[remodeling]
    psap = gradient + rap
    for canonical_name, display_name, value, target_field_key, source_text in (
        (
            "tricuspid_gradient_calculated",
            "Gradiente tricúspide calculado",
            gradient,
            "IT_Grad",
            f"Bernoulli simplificada: 4 × ({tr_velocity:g} m/s)²",
        ),
        (
            "right_atrial_pressure_estimated",
            "Pressão atrial direita estimada",
            rap,
            "PAD_estimada",
            source,
        ),
        (
            "psap_estimated",
            "PSAP estimada",
            psap,
            "PSAP",
            "Gradiente tricúspide calculado + pressão atrial direita estimada",
        ),
    ):
        outputs.append(
            EchoMeasurementOutput(
                canonical_name=canonical_name,
                display_name=display_name,
                value=round(value, 2),
                raw_value=f"{value:.2f}",
                unit="mmHg",
                target_field_key=target_field_key,
                source_text=source_text,
                confidence=0.9,
            )
        )
    return outputs


def validate_and_enrich_clinical_output(
    output: EchoClinicalStructureOutput,
    transcript: str,
    *,
    species: str | None = None,
    current_measurements: dict[str, str] | None = None,
    exam_context: dict | None = None,
    reference_context: dict | None = None,
) -> EchoClinicalStructureOutput:
    deterministic, numeric_warnings = extract_measurements_from_transcript(transcript)
    field_suggestions, duplicate_warnings = _consolidate_field_suggestions(
        list(output.field_suggestions)
    )
    field_suggestions, normality_warnings = _expand_asserted_normality(
        transcript=transcript,
        suggestions=field_suggestions,
        species=species or output.exam_context.species,
    )
    field_suggestions, measurement_warnings = _enrich_from_current_measurements(
        field_suggestions,
        [*duplicate_warnings, *normality_warnings],
        current_measurements,
        species or output.exam_context.species,
    )
    field_suggestions, measurement_warnings = _enrich_advanced_mitral_multimodal(
        field_suggestions,
        measurement_warnings,
        transcript=transcript,
        current_measurements=current_measurements,
        species=species or output.exam_context.species,
        reference_context=reference_context,
    )
    field_suggestions, measurement_warnings = _enrich_pulmonary_hypertension_probability(
        field_suggestions,
        measurement_warnings,
        transcript=transcript,
        current_measurements=current_measurements,
        species=species or output.exam_context.species,
    )
    field_suggestions = _normalize_clinical_reference_language(
        field_suggestions,
        current_measurements=current_measurements,
        reference_context=reference_context,
    )
    measurements = list(output.measurements)
    derived_right_heart = _derived_right_heart_measurements(
        transcript,
        current_measurements,
    )
    derived_targets = {
        str(item.target_field_key)
        for item in derived_right_heart
        if item.target_field_key
    }
    if derived_targets:
        measurements = [
            item
            for item in measurements
            if str(item.target_field_key or "") not in derived_targets
        ]
    for measurement in derived_right_heart:
        measurements.append(measurement)
    provider_warnings = _filter_contextual_provider_warnings(
        list(output.warnings),
        transcript=transcript,
        current_measurements=current_measurements,
        exam_context=exam_context,
        reference_context=reference_context,
    )
    if any(item.canonical_name == "psap_estimated" for item in derived_right_heart):
        provider_warnings = [
            warning
            for warning in provider_warnings
            if not (
                "pressao sistolica" in _strip_accents(warning.message)
                and "nao foi fornecido" in _strip_accents(warning.message)
            )
        ]
        measurement_warnings.append(
            EchoClinicalWarningOutput(
                warning_type="psap_is_estimate",
                severity="info",
                message=(
                    "A PSAP foi estimada pelo gradiente da regurgitação tricúspide "
                    "somado à pressão atrial direita presumida pelo remodelamento. "
                    "Confirme a estimativa e exclua obstrução da via de saída do "
                    "ventrículo direito antes de interpretar."
                ),
                related_fields=["IT_Vmax", "IT_Grad", "PAD_estimada", "PSAP"],
            )
        )
    warnings = [*measurement_warnings, *provider_warnings]
    existing_by_name: dict[str, list[EchoMeasurementOutput]] = {}
    for measurement in measurements:
        existing_by_name.setdefault(measurement.canonical_name, []).append(measurement)

    for extracted in deterministic:
        candidates = existing_by_name.get(extracted.canonical_name, [])
        matching = any(
            candidate.value is not None
            and extracted.value is not None
            and math.isclose(candidate.value, extracted.value, rel_tol=1e-6, abs_tol=1e-6)
            and (candidate.unit or "") == (extracted.unit or "")
            for candidate in candidates
        )
        if matching:
            continue
        if candidates:
            warnings.append(
                EchoClinicalWarningOutput(
                    warning_type="numeric_conflict",
                    severity="critical",
                    message=(
                        f"Há valores divergentes para {extracted.display_name}; "
                        "nenhum deles foi escolhido automaticamente."
                    ),
                    related_fields=[extracted.canonical_name],
                )
            )
        measurements.append(extracted)
        existing_by_name.setdefault(extracted.canonical_name, []).append(extracted)

    percentages = {
        "ejection_fraction",
        "fractional_shortening",
    }
    validated_measurements: list[EchoMeasurementOutput] = []
    for measurement in measurements:
        safe_measurement = measurement
        if measurement.value is not None and measurement.value < 0:
            warnings.append(
                EchoClinicalWarningOutput(
                    warning_type="negative_measurement",
                    severity="critical",
                    message=f"{measurement.display_name} possui valor negativo e exige revisão.",
                    related_fields=[measurement.canonical_name],
                )
            )
            safe_measurement = measurement.model_copy(
                update={"target_field_key": None}
            )
        expected_unit = _EXPECTED_UNITS.get(measurement.canonical_name)
        if expected_unit and _normalize_unit(measurement.unit) != expected_unit:
            warnings.append(
                EchoClinicalWarningOutput(
                    warning_type="unexpected_measurement_unit",
                    severity="critical",
                    message=(
                        f"{measurement.display_name} possui unidade ausente ou incompatível; "
                        "o valor foi preservado somente para revisão."
                    ),
                    related_fields=[measurement.canonical_name],
                )
            )
            safe_measurement = safe_measurement.model_copy(
                update={"target_field_key": None}
            )
        if (
            measurement.canonical_name in percentages
            and measurement.value is not None
            and measurement.value > 100
        ):
            warnings.append(
                EchoClinicalWarningOutput(
                    warning_type="percentage_out_of_range",
                    severity="critical",
                    message=f"{measurement.display_name} acima de 100%; revisar transcrição e unidade.",
                    related_fields=[measurement.canonical_name],
                )
            )
        validated_measurements.append(safe_measurement)
    measurements = validated_measurements

    velocity = next(
        (
            item.value
            for item in measurements
            if item.canonical_name == "tricuspid_regurgitation_velocity" and item.value is not None
        ),
        None,
    )
    gradient = next(
        (
            item.value
            for item in measurements
            if item.canonical_name == "tricuspid_gradient" and item.value is not None
        ),
        None,
    )
    if velocity is not None and gradient is not None:
        calculated = 4 * (velocity**2)
        tolerance = max(5.0, calculated * 0.2)
        if abs(calculated - gradient) > tolerance:
            warnings.append(
                EchoClinicalWarningOutput(
                    warning_type="velocity_gradient_mismatch",
                    severity="warning",
                    message=(
                        "Velocidade do refluxo tricúspide e gradiente informado parecem "
                        f"incompatíveis pela verificação ΔP = 4 × V² "
                        f"({calculated:.2f} mmHg versus {gradient:g} mmHg). "
                        "Os valores informados foram preservados."
                    ),
                    related_fields=[
                        "tricuspid_regurgitation_velocity",
                        "tricuspid_gradient",
                    ],
                )
            )

    normalized_transcript = _strip_accents(transcript)
    contradiction_pairs = (
        (
            "sem refluxo mitral",
            ("refluxo mitral moderado", "refluxo mitral importante", "refluxo mitral grave"),
            "mitral_regurgitation_contradiction",
            ["valva_mitral"],
        ),
        (
            "atrio esquerdo normal",
            ("atrio esquerdo muito dilatado", "atrio esquerdo aumentado"),
            "left_atrium_contradiction",
            ["atrio_esquerdo"],
        ),
    )
    for negative, positives, warning_type, related_fields in contradiction_pairs:
        if negative in normalized_transcript and any(
            positive in normalized_transcript for positive in positives
        ):
            warnings.append(
                EchoClinicalWarningOutput(
                    warning_type=warning_type,
                    severity="critical",
                    message="A transcrição contém afirmações clínicas contraditórias; revisar antes de aplicar.",
                    related_fields=related_fields,
                )
            )

    existing_warning_keys = set()
    existing_warning_concepts = set()
    deduped_warnings: list[EchoClinicalWarningOutput] = []
    for warning in [*warnings, *numeric_warnings]:
        key = _warning_key(warning)
        concept = _warning_concept(warning)
        if key in existing_warning_keys or concept in existing_warning_concepts:
            continue
        existing_warning_keys.add(key)
        existing_warning_concepts.add(concept)
        deduped_warnings.append(warning)

    if output.conclusion_suggestion and not any(
        suggestion.field_key == "conclusao" for suggestion in field_suggestions
    ):
        field_suggestions.append(
            {
                "field_key": "conclusao",
                "text": "\n".join(output.conclusion_suggestion),
                "confidence": min(
                    [suggestion.confidence for suggestion in output.field_suggestions] or [0.75]
                ),
                "source_spans": [],
                "evidence_type": "diagnostic_suggestion",
            }
        )

    return EchoClinicalStructureOutput.model_validate(
        {
            **output.model_dump(),
            "measurements": measurements,
            "field_suggestions": field_suggestions,
            "warnings": deduped_warnings,
        }
    )
