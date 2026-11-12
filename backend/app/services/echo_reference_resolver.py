"""Versioned, non-destructive policy for echocardiographic comparisons.

The database is an editable numeric catalog, not a per-parameter source registry.
Only reconciled signatures receive a publication attribution. Original bounds
remain in ``catalog_ranges`` even when they cannot support a comparison.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from app.utils.referencia_eco_defaults import (
    normalizar_especie_referencia, obter_tapse_canino_por_peso,
)
from app.utils.echo_low_weight_reference import low_weight_m_mode_ranges, low_weight_reference_seed

POLICY_VERSION = "echo-reference-safety-v2-low-weight"
RANGE_PREFIXES = (
    "lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s", "fs", "ef",
    "tapse", "mapse", "ao", "la", "la_ao", "ap", "ap_ao", "vmax_ao",
    "vmax_pulm", "mv_e", "mv_a", "mv_ea", "mv_dt", "ivrt", "tdi_e",
    "tdi_a", "e_e_linha", "edv", "esv", "sv",
)
_STRUCTURAL_PREFIXES = (
    "lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s", "ao", "la",
    "la_ao", "ap", "ap_ao",
)
_WEIGHT_DOMAINS = {"Canina": (2.2, 95.0), "Felina": (1.5, 11.0)}
# Häggström et al. 2016, Table 3 (corrected version, DOI 10.1111/jvim.14569).
# These prediction limits differ from the clinical LA:Ao <1.5 discussed by
# the authors. Never substitute one statistical meaning for the other.
_FELINE_LA_AO_PI95 = {
    1.5: (.85, 1.40), 2.0: (.85, 1.40), 2.5: (.86, 1.41),
    3.0: (.86, 1.42), 3.5: (.87, 1.42), 4.0: (.88, 1.43),
    4.5: (.88, 1.43), 5.0: (.88, 1.43), 5.5: (.89, 1.44),
    6.0: (.89, 1.44), 6.5: (.90, 1.45), 7.0: (.90, 1.46),
    7.5: (.91, 1.46), 8.0: (.91, 1.47), 8.5: (.92, 1.47),
    9.0: (.92, 1.47), 9.5: (.92, 1.48), 10.0: (.92, 1.48),
    10.5: (.94, 1.49), 11.0: (.94, 1.50),
}
_METHODS = {
    "TAPSE_metodo": "modo_m_apical",
    "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial",
}


def _number(value: Any, *, positive: bool = False) -> float | None:
    try:
        result = float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None
    if not math.isfinite(result) or (positive and result <= 0):
        return None
    return result


def _within(weight: float | None, minimum: float, maximum: float) -> bool:
    return weight is not None and minimum <= weight <= maximum


def _complete(bounds: Mapping[str, Any]) -> bool:
    minimum, maximum = _number(bounds.get("min")), _number(bounds.get("max"))
    return (minimum is not None and maximum is not None and minimum <= maximum
            and (minimum, maximum) != (0, 0))


def resolve_echo_reference(
    referencia: Mapping[str, Any], *, peso_kg: Any = None,
    medidas: Mapping[str, Any] | None = None,
    catalog_weight_min: Any = None, catalog_weight_max: Any = None,
    idade: Any = None,
) -> dict[str, Any]:
    """Return comparison-safe bounds and their auditable original values.

    ``medidas`` contains explicit exam-level acquisition confirmations. Catalog
    management and list responses therefore expose candidates, not confirmed
    TAPSE/LA:Ao ranges. Applying this function repeatedly preserves raw bounds,
    methods, requested weight and catalog coverage.
    """
    result = dict(referencia)
    age = referencia.get("patient_age") if idade is None else idade
    if age is not None:
        result["patient_age"] = age
    old_raw = referencia.get("catalog_ranges")
    raw = {
        prefix: dict(old_raw[prefix])
        if isinstance(old_raw, Mapping) and isinstance(old_raw.get(prefix), Mapping)
        else {"min": referencia.get(f"{prefix}_min"), "max": referencia.get(f"{prefix}_max")}
        for prefix in RANGE_PREFIXES
    }
    # Retain only exact bound keys; do not copy arbitrary client metadata.
    raw = {prefix: {"min": bounds.get("min"), "max": bounds.get("max")}
           for prefix, bounds in raw.items()}
    for prefix, bounds in raw.items():
        result[f"{prefix}_min"], result[f"{prefix}_max"] = bounds["min"], bounds["max"]
    for field in ("fs_source", "tapse_source", "la_ao_source"):
        result.pop(field, None)
    species = normalizar_especie_referencia(referencia.get("especie"))
    weight = _number(peso_kg, positive=True)
    explicit_invalid_weight = peso_kg is not None and weight is None
    if weight is None and not explicit_invalid_weight and "patient_weight_kg" in referencia:
        weight = _number(referencia.get("patient_weight_kg"), positive=True)
    if weight is None and not explicit_invalid_weight and "patient_weight_kg" not in referencia:
        weight = _number(referencia.get("peso_kg"), positive=True)
    row_weight = _number(referencia.get("peso_kg"), positive=True)
    if medidas is None:
        medidas = referencia.get("reference_methods", {})
    methods = {key: medidas.get(key) for key in (*_METHODS, "VE_tecnica_relatorio")
               if isinstance(medidas, Mapping) and medidas.get(key)}
    cover_min = _number(catalog_weight_min if catalog_weight_min is not None
                        else referencia.get("catalog_weight_min"), positive=True)
    cover_max = _number(catalog_weight_max if catalog_weight_max is not None
                        else referencia.get("catalog_weight_max"), positive=True)
    metadata: dict[str, dict[str, Any]] = {}
    for prefix, bounds in raw.items():
        complete = _complete(bounds)
        metadata[prefix] = {
            "status": "catalog" if complete else "unavailable",
            "reason": "Faixa cadastrada; publicação e método ainda não reconciliados" if complete else "Faixa não cadastrada",
            "source": None, "doi": None, "statistic": "catalog_interval" if complete else None,
            "population": None, "min_weight_kg": None, "max_weight_kg": None,
            "candidate_min": bounds["min"] if complete else None,
            "candidate_max": bounds["max"] if complete else None,
        }
        if not complete:
            result[f"{prefix}_min"] = result[f"{prefix}_max"] = None

    def block(prefix: str, reason: str) -> None:
        result[f"{prefix}_min"] = result[f"{prefix}_max"] = None
        metadata[prefix].update(status="blocked", reason=reason)

    def published(prefix: str, bounds: tuple[float, float], *, source: str, doi: str,
                  statistic: str, population: str, minimum: float, maximum: float,
                  method_key: str | None = None) -> None:
        meta = metadata[prefix]
        meta.update(source=source, doi=doi, statistic=statistic, population=population,
                    min_weight_kg=minimum, max_weight_kg=maximum,
                    candidate_min=bounds[0], candidate_max=bounds[1])
        if method_key:
            meta.update(required_method=_METHODS[method_key], required_measurement_key=method_key,
                        required_measurement_value=_METHODS[method_key])
        if not _within(weight, minimum, maximum):
            block(prefix, "Peso fora do domínio da publicação")
        elif method_key and methods.get(method_key) != _METHODS[method_key]:
            result[f"{prefix}_min"] = result[f"{prefix}_max"] = None
            meta.update(status="requires_method", reason="Confirme o método de aquisição para aplicar esta faixa")
        else:
            result[f"{prefix}_min"], result[f"{prefix}_max"] = bounds
            meta.update(status="published", reason="Faixa publicada compatível com o método e o peso informados")

    # Descriptive Doppler studies do not validate individual legacy intervals.
    for prefix in ("vmax_ao", "vmax_pulm"):
        block(prefix, "Intervalo individual sem fonte e técnica Doppler validadas")
    block("ef", "FE Teichholz: intervalo não validado por método")
    result["ef_reference_note"] = metadata["ef"]["reason"]

    if species == "Canina":
        if row_weight == 25 and (raw["lvid_d"]["min"], raw["lvid_d"]["max"]) == (33, 42):
            block("lvid_d", "Transcrição legada divergente de Cornell 2004: a Tabela 4 publica 33–48 mm para 25 kg")
        if (raw["fs"]["min"], raw["fs"]["max"]) in {(25, 45), (20.7, 51.9)}:
            published("fs", (20.7, 51.9), source="Visser et al. 2019; modo M, eixo curto; cães adultos saudáveis",
                      doi="10.1111/jvim.15562", statistic="reference_interval_95",
                      population="122 cães adultos saudáveis", minimum=2.6, maximum=67.8)
        else:
            block("fs", "FEC sem intervalo publicado reconciliado para esta linha")
        for prefix, unsafe in (("mv_e", {(0.5, 1.09), (0.5, 1.1)}),
                               ("mv_a", {(0.3, 0.8)}), ("mv_dt", {(0, 160)})):
            if (raw[prefix]["min"], raw[prefix]["max"]) in unsafe:
                block(prefix, "Faixa genérica legada sem contexto de idade, frequência cardíaca e fonte reconciliada")
        if (raw["la_ao"]["min"], raw["la_ao"]["max"]) == (0.8, 1.6):
            block("la_ao", "Faixa legada sem método de aquisição identificado")
        else:
            block("la_ao", "AE/Ao sem método e publicação reconciliados para esta linha")
        if raw["tapse"]["min"] is None and raw["tapse"]["max"] is None and _within(weight, 3.0, 45.0):
            published("tapse", obter_tapse_canino_por_peso(weight), source="Visser et al. 2015",
                      doi="10.1016/j.jvc.2014.10.003", statistic="prediction_interval_95",
                      population="Cães saudáveis; TAPSE em modo M na vista apical", minimum=3.0,
                      maximum=45.0, method_key="TAPSE_metodo")
        else:
            block("tapse", "TAPSE sem intervalo publicado reconciliado para o método e peso")
        if (raw["mapse"]["min"], raw["mapse"]["max"]) in {(6.5, 7.5), (10.3, 11.3), (12.1, 18.1)}:
            block("mapse", "Intervalo de confiança da média; não representa intervalo individual de referência")
            metadata["mapse"].update(statistic="confidence_interval_mean", source="Schober e Luis Fuentes 2001")
    elif species == "Felina":
        fs_upper = 63 if row_weight is not None and row_weight >= 9.5 else 62
        if _within(row_weight, 1.5, 11.0) and (raw["fs"]["min"], raw["fs"]["max"]) == (28, fs_upper):
            published("fs", (28, fs_upper), source="Häggström et al. 2016; modo M; gatos adultos de raça pura",
                      doi="10.1111/jvim.14569", statistic="prediction_interval_95",
                      population="18460 gatos adultos de raça pura com ecocardiogramas normais", minimum=1.5, maximum=11.0)
        else:
            block("fs", "FEC sem intervalo publicado reconciliado para esta linha")
        expected = _FELINE_LA_AO_PI95.get(row_weight)
        original = (raw["la_ao"]["min"], raw["la_ao"]["max"])
        if expected and original in {expected, (expected[0], 1.5)}:
            published("la_ao", expected, source="Häggström et al. 2016; Tabela 3; 2D, eixo curto, diástole inicial",
                      doi="10.1111/jvim.14569", statistic="prediction_interval_95",
                      population="18460 gatos adultos de raça pura com ecocardiogramas normais", minimum=1.5,
                      maximum=11.0, method_key="AE_Ao_metodo")
        else:
            block("la_ao", "AE/Ao sem intervalo publicado reconciliado para esta linha e método")
        metadata["la_ao"]["clinical_threshold"] = {
            "operator": "<", "value": 1.5, "source": "Häggström et al. 2016",
            "doi": "10.1111/jvim.14569", "description": "Limiar clínico geral discutido pelos autores; distinto do intervalo de predição por peso",
        }
        block("tapse", "Intervalo canino de TAPSE não aplicável a felinos")
    else:
        block("fs", "Espécie sem intervalo publicado reconciliado")
        block("tapse", "Espécie sem intervalo publicado reconciliado")
        block("la_ao", "Espécie sem intervalo publicado reconciliado")

    domain = _WEIGHT_DOMAINS.get(species)
    if domain:
        reason = None
        if not _within(weight, *domain) or not _within(row_weight, *domain):
            reason = "Peso do paciente ou da linha fora do domínio de referência reconciliado"
        elif cover_min is not None and cover_max is not None and not _within(weight, cover_min, cover_max):
            reason = "Peso fora da cobertura das linhas elegíveis do catálogo"
        if reason:
            for prefix in (*_STRUCTURAL_PREFIXES, "fs"):
                block(prefix, reason)
        for prefix in _STRUCTURAL_PREFIXES:
            metadata[prefix].update(min_weight_kg=domain[0], max_weight_kg=domain[1])

    # Missing coverage is a catalog limitation, not absence of all published
    # low-weight evidence. Never extrapolate the nearest editable catalog row.
    used_model = False
    for prefix, model in low_weight_m_mode_ranges(species, weight, age).items():
        if result.get(f"{prefix}_min") is not None and result.get(f"{prefix}_max") is not None:
            continue
        if isinstance(medidas, Mapping) and medidas.get("VE_tecnica_relatorio") == "2d":
            model.update(status="unavailable", candidate_min=None, candidate_max=None,
                         reason="Modo M: não aplicar à técnica 2D selecionada.")
            for field in ("estimate_min", "estimate_max", "estimate_context"):
                model.pop(field, None)
        metadata[prefix] = model
        result[f"{prefix}_min"] = model.get("candidate_min")
        result[f"{prefix}_max"] = model.get("candidate_max")
        used_model = True
    result.pop("reference_origin", None)
    if used_model:
        result["reference_origin"] = "computed"

    if metadata["fs"]["status"] == "published":
        result["fs_source"] = metadata["fs"]["source"]
    if metadata["tapse"]["status"] == "published":
        result["tapse_source"] = metadata["tapse"]["source"]
    if metadata["la_ao"]["status"] == "published":
        result["la_ao_source"] = metadata["la_ao"]["source"]
    result.update(policy_version=POLICY_VERSION, catalog_ranges=raw, range_metadata=metadata,
                  patient_weight_kg=weight, catalog_weight_min=cover_min, catalog_weight_max=cover_max,
                  reference_methods=methods)
    return result


def select_echo_reference(
    referencias: Iterable[Mapping[str, Any]], *, peso_kg: Any,
    medidas: Mapping[str, Any] | None = None,
    species: Any = None,
    idade: Any = None,
) -> dict[str, Any] | None:
    """Select nearest eligible row; do not reuse catalog extrema out of coverage."""
    weight = _number(peso_kg, positive=True)
    rows = [dict(row) for row in referencias if _number(row.get("peso_kg"), positive=True) is not None]
    if weight is None:
        return None
    if not rows:
        seed = low_weight_reference_seed(species, weight, idade)
        return resolve_echo_reference(seed, peso_kg=weight, medidas=medidas, idade=idade) if seed else None
    species = normalizar_especie_referencia(rows[0].get("especie"))
    rows = [row for row in rows if normalizar_especie_referencia(row.get("especie")) == species]
    domain = _WEIGHT_DOMAINS.get(species)
    eligible = [row for row in rows if not domain or _within(_number(row["peso_kg"], positive=True), *domain)]
    candidates = eligible or rows
    chosen = min(candidates, key=lambda row: (abs(float(row["peso_kg"]) - weight), float(row["peso_kg"])))
    minimum = min(float(row["peso_kg"]) for row in eligible) if eligible else None
    maximum = max(float(row["peso_kg"]) for row in eligible) if eligible else None
    return resolve_echo_reference(chosen, peso_kg=weight, medidas=medidas,
                                  catalog_weight_min=minimum, catalog_weight_max=maximum, idade=idade)


def load_echo_reference(db: Any, *, species: Any, weight_kg: Any,
                        medidas: Mapping[str, Any] | None = None, idade: Any = None) -> dict[str, Any] | None:
    """Use the same selector for API, PDF and assistant database consumers."""
    from sqlalchemy import func
    from app.models.referencia_eco import ReferenciaEco

    normalized = normalizar_especie_referencia(species)
    if not normalized or _number(weight_kg, positive=True) is None:
        return None
    query = db.query(ReferenciaEco)
    if normalized == "Canina":
        query = query.filter(ReferenciaEco.especie.ilike("canin%"))
    elif normalized == "Felina":
        query = query.filter(ReferenciaEco.especie.ilike("felin%"))
    else:
        query = query.filter(func.lower(ReferenciaEco.especie) == normalized.lower())
    rows = [{column.name: getattr(row, column.name) for column in ReferenciaEco.__table__.columns}
            for row in query.all()]
    return select_echo_reference(rows, peso_kg=weight_kg, medidas=medidas, species=normalized, idade=idade)
