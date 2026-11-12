"""Conservative interpretation of legacy echocardiographic length units."""

from __future__ import annotations

import math
from typing import Any


ECHO_LENGTH_KEYS = {
    "DIVEd", "SIVd", "PLVEd", "DIVES", "SIVs", "PLVES",
    "DIVEd_2D", "SIVd_2D", "PLVEd_2D", "DIVES_2D", "SIVs_2D", "PLVES_2D",
    "Aorta", "Atrio_esquerdo", "AE_diametro_max", "AE_diametro_min", "Ao_nivel_AP", "AP",
}
CONFIRMED_UNIT_PREFIX = "unidade_confirmada_"


def _positive_number(value: Any) -> float | None:
    try:
        parsed = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def confirmed_echo_unit(measurements: dict[str, Any], key: str) -> str | None:
    if key not in ECHO_LENGTH_KEYS:
        return None
    unit = str(measurements.get(f"{CONFIRMED_UNIT_PREFIX}{key}") or "").strip().lower()
    return unit if unit in {"cm", "mm"} else None


def ambiguous_echo_length_keys(measurements: dict[str, Any]) -> set[str]:
    values = {
        key: number
        for key in ECHO_LENGTH_KEYS
        if (number := _positive_number(measurements.get(key))) is not None
    }
    candidates = {key for key, value in values.items() if 0.3 <= value <= 3.5}
    millimeters = sum(value >= 5 for value in values.values())
    if len(values) < 3 or len(candidates) < 3 or len(candidates) < 2 * millimeters:
        return set()
    return {key for key in candidates if confirmed_echo_unit(measurements, key) is None}


def normalize_confirmed_echo_lengths(measurements: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(measurements)
    for key in ECHO_LENGTH_KEYS:
        if confirmed_echo_unit(measurements, key) != "cm":
            continue
        value = _positive_number(measurements.get(key))
        if value is not None:
            normalized[key] = str(value * 10)
    return normalized


def clinically_safe_echo_measurements(measurements: dict[str, Any]) -> dict[str, Any]:
    """Context for clinical comparisons, excluding uncertain or stale lengths."""
    ambiguous = ambiguous_echo_length_keys(measurements)
    safe = normalize_confirmed_echo_lengths(measurements)
    for key in ambiguous:
        safe.pop(key, None)
    for key in list(safe):
        if key.startswith(CONFIRMED_UNIT_PREFIX):
            safe.pop(key)
    for diameter, derived in (
        ("DIVEd", "DIVEd_normalizado"),
        ("DIVEd_2D", "DIVEd_normalizado_2D"),
    ):
        if diameter in ambiguous or confirmed_echo_unit(measurements, diameter) == "cm":
            safe.pop(derived, None)
    return safe
