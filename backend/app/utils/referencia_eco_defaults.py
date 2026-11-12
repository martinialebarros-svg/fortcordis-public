"""Published echo intervals and method-aware safeguards for stored catalog rows."""
from __future__ import annotations

from typing import Any
import math
import unicodedata

_TAPSE_CANINO_REFERENCIAS_MM: tuple[tuple[float, float, float], ...] = (
    (3.0, 6.6, 10.6),
    (4.0, 7.2, 11.5),
    (5.0, 7.7, 12.3),
    (7.0, 8.5, 13.6),
    (9.0, 9.2, 14.7),
    (12.0, 10.0, 16.0),
    (15.0, 10.7, 17.1),
    (20.0, 11.6, 18.6),
    (25.0, 12.4, 19.9),
    (30.0, 13.1, 21.0),
    (35.0, 13.7, 22.0),
    (40.0, 14.3, 22.8),
    (45.0, 14.8, 23.7),
)
# Intervalos de predição por peso: Visser et al., J Vet Cardiol 2015,
# DOI 10.1016/j.jvc.2014.10.003 (tabela também apresentada na tese do autor).


def normalizar_especie_referencia(especie: Any) -> str | None:
    if especie is None:
        return None

    valor_original = str(especie).strip()
    valor = unicodedata.normalize("NFKD", valor_original)
    valor = valor.encode("ascii", "ignore").decode("ascii").lower()
    if not valor:
        return None
    if valor in {"felina", "felino", "felinos", "feline", "gato", "gatos", "cat", "cats"}:
        return "Felina"
    if valor in {"canina", "canino", "caninos", "canine", "cao", "caes", "cachorro", "cachorros", "dog", "dogs"}:
        return "Canina"
    return valor_original


def _coerce_positive_float(valor: Any) -> float | None:
    if valor in (None, ""):
        return None

    try:
        numero = float(str(valor).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None

    return numero if math.isfinite(numero) and numero > 0 else None


def obter_tapse_canino_por_peso(peso_kg: float) -> tuple[float, float]:
    """Resolve TAPSE by the closest tabulated body weight."""
    _, ref_min, ref_max = min(
        _TAPSE_CANINO_REFERENCIAS_MM,
        key=lambda item: (abs(item[0] - peso_kg), item[0]),
    )
    return ref_min, ref_max


def aplicar_defaults_publicados_caninos(
    referencia: dict[str, Any],
    *,
    peso_kg: Any | None = None,
    medidas: dict[str, Any] | None = None,
    catalog_weight_min: Any | None = None,
    catalog_weight_max: Any | None = None,
) -> dict[str, Any]:
    """Compatibility entry point for the versioned comparison policy."""
    # Local import keeps normalizers and the TAPSE table reusable by the service.
    from app.services.echo_reference_resolver import resolve_echo_reference

    return resolve_echo_reference(
        referencia, peso_kg=peso_kg, medidas=medidas,
        catalog_weight_min=catalog_weight_min, catalog_weight_max=catalog_weight_max,
    )
