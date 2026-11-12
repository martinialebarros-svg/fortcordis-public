"""Resolve supported legacy diastolic names without changing stored history."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


# Keep the supported names in parity with canonicalFelineDiastolicKey in the UI.
_DIASTOLIC_ALIASES = {
    "MV_E": "Onda_E", "MV_A": "Onda_A", "MV_E_A": "E_A", "MV_DT": "TD",
    "IVRT": "TRIV", "MV_E_TRIV": "E_TRIV", "TDI_e": "e_doppler",
    "TDI_a": "a_doppler", "EEp": "E_E_linha",
}

# Presence in this set carries an explicit clearing/unresolved signal through
# description storage. It must not be replaced by a retained historical alias.
ECHO_DIASTOLIC_CANONICAL_KEYS = frozenset({
    *_DIASTOLIC_ALIASES.values(), "doppler_tecidual_relacao",
})


def normalize_echo_diastolic_aliases(measurements: Mapping[str, Any]) -> dict[str, Any]:
    """Add canonical names to a copy; explicit canonical entries always win.

    An empty, zero or None canonical value can represent a deliberate clearing.
    Neither it nor the original aliases, metadata or acquisition state changes.
    No measurements, indices or method confirmations are derived here.
    """
    normalized = dict(measurements)
    for alias, canonical in _DIASTOLIC_ALIASES.items():
        if canonical not in normalized and alias in measurements:
            normalized[canonical] = measurements[alias]
    return normalized
