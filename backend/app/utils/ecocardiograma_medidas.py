from __future__ import annotations

import re
from typing import Any
from app.utils.echo_unit_provenance import ECHO_LENGTH_KEYS, CONFIRMED_UNIT_PREFIX
from app.utils.echo_reference_methods import ECHO_REFERENCE_METHOD_VALUES
from app.utils.echo_diastolic_aliases import ECHO_DIASTOLIC_CANONICAL_KEYS


LV_M_MODE_KEYS = {
    "DIVEd",
    "DIVEd_normalizado",
    "SIVd",
    "PLVEd",
    "DIVES",
    "SIVs",
    "PLVES",
    "VDF",
    "VSF",
    "FE_Teicholz",
    "DeltaD_FS",
}

LV_2D_KEYS = {
    "DIVEd_2D",
    "DIVEd_normalizado_2D",
    "SIVd_2D",
    "PLVEd_2D",
    "DIVES_2D",
    "SIVs_2D",
    "PLVES_2D",
    "VDF_2D",
    "VSF_2D",
    "FE_Teicholz_2D",
    "DeltaD_FS_2D",
}

OUTFLOW_MEASUREMENT_KEYS = {
    "Vmax_VSVE", "Grad_VSVE", "Vmax_aorta", "Grad_aorta",
    "Vmax_VSVD", "Grad_VSVD", "Vmax_pulmonar", "Grad_pulmonar",
}

_NUMERIC_VALUE_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$"
)


def _has_positive_measurement(
    measurements: dict[str, Any],
    keys: set[str],
) -> bool:
    for key in keys:
        raw_value = str(measurements.get(key) or "").strip().replace(",", ".")
        if not raw_value:
            continue
        try:
            if float(raw_value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def inferir_tecnica_ve_relatorio(
    measurements: dict[str, Any],
) -> str | None:
    selected = str(measurements.get("VE_tecnica_relatorio") or "").strip().lower()
    if selected in {"modo_m", "2d"}:
        return selected

    has_m_mode = _has_positive_measurement(measurements, LV_M_MODE_KEYS)
    has_2d = _has_positive_measurement(measurements, LV_2D_KEYS)
    if has_m_mode and not has_2d:
        return "modo_m"
    if has_2d and not has_m_mode:
        return "2d"
    return None


def extrair_medidas_ecocardiograma_da_descricao(
    description: str | None,
) -> dict[str, str]:
    if not description:
        return {}

    section_match = re.search(
        r"##\s*Medidas\s+Ecocardiogr(?:a|á)ficas\s*(.*?)(?=\n##\s*|\Z)",
        str(description),
        re.IGNORECASE | re.DOTALL,
    )
    if not section_match:
        return {}

    measurements: dict[str, str] = {}
    for match in re.finditer(
        r"^[ \t]*-[ \t]*([A-Za-z0-9_]+):[ \t]*(.*?)[ \t]*$",
        section_match.group(1),
        re.MULTILINE,
    ):
        key = match.group(1)
        raw_value = match.group(2).strip()
        if key in ECHO_DIASTOLIC_CANONICAL_KEYS:
            # An explicit blank or invalid canonical value blocks older aliases.
            # Preserve it in the read projection without accepting it as a peak.
            measurements[key] = (raw_value.replace(",", ".")
                                 if _NUMERIC_VALUE_PATTERN.fullmatch(raw_value) else raw_value)
            continue
        if not raw_value:
            continue

        if key.endswith("_rotulo_origem") and key.removesuffix("_rotulo_origem") in OUTFLOW_MEASUREMENT_KEYS:
            measurements[key] = raw_value
            continue

        if key.endswith("_origem") and key.removesuffix("_origem") in OUTFLOW_MEASUREMENT_KEYS:
            if raw_value in {"importado", "informado", "calculado"}:
                measurements[key] = raw_value
            continue

        if key == "VE_tecnica_relatorio":
            normalized = raw_value.lower().replace("-", "_").replace(" ", "_")
            if normalized in {"modo_m", "2d"}:
                measurements[key] = normalized
            continue

        if key == "VE_vista_2D":
            if raw_value in {"eixo_curto", "eixo_longo"}:
                measurements[key] = raw_value
            continue

        if key in ECHO_REFERENCE_METHOD_VALUES:
            if raw_value in ECHO_REFERENCE_METHOD_VALUES[key]:
                measurements[key] = raw_value
            continue

        if key == "Remodelamento_AD":
            normalized = raw_value.lower()
            if normalized in {"ausente", "leve", "moderado", "importante"}:
                measurements[key] = normalized
            continue

        if key.startswith(CONFIRMED_UNIT_PREFIX):
            measurement_key = key[len(CONFIRMED_UNIT_PREFIX):]
            unit = raw_value.lower()
            if measurement_key in ECHO_LENGTH_KEYS and unit in {"cm", "mm"}:
                measurements[key] = unit
            continue

        if _NUMERIC_VALUE_PATTERN.fullmatch(raw_value):
            measurements[key] = raw_value.replace(",", ".")
        elif key in OUTFLOW_MEASUREMENT_KEYS:
            # Preserve a filled invalid value for confirmation. Dropping it
            # would make reopening/PDF treat it as an absent gradient to derive.
            measurements[key] = raw_value

    inferred = inferir_tecnica_ve_relatorio(measurements)
    if inferred:
        measurements["VE_tecnica_relatorio"] = inferred
    return measurements
