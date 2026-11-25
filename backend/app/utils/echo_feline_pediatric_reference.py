"""Source-bound descriptive lookup for kittens; never classification bounds.

Gunther-Harrington et al., JFMS 2021;23:293–301, Supplementary Table 1.
DOI 10.1177/1098612X20946461. Values below are the published pooled RIs,
not observed extrema or the parenthesized 90% CIs of the reference limits.
The weight-adjusted Table 2 is deliberately not used (unreconciled values).
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from app.utils.referencia_eco_defaults import normalizar_especie_referencia

PEDIATRIC_PROTOCOL = "gunther_harrington_2021_sem_sedacao"
PEDIATRIC_SOURCE = "Gunther-Harrington et al. 2021; Tabela suplementar 1"
PEDIATRIC_DOI = "10.1177/1098612X20946461"
PEDIATRIC_POPULATION = "88 gatos domésticos de pelo curto, não sedados, de 6–16 semanas"
PEDIATRIC_NOTE = (
    "* Coorte pediátrica de 6–16 semanas: intervalos de referência agrupados, "
    "não ajustados ao peso, apenas para consulta e sem classificação automática. "
    "Interpretar em conjunto com peso, técnica, morfologia e demais achados."
)

# Canonical report units. Published lengths in cm are converted exactly to mm.
# Do not map aortic-root Ao onto the separate Ao_nivel_AP measurement.
PEDIATRIC_RANGES = {
    "DIVEd": (8.6, 15.3, "mm", "m"),
    "DIVES": (2.8, 8.4, "mm", "m"),
    "SIVd": (2.1, 4.5, "mm", "m"),
    "SIVs": (3.7, 7.2, "mm", "m"),
    "PLVEd": (2.0, 4.5, "mm", "m"),
    "PLVES": (3.8, 7.4, "mm", "m"),
    "DeltaD_FS": (36.6, 68.6, "%", "m"),
    "DIVEd_2D": (8.3, 14.0, "mm", "2d"),
    "DIVES_2D": (3.4, 8.8, "mm", "2d"),
    "SIVd_2D": (2.3, 4.4, "mm", "2d"),
    "SIVs_2D": (3.3, 7.1, "mm", "2d"),
    "PLVEd_2D": (2.0, 4.5, "mm", "2d"),
    "PLVES_2D": (3.4, 6.5, "mm", "2d"),
    "Aorta": (4.7, 7.8, "mm", "atrial"),
    "Atrio_esquerdo": (6.3, 10.6, "mm", "atrial"),
    "AE_Ao": (1.12, 1.63, "", "atrial"),
    "Vmax_aorta": (0.72, 1.39, "m/s", "doppler"),
    "Vmax_pulmonar": (0.53, 1.35, "m/s", "doppler"),
}


def _age_text(age: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(age or "").strip())
    # Preserve punctuation: dropping Unicode dashes would turn '1–2 semanas'
    # into '12 semanas', or a negative age into a positive one.
    text = "".join(char for char in normalized if not unicodedata.combining(char)).lower()
    return re.sub(r"\s*\(estimada\)$", "", text)


def is_feline_pediatric_context(species: Any, age: Any) -> bool:
    """Also guard a simple age range that may include a juvenile.

    A range is never a precise age: it can withhold adult comparisons but cannot
    unlock pediatric numbers. Keep the existing canine/adult guard unchanged.
    """
    from app.utils.echo_low_weight_reference import low_weight_age_context
    if normalizar_especie_referencia(species) != "Felina":
        return False
    if low_weight_age_context(age) == "juvenile":
        return True
    match = re.fullmatch(
        r"(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*"
        r"(anos?|years?|a|y|mes(?:es)?|months?|m|dias?|days?|d|semanas?|weeks?|w)",
        _age_text(age),
    )
    if not match:
        return False
    lower = float(match[1].replace(",", "."))
    unit = match[3]
    factor = 12 if unit.startswith(("a", "y")) else 1 if unit.startswith("m") else 7 / 30.4375 if unit.startswith(("s", "w")) else 1 / 30.4375
    return math.isfinite(lower) and lower * factor < 12


def pediatric_age_weeks(age: Any) -> float | None:
    """Parse explicit durations only; vague/year-only estimates prove no weeks.

    Month=30.4375 days and year=365.25 days are conversion conventions, not
    greater precision than the recorded age. A patient labelled simply
    'filhote' or '0–11 meses (estimada pelo ano)' is intentionally unresolved.
    """
    text = _age_text(age)
    tokens = list(re.finditer(r"(\d+(?:[.,]\d+)?)\s*(anos?|years?|a|y|mes(?:es)?|months?|m|dias?|days?|d|semanas?|weeks?|w)\b", text))
    if not tokens:
        return None
    remaining = text
    for token in reversed(tokens):
        remaining = remaining[:token.start()] + " " + remaining[token.end():]
    if re.sub(r"[\s,;+]|\be\b|\band\b", "", remaining):
        return None
    days = 0.0
    seen_units: set[str] = set()
    for token in tokens:
        number = float(token[1].replace(",", "."))
        unit = token[2]
        group = "year" if unit.startswith(("a", "y")) else "month" if unit.startswith("m") else "week" if unit.startswith(("s", "w")) else "day"
        if group in seen_units:
            return None
        seen_units.add(group)
        days += number * {"year": 365.25, "month": 30.4375, "week": 7, "day": 1}[group]
    return days / 7 if math.isfinite(days) else None


def pediatric_range_text(lower: float, upper: float, unit: str, *, compact: bool = False) -> str:
    bounds = f"{lower:.2f}–{upper:.2f}".replace(".", ",")
    value = f"{bounds} {unit}".strip()
    return value + ("*" if compact else " (coorte pediátrica)")


def feline_pediatric_reference(age: Any, weight: Any, methods: Mapping[str, Any]) -> dict[str, Any]:
    """Return descriptive RIs only after age, weight and acquisition checks.

    The caller owns the species/juvenile guard. No weight domain is invented:
    the article supplies median/IQR, not the observed minimum and maximum.
    """
    weeks = pediatric_age_weeks(age)
    try:
        valid_weight = not isinstance(weight, bool) and math.isfinite(float(weight)) and float(weight) > 0
    except (TypeError, ValueError, OverflowError):
        valid_weight = False
    global_reason = (
        "Idade em semanas não confirmada; informe uma duração numérica."
        if weeks is None else
        "Idade fora da população estudada de 6–16 semanas."
        if not 6 <= weeks <= 16 else
        "Informe um peso positivo e válido; os intervalos agrupados não são ajustados ao peso."
        if not valid_weight else ""
    )
    ranges = {}
    for key, (lower, upper, unit, family) in PEDIATRIC_RANGES.items():
        reason = global_reason
        status = "unavailable" if reason else "descriptive"
        if not reason and methods.get("Pediatria_protocolo") != PEDIATRIC_PROTOCOL:
            status, reason = "requires_method", "Confirme o protocolo pediátrico de aquisição sem sedação."
        elif not reason and family == "m" and methods.get("VE_tecnica_relatorio") != "modo_m":
            status, reason = "requires_method", "Confirme modo M em eixo curto no nível das cordoalhas."
        elif not reason and family == "2d" and (
            methods.get("VE_tecnica_relatorio") != "2d" or methods.get("VE_vista_2D") != "eixo_longo"
        ):
            status, reason = "requires_method", "Confirme aquisição 2D em eixo longo para estas medidas."
        elif not reason and family == "atrial" and methods.get("AE_Ao_metodo") != "2d_eixo_curto_diastole_inicial":
            status, reason = "requires_method", "Confirme AE/Ao 2D em eixo curto na diástole inicial."
        ranges[key] = {
            "status": status,
            "lower": lower if status == "descriptive" else None,
            "upper": upper if status == "descriptive" else None,
            "unit": unit,
            "text": pediatric_range_text(lower, upper, unit) if status == "descriptive" else "",
            "reason": reason or "Intervalo agrupado da coorte pediátrica, não ajustado ao peso; sem classificação automática.",
            "source": PEDIATRIC_SOURCE, "doi": PEDIATRIC_DOI,
            "statistic": "published_cohort_reference_interval",
        }
    return {
        "source": PEDIATRIC_SOURCE, "doi": PEDIATRIC_DOI, "population": PEDIATRIC_POPULATION,
        "patient_age_weeks": weeks, "min_age_weeks": 6, "max_age_weeks": 16,
        "reason": global_reason or "Intervalos agrupados para consulta; confirmar o método de cada medida e interpretar com o peso.",
        "ranges": ranges,
    }
