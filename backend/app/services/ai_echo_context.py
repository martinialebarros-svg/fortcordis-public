from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services.echo_reference_resolver import load_echo_reference
from app.utils.referencia_eco_defaults import normalizar_especie_referencia
from app.utils.echo_diastolic import diastolic_references
from app.utils.echo_unit_provenance import (
    clinically_safe_echo_measurements,
)


ECHO_MEASUREMENT_UNITS: dict[str, str] = {
    "DIVEd": "mm",
    "DIVEd_normalizado": "cm/kg^0,294",
    "SIVd": "mm",
    "PLVEd": "mm",
    "DIVES": "mm",
    "SIVs": "mm",
    "PLVES": "mm",
    "DIVEd_2D": "mm",
    "DIVEd_normalizado_2D": "cm/kg^0,316",
    "SIVd_2D": "mm",
    "PLVEd_2D": "mm",
    "DIVES_2D": "mm",
    "SIVs_2D": "mm",
    "PLVES_2D": "mm",
    "VDF": "mL",
    "VDF_2D": "mL",
    "VSF": "mL",
    "VSF_2D": "mL",
    "FE_Teicholz": "%",
    "FE_Teicholz_2D": "%",
    "DeltaD_FS": "%",
    "DeltaD_FS_2D": "%",
    "TAPSE": "mm",
    "MAPSE": "mm",
    "Aorta": "mm",
    "Atrio_esquerdo": "mm",
    "AE_Ao": "adimensional",
    "AE_diametro_max": "mm",
    "AE_diametro_min": "mm",
    "Fracao_encurtamento_AE": "%",
    "Fluxo_auricular": "m/s",
    "Vmax_VSVE": "m/s",
    "Grad_VSVE": "mmHg",
    "Vmax_VSVD": "m/s",
    "Grad_VSVD": "mmHg",
    "Onda_E": "m/s",
    "Onda_A": "m/s",
    "E_A": "adimensional",
    "E_TRIV": "adimensional",
    "TD": "ms",
    "TRIV": "ms",
    "MR_dp_dt": "mmHg/s",
    "e_doppler": "m/s",
    "a_doppler": "m/s",
    "doppler_tecidual_relacao": "adimensional",
    "E_E_linha": "adimensional",
    "AP": "mm",
    "Ao_nivel_AP": "mm",
    "AP_Ao": "adimensional",
    "IM_Vmax": "m/s",
    "IM_Grad": "mmHg",
    "IT_Vmax": "m/s",
    "IT_Grad": "mmHg",
    "IA_Vmax": "m/s",
    "IA_Grad": "mmHg",
    "IP_Vmax": "m/s",
    "IP_Grad": "mmHg",
    "Remodelamento_AD": "qualitativo",
    "PAD_estimada": "mmHg",
    "PSAP": "mmHg",
    "VE_tecnica_relatorio": "qualitativo",
    "Vmax_aorta": "m/s",
    "Grad_aorta": "mmHg",
    "Vmax_pulmonar": "m/s",
    "Grad_pulmonar": "mmHg",
}

ECHO_MEASUREMENT_METHODS: dict[str, str] = {
    **{
        key: "modo M"
        for key in (
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
        )
    },
    **{
        key: "modo bidimensional"
        for key in (
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
        )
    },
    "TAPSE": "excursão sistólica anular",
    "MAPSE": "excursão sistólica anular",
    "Aorta": "modo bidimensional",
    "Atrio_esquerdo": "modo bidimensional",
    "AE_Ao": "modo bidimensional",
    "AE_diametro_max": "vista e metodo de aquisicao a confirmar",
    "AE_diametro_min": "vista e metodo de aquisicao a confirmar",
    "Fracao_encurtamento_AE": "calculada dos diametros informados; confirmar a mesma vista",
    "Fluxo_auricular": "Doppler pulsado",
    "Vmax_VSVE": "Doppler espectral, via de saída do VE",
    "Grad_VSVE": "Gradiente registrado, via de saída do VE; método não informado",
    "Vmax_VSVD": "Doppler espectral, via de saída do VD",
    "Grad_VSVD": "Gradiente registrado, via de saída do VD; método não informado",
    "Onda_E": "Doppler pulsado transmitral",
    "Onda_A": "Doppler pulsado transmitral",
    "E_A": "Doppler pulsado transmitral",
    "E_TRIV": "Doppler pulsado transmitral",
    "TD": "Doppler pulsado transmitral",
    "TRIV": "Doppler pulsado",
    "MR_dp_dt": "Doppler contínuo",
    "e_doppler": "Doppler tecidual",
    "a_doppler": "Doppler tecidual",
    "doppler_tecidual_relacao": "Doppler tecidual",
    "E_E_linha": "Doppler pulsado e tecidual",
    "AP": "modo bidimensional",
    "Ao_nivel_AP": "modo bidimensional",
    "AP_Ao": "modo bidimensional",
    "IM_Vmax": "Doppler contínuo",
    "IM_Grad": "Bernoulli simplificada",
    "IT_Vmax": "Doppler contínuo",
    "IT_Grad": "Bernoulli simplificada",
    "IA_Vmax": "Doppler contínuo",
    "IA_Grad": "Bernoulli simplificada",
    "IP_Vmax": "Doppler contínuo",
    "IP_Grad": "Bernoulli simplificada",
    "Remodelamento_AD": "avaliação morfológica",
    "PAD_estimada": "estimativa ecocardiográfica",
    "PSAP": "estimativa ecocardiográfica",
    "VE_tecnica_relatorio": "seleção do operador",
    # A importação atual não registra se a velocidade foi obtida por PW ou CW.
    "Vmax_aorta": "Doppler espectral; modalidade não informada",
    "Grad_aorta": "Doppler espectral; modalidade não informada",
    "Vmax_pulmonar": "Doppler espectral; modalidade não informada",
    "Grad_pulmonar": "Doppler espectral; modalidade não informada",
}


REFERENCE_FIELD_MAP: dict[str, tuple[str, str, str]] = {
    "DIVEd": ("lvid_d_min", "lvid_d_max", "mm"),
    "DIVES": ("lvid_s_min", "lvid_s_max", "mm"),
    "SIVd": ("ivs_d_min", "ivs_d_max", "mm"),
    "SIVs": ("ivs_s_min", "ivs_s_max", "mm"),
    "PLVEd": ("lvpw_d_min", "lvpw_d_max", "mm"),
    "PLVES": ("lvpw_s_min", "lvpw_s_max", "mm"),
    "VDF": ("edv_min", "edv_max", "mL"),
    "VSF": ("esv_min", "esv_max", "mL"),
    "DeltaD_FS": ("fs_min", "fs_max", "%"),
    "TAPSE": ("tapse_min", "tapse_max", "mm"),
    "MAPSE": ("mapse_min", "mapse_max", "mm"),
    "Aorta": ("ao_min", "ao_max", "mm"),
    "Atrio_esquerdo": ("la_min", "la_max", "mm"),
    "AE_Ao": ("la_ao_min", "la_ao_max", "adimensional"),
    "AP": ("ap_min", "ap_max", "mm"),
    "AP_Ao": ("ap_ao_min", "ap_ao_max", "adimensional"),
    "Onda_E": ("mv_e_min", "mv_e_max", "m/s"),
    "Onda_A": ("mv_a_min", "mv_a_max", "m/s"),
    "E_A": ("mv_ea_min", "mv_ea_max", "adimensional"),
    "TD": ("mv_dt_min", "mv_dt_max", "ms"),
    "TRIV": ("ivrt_min", "ivrt_max", "ms"),
    "e_doppler": ("tdi_e_min", "tdi_e_max", "m/s"),
    "a_doppler": ("tdi_a_min", "tdi_a_max", "m/s"),
    "E_E_linha": ("e_e_linha_min", "e_e_linha_max", "adimensional"),
    "Vmax_aorta": ("vmax_ao_min", "vmax_ao_max", "m/s"),
    "Vmax_pulmonar": ("vmax_pulm_min", "vmax_pulm_max", "m/s"),
}


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def load_echo_reference_context(
    db: Session,
    *,
    species: str | None,
    weight_kg: Any,
    current_measurements: dict[str, Any] | None = None,
    age: Any = None,
) -> dict[str, Any] | None:
    normalized_species = normalizar_especie_referencia(species)
    resolved_weight = _positive_float(weight_kg)
    if not normalized_species or resolved_weight is None:
        return None

    resolved_reference = load_echo_reference(
        db, species=normalized_species, weight_kg=resolved_weight,
        medidas=current_measurements, idade=age,
    )
    if resolved_reference is None:
        return None
    ranges: dict[str, dict[str, Any]] = {}
    for measurement_key, (minimum_key, maximum_key, unit) in REFERENCE_FIELD_MAP.items():
        prefix = minimum_key.removesuffix("_min")
        metadata = resolved_reference.get("range_metadata", {}).get(prefix, {})
        # Unreconciled catalog numbers and candidate method ranges are not
        # validated individual intervals and must not enter the model prompt.
        if metadata.get("status") != "published":
            continue
        if (current_measurements or {}).get("VE_tecnica_relatorio") == "2d" and measurement_key in {
            "DIVEd", "DIVES", "SIVd", "SIVs", "PLVEd", "PLVES", "VDF", "VSF", "DeltaD_FS",
        }:
            continue
        minimum = resolved_reference.get(minimum_key)
        maximum = resolved_reference.get(maximum_key)
        if measurement_key in {"e_doppler", "a_doppler"}:
            minimum = float(minimum) / 100 if minimum is not None else None
            maximum = float(maximum) / 100 if maximum is not None else None
        if minimum is None or maximum is None:
            continue
        ranges[measurement_key] = {
            "min": minimum,
            "max": maximum,
            "unit": unit,
        }
        for key in ("source", "doi", "statistic", "population", "required_method",
                    "required_measurement_key", "required_measurement_value",
                    "min_weight_kg", "max_weight_kg"):
            if metadata.get(key) is not None:
                ranges[measurement_key][key] = metadata[key]

    return {
        "source": "tabela_de_referencia_carregada",
        "reference_id": resolved_reference.get("id"),
        "species": normalized_species,
        "patient_weight_kg": resolved_weight,
        "nearest_reference_weight_kg": resolved_reference.get("peso_kg"),
        "ranges": ranges,
    }


def safe_measurement_context(
    current_measurements: dict[str, str] | None,
    *,
    species: str | None = None,
    reference_context: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    safe: dict[str, dict[str, Any]] = {}
    normalized_measurements = clinically_safe_echo_measurements(current_measurements or {})
    resolved_species = normalizar_especie_referencia(
        species or (reference_context or {}).get("species")
    )
    ranges = safe_reference_context(
        reference_context, current_measurements=normalized_measurements,
        species=resolved_species,
    ).get("ranges", {})
    diastolic_consultation = diastolic_references(normalized_measurements, resolved_species)
    # Historical indices remain stored after edit/reimport, but are not evidence
    # for the clinical prompt until their acquisition domain is reconfirmed.
    # An absent protocol alone must not suppress genuinely legacy canine data.
    excluded_diastolic_indices: set[str] = set()
    for method_key, wave_key, dependent_indices in (
        ("Diastolica_metodo", "Diastolica_ondas", {"E_A", "E_TRIV", "E_E_linha"}),
        ("TDI_metodo", "TDI_ondas", {"doppler_tecidual_relacao", "E_E_linha"}),
    ):
        wave_state = normalized_measurements.get(wave_key)
        reviewed = resolved_species == "Felina" or (
            resolved_species == "Canina"
            and bool(wave_state or normalized_measurements.get(method_key))
        )
        if reviewed and wave_state != "separadas":
            excluded_diastolic_indices.update(dependent_indices)
    for key, value in normalized_measurements.items():
        if key in excluded_diastolic_indices:
            continue
        # Keep numeric history in the exam, but never offer a fused peak or its
        # ratios as an individual diastolic measurement to the clinical model.
        if diastolic_consultation.get(key, {}).get("kind") == "uninterpretable":
            continue
        # Registros antigos usam Cornell (0,294) e novos usam Visser (0,316).
        # Sem proveniência por valor, o índice 2D persistido não é evidência segura para a IA.
        if key == "DIVEd_normalizado_2D":
            continue
        if key == "DIVEd_normalizado" and resolved_species != "Canina":
            continue
        normalized = str(value or "").strip()
        if key not in ECHO_MEASUREMENT_UNITS:
            continue
        if key == "Remodelamento_AD":
            if normalized.lower() in {"ausente", "leve", "moderado", "importante"}:
                safe[key] = {
                    "value": normalized.lower(),
                    "unit": ECHO_MEASUREMENT_UNITS[key],
                    "method": ECHO_MEASUREMENT_METHODS[key],
                }
            continue
        if key == "VE_tecnica_relatorio":
            if normalized.lower() in {"modo_m", "2d"}:
                safe[key] = {
                    "value": normalized.lower(),
                    "unit": ECHO_MEASUREMENT_UNITS[key],
                    "method": ECHO_MEASUREMENT_METHODS[key],
                }
            continue
        if not re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", normalized):
            continue
        item: dict[str, Any] = {
            "value": normalized,
            "unit": ECHO_MEASUREMENT_UNITS[key],
            "method": ECHO_MEASUREMENT_METHODS[key],
        }
        if key in {
            f"{prefix}_{site}"
            for prefix in ("Vmax", "Grad")
            for site in ("VSVE", "aorta", "VSVD", "pulmonar")
        }:
            origin = str(normalized_measurements.get(f"{key}_origem") or "").strip()
            if origin in {"importado", "calculado"}:
                item["origin"] = origin
                if key.startswith("Grad_"):
                    item["method"] = (
                        "Bernoulli simplificada (4 × V²)"
                        if origin == "calculado"
                        else "Gradiente importado; método de aquisição não informado"
                    )
            source_label = str(normalized_measurements.get(f"{key}_rotulo_origem") or "").strip()
            if source_label:
                item["source_label"] = source_label[:200]
        reference_range = ranges.get(key)
        if isinstance(reference_range, dict):
            item["reference"] = reference_range
        safe[key] = item
    return safe


def safe_reference_context(
    reference_context: dict[str, Any] | None,
    *,
    current_measurements: dict[str, Any] | None = None,
    species: str | None = None,
) -> dict[str, Any]:
    """Minimize prompt references to validated publication metadata and bounds."""
    if not isinstance(reference_context, dict):
        return {}
    resolved_species = normalizar_especie_referencia(species or reference_context.get("species"))
    patient_weight = _positive_float(reference_context.get("patient_weight_kg"))
    measurements = clinically_safe_echo_measurements(current_measurements or {})
    safe = {key: reference_context[key] for key in (
        "source", "reference_id", "species", "patient_weight_kg", "nearest_reference_weight_kg",
    ) if key in reference_context}
    safe["ranges"] = {}
    ranges = reference_context.get("ranges", {})
    if not isinstance(ranges, dict):
        return safe
    for key, reference in ranges.items():
        if not isinstance(reference, dict) or not _reference_matches_measurement(
            key, measurements, resolved_species, reference, patient_weight
        ):
            continue
        safe["ranges"][key] = {field: reference[field] for field in (
            "min", "max", "unit", "source", "doi", "statistic", "population", "required_method",
            "required_measurement_key", "required_measurement_value",
            "min_weight_kg", "max_weight_kg",
        ) if field in reference}
    return safe


def _reference_matches_measurement(
    key: str,
    measurements: dict[str, Any],
    species: str | None,
    reference: dict[str, Any],
    patient_weight: float | None,
) -> bool:
    """Defend even direct AI payloads against stale or method-ambiguous ranges."""
    published_sources = {
        ("Canina", "DeltaD_FS"): ("10.1111/jvim.15562", "reference_interval_95", 2.6, 67.8),
        ("Felina", "DeltaD_FS"): ("10.1111/jvim.14569", "prediction_interval_95", 1.5, 11.0),
        ("Canina", "TAPSE"): ("10.1016/j.jvc.2014.10.003", "prediction_interval_95", 3.0, 45.0),
        ("Felina", "AE_Ao"): ("10.1111/jvim.14569", "prediction_interval_95", 1.5, 11.0),
    }
    expected_source = published_sources.get((species, key))
    if (expected_source is None or not reference.get("source")
            or (reference.get("doi"), reference.get("statistic")) != expected_source[:2]
            or patient_weight is None or not expected_source[2] <= patient_weight <= expected_source[3]):
        return False
    try:
        minimum, maximum = float(reference.get("min")), float(reference.get("max"))
    except (TypeError, ValueError):
        return False
    if not math.isfinite(minimum) or not math.isfinite(maximum) or not 0 < minimum <= maximum:
        return False
    if measurements.get("VE_tecnica_relatorio") == "2d" and key in {
        "DIVEd", "DIVES", "SIVd", "SIVs", "PLVEd", "PLVES", "VDF", "VSF", "DeltaD_FS",
    }:
        return False
    if key == "TAPSE" and measurements.get("TAPSE_metodo") != "modo_m_apical":
        return False
    if key == "AE_Ao" and species == "Felina" and measurements.get("AE_Ao_metodo") != "2d_eixo_curto_diastole_inicial":
        return False
    required_key = reference.get("required_measurement_key")
    required_value = reference.get("required_measurement_value")
    return not required_key or measurements.get(required_key) == required_value
