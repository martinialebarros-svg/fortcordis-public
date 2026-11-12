"""Source-bound M-mode fallback when a catalog has no usable low-weight row.

Never fills volumes, Doppler, annular excursion, 2D or atrial/aortic dimensions.
Extrapolated limits are descriptive estimates, NOT individual reference bounds.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from app.utils.referencia_eco_defaults import normalizar_especie_referencia

LOW_WEIGHT_PREFIXES = ("lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s")
# Isayama et al. 2022, Table 2: 2.5/97.5 percentiles and scaling exponent.
# Dimensions are in cm before conversion; approximate allometric PI limits,
# not the rounded, weight-specific regression predictions of Table 3.
TOY_M_MODE = {
    "lvid_d": (1.02, 1.57, .332), "lvid_s": (.54, 1.15, .263),
    "ivs_d": (.15, .77, .486), "ivs_s": (.46, .83, .238),
    "lvpw_d": (.33, .57, .275), "lvpw_s": (.43, .75, .310),
}
# Häggström et al. 2016, corrected Table 3, normal cohort (18,460 cats).
# Table 2 CIs describe coefficient uncertainty and MUST NOT serve as PIs.
FELINE_M_MODE_NODES = {
    1.5: {"lvid_d": (9.5, 15), "lvid_s": (4.2, 9.6), "ivs_d": (2.3, 4),
          "ivs_s": (3.5, 6.7), "lvpw_d": (2.2, 3.8), "lvpw_s": (3.6, 6.5)},
    2.0: {"lvid_d": (10.2, 16), "lvid_s": (4.6, 10.5), "ivs_d": (2.5, 4.3),
          "ivs_s": (3.7, 7.2), "lvpw_d": (2.4, 4.1), "lvpw_s": (3.9, 7.1)},
    2.5: {"lvid_d": (10.9, 17), "lvid_s": (4.8, 11.2), "ivs_d": (2.6, 4.5),
          "ivs_s": (3.9, 7.6), "lvpw_d": (2.5, 4.4), "lvpw_s": (4.1, 7.5)},
    3.0: {"lvid_d": (11.4, 17.8), "lvid_s": (5.1, 11.7), "ivs_d": (2.7, 4.7),
          "ivs_s": (4.1, 7.9), "lvpw_d": (2.6, 4.5), "lvpw_s": (4.3, 7.9)},
}
# Central allometric exponents from the NORMAL cohort, Table 2. Below 1.5 kg
# these scale the nearest tabulated limits as an UNVALIDATED system estimate.
FELINE_EXPONENTS = {"lvid_d": .262, "lvid_s": .261, "ivs_d": .204,
                    "ivs_s": .227, "lvpw_d": .244, "lvpw_s": .263}


def _round_mm(value: float) -> float:
    """Positive values: same half-up hundredth representation as the browser."""
    return math.floor(value * 100 + .5) / 100


def low_weight_age_context(age: Any) -> str:
    """Conservative <12-month software guard, not a maturity cutoff from a study."""
    text = unicodedata.normalize("NFKD", str(age or "").strip()).encode("ascii", "ignore").decode().lower()
    year_range = re.fullmatch(r"(\d+)[–-](\d+) anos \(estimada pelo ano\)", str(age or "").lower())
    if year_range:
        return "adult" if int(year_range[1]) >= 1 else "unknown"
    if str(age or "").lower() == "0–11 meses (estimada pelo ano)":
        return "juvenile"
    text = re.sub(r"\s*\(estimada\)$", "", text)
    if re.fullmatch(r"(?:filhote|juvenil|kitten|puppy|em crescimento)", text):
        return "juvenile"
    if re.fullmatch(r"adult[oa]|adult", text):
        return "adult"
    tokens = list(re.finditer(r"(\d+(?:[.,]\d+)?)\s*(anos?|years?|a|y|mes(?:es)?|months?|m|dias?|days?|d|semanas?|weeks?|w)\b", text))
    if not tokens:
        return "unknown"
    remaining = text
    for token in reversed(tokens):
        remaining = remaining[:token.start()] + " " + remaining[token.end():]
    if re.sub(r"[\s,;+]|\be\b|\band\b", "", remaining):
        return "unknown"
    months = 0.0
    for token in tokens:
        number = float(token[1].replace(",", "."))
        unit = token[2]
        months += number * (12 if unit.startswith(("a", "y")) else 1 if unit.startswith("m")
                            else 7 / 30.4375 if unit.startswith(("s", "w")) else 1 / 30.4375)
    return "juvenile" if months < 12 else "adult"


def low_weight_m_mode_ranges(species: Any, weight: float | None, age: Any = None) -> dict[str, dict[str, Any]]:
    species = normalizar_especie_referencia(species)
    if species not in {"Canina", "Felina"} or weight is None or not math.isfinite(weight) or not 0 < weight < 3:
        return {}
    estimated = weight < 1.5
    age_context = low_weight_age_context(age)
    output = {}
    for prefix in LOW_WEIGHT_PREFIXES:
        if species == "Canina":
            lower, upper, exponent = TOY_M_MODE[prefix]
            bounds = [_round_mm(10 * coefficient * weight ** exponent) for coefficient in (lower, upper)]
            calculation = "extrapolated" if estimated else "allometric"
            formula = f"10 x ({lower}; {upper}) x peso^{exponent} mm"
            source = "Isayama et al. 2022; Tabela 2; limites alométricos aproximados; modo M"
            doi = "10.3389/fvets.2022.918457"
            population = "86 cães adultos de pequeno porte, não sedados; peso <5 kg; domínio tabulado 1,5-5 kg"
            statistic = "approximate_allometric_prediction_limits_95"
        else:
            exponent = FELINE_EXPONENTS[prefix]
            source = "Häggström et al. 2016; Tabela 3 corrigida; modo M"
            doi = "10.1111/jvim.14569"
            population = "18460 gatos adultos de raça pura com ecocardiogramas normais; domínio tabulado 1,5-11 kg"
            if estimated:
                bounds = [_round_mm(bound * (weight / 1.5) ** exponent)
                          for bound in FELINE_M_MODE_NODES[1.5][prefix]]
                calculation, statistic = "extrapolated", "extrapolated_estimate"
                formula = f"limites tabulados de 1,5 kg x (peso / 1,5)^{exponent}"
            else:
                lower_weight = max(node for node in FELINE_M_MODE_NODES if node <= weight)
                upper_weight = min(node for node in FELINE_M_MODE_NODES if node >= weight)
                lower = FELINE_M_MODE_NODES[lower_weight][prefix]
                upper = FELINE_M_MODE_NODES[upper_weight][prefix]
                factor = 0 if lower_weight == upper_weight else (weight - lower_weight) / (upper_weight - lower_weight)
                bounds = [_round_mm(low + factor * (high - low)) for low, high in zip(lower, upper)]
                calculation = "tabulated" if lower_weight == upper_weight else "interpolated"
                statistic = "prediction_interval_95" if calculation == "tabulated" else "interpolated_prediction_limits_95"
                formula = f"Tabela 3: {lower_weight:g}-{upper_weight:g} kg; interpolação linear dos limites" if factor else "Tabela 3: limites do peso tabulado"
        if not 0 < bounds[0] < bounds[1]:
            continue
        reason = ("Estimativa por extrapolação abaixo de 1,5 kg; sem intervalo individual validado e sem classificação automática. "
                  if estimated else "Limites calculados por interpolação entre pesos tabulados. " if calculation == "interpolated"
                  else "Limites alométricos aproximados calculados para o peso real. " if calculation == "allometric"
                  else "Intervalo do peso tabulado na publicação. ")
        reason += "Referência de adultos; não aplicar automaticamente a animais em crescimento nem concluir diagnóstico isoladamente."
        meta = dict(status="estimated" if estimated else "published", source=source, doi=doi,
                    statistic="extrapolated_estimate" if estimated else statistic,
                    population=population, min_weight_kg=1.5, max_weight_kg=5 if species == "Canina" else 11,
                    model_weight_kg=weight, calculation=calculation, formula=formula, exponent=exponent,
                    reason=reason)
        if estimated:
            meta.update(estimate_min=bounds[0], estimate_max=bounds[1], candidate_min=None, candidate_max=None)
            meta["estimate_context"] = "weight_extrapolation"
        else:
            meta.update(candidate_min=bounds[0], candidate_max=bounds[1])
        if age_context == "juvenile":
            meta.update(status="unavailable", candidate_min=None, candidate_max=None,
                        reason="Referência de adultos não aplicada: paciente em crescimento; sem referência pediátrica reconciliada.")
            for field in ("estimate_min", "estimate_max", "estimate_context"):
                meta.pop(field, None)
        elif age_context == "unknown":
            meta.update(status="estimated", candidate_min=None, candidate_max=None,
                        estimate_min=bounds[0], estimate_max=bounds[1],
                        estimate_context="weight_extrapolation" if estimated else "age_unconfirmed",
                        reason=reason + " Idade/maturidade não confirmada; limites de adultos apenas para consulta, sem classificação automática.")
        output[prefix] = meta
    return output


def low_weight_reference_seed(species: Any, weight: float | None, age: Any = None) -> dict[str, Any] | None:
    """An ephemeral carrier, never a row inserted into the editable catalog."""
    normalized = normalizar_especie_referencia(species)
    if not low_weight_m_mode_ranges(normalized, weight):
        return None
    return {"id": 0, "especie": normalized, "peso_kg": weight, "reference_origin": "computed", "patient_age": age}
