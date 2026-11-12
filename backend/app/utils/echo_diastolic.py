"""Species dispatcher for method-specific diastolic consultation evidence."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.utils.echo_canine_diastolic import canine_diastolic_notes, canine_diastolic_references
from app.utils.echo_feline_diastolic import feline_diastolic_notes, feline_diastolic_references
from app.utils.referencia_eco_defaults import normalizar_especie_referencia


def diastolic_references(measurements: Mapping[str, Any], species: Any) -> dict[str, dict[str, Any]]:
    normalized = normalizar_especie_referencia(species)
    if normalized == "Canina":
        return canine_diastolic_references(measurements, normalized)
    if normalized == "Felina":
        return feline_diastolic_references(measurements, normalized)
    return {}


def diastolic_indices_awaiting_confirmation(measurements: Mapping[str, Any], species: Any) -> set[str]:
    """Mark retained ratios after an explicit review invalidation, not legacy data."""
    if normalizar_especie_referencia(species) not in {"Canina", "Felina"}:
        return set()
    pending: set[str] = set()
    if measurements.get("Diastolica_ondas") == "nao_confirmadas":
        pending.update({"E_A", "E_TRIV", "E_E_linha"})
    if measurements.get("TDI_ondas") == "nao_confirmadas":
        pending.update({"doppler_tecidual_relacao", "E_E_linha"})
    return pending


def diastolic_notes(measurements: Mapping[str, Any], species: Any) -> list[str]:
    normalized = normalizar_especie_referencia(species)
    if normalized == "Canina":
        notes = canine_diastolic_notes(measurements, normalized)
    elif normalized == "Felina":
        notes = feline_diastolic_notes(measurements, normalized)
    else:
        return []
    if measurements.get("Diastolica_ondas") == "nao_confirmadas":
        notes.append("Ondas E/A: separação pendente de reconfirmação. Os índices históricos E/A, E/TRIV e E/e' aguardam revisão; não interpretar esses índices até reconfirmar as ondas.")
    if measurements.get("TDI_ondas") == "nao_confirmadas":
        notes.append("Ondas e'/a': separação pendente de reconfirmação. Os índices históricos e'/a' e E/e' aguardam revisão; não interpretar esses índices até reconfirmar as ondas.")
    return notes
