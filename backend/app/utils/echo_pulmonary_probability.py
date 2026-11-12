"""Reviewed, method-aware canine pulmonary-hypertension probability.

Reinero et al. 2020, Tables 2/3 (10.1111/jvim.15725). Exact 3.0 m/s
belongs to the <=3.0 band, resolving the editorial overlap with "3.0-3.4".
This is echocardiographic probability, not a diagnosis or a pressure grade.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from app.utils.referencia_eco_defaults import normalizar_especie_referencia
from app.utils.echo_unit_provenance import ECHO_LENGTH_KEYS, ambiguous_echo_length_keys, normalize_confirmed_echo_lengths

HP_CONTEXT_KEYS = (
    "HP_ativa", "HP_TRV", "HP_VSVD", "HP_ventriculos", "HP_arteria_pulmonar",
    "HP_atrio_cava", "HP_suporte_automatico", "IT_Vmax", "AP_Ao", "AP",
    "Ao_nivel_AP", "unidade_confirmada_AP", "unidade_confirmada_Ao_nivel_AP",
    "Remodelamento_AD", "HP_RPAD", "HP_RPA_max", "HP_RPA_min", "HP_TA", "HP_TE",
    "HP_IP_inicio",
)
HP_NUMERIC_KEYS = frozenset({
    "IT_Vmax", "AP_Ao", "AP", "Ao_nivel_AP", "HP_RPAD", "HP_RPA_max",
    "HP_RPA_min", "HP_TA", "HP_TE", "HP_IP_inicio",
})
HP_MEASUREMENT_KEYS = frozenset(k for k in HP_CONTEXT_KEYS if k.startswith("HP_")) | {
    "HP_observacoes", "HP_revisao",
}
HP_SITES = ("ventriculos", "arteria_pulmonar", "atrio_cava")
HP_SITE_LABELS = {
    "ventriculos": "Ventrículos", "arteria_pulmonar": "Artéria pulmonar",
    "atrio_cava": "Átrio direito/veia cava caudal",
}
HP_REFERENCE = (
    "Reinero et al. (2020). ACVIM consensus statement guidelines for the diagnosis, "
    "classification, treatment, and monitoring of pulmonary hypertension in dogs. "
    "Tabelas 2 e 3. DOI: 10.1111/jvim.15725."
)
HP_RPAD_REFERENCE = (
    "Visser et al. (2016). Diagnostic Value of Right Pulmonary Artery Distensibility "
    "Index in Dogs with Pulmonary Hypertension: Comparison with Doppler Echocardiographic "
    "Estimates of Pulmonary Arterial Pressure. DOI: 10.1111/jvim.13911."
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float | None:
    raw = _text(value)
    if isinstance(value, bool) or not re.fullmatch(r"[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)(?:[eE][+-]?[0-9]+)?", raw):
        return None
    try:
        number = float(raw.replace(",", "."))
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _species(species: Any) -> str:
    return normalizar_especie_referencia(species) or _text(species)


def _length_context(measurements: dict[str, Any]) -> dict[str, Any]:
    """Use HP's decimal grammar for the entire unit-detection cohort."""
    context = dict(measurements)
    for key in ECHO_LENGTH_KEYS:
        context[key] = _number(measurements.get(key))
    return context


def make_pulmonary_review_stamp(measurements: dict[str, Any], species: Any) -> str:
    context = []
    for key in HP_CONTEXT_KEYS:
        raw = _text(measurements.get(key))
        number = _number(measurements.get(key))
        value = (number if number is not None else raw or None) if key in HP_NUMERIC_KEYS else raw
        context.append([key, value])
    # This state depends on the original cohort of length measurements, not
    # just AP/Ao fields. It is review metadata, never a saved clinical value.
    context.append(["unidades_ambiguas_AP_Ao", sorted(ambiguous_echo_length_keys(_length_context(measurements)) & {"AP", "Ao_nivel_AP"})])
    return json.dumps(["acvim2020-v1", _species(species), context], ensure_ascii=False, separators=(",", ":"))


def has_valid_pulmonary_review(measurements: dict[str, Any], species: Any) -> bool:
    try:
        # Reject NaN/Infinity, including forged JSON constants; they are not clinical numbers.
        def reject_constant(value: str):
            raise ValueError(value)
        saved = json.loads(_text(measurements.get("HP_revisao")), parse_constant=reject_constant)
        expected = json.loads(make_pulmonary_review_stamp(measurements, species))
        # bool == 1 in Python, whereas JSON/JS distinguish their types.
        if not isinstance(saved, list) or len(saved) != 3 or not isinstance(saved[2], list):
            return False
        if any(not isinstance(pair, list) or len(pair) != 2 or isinstance(pair[1], bool) for pair in saved[2]):
            return False
        return saved == expected
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def canine_ph_probability(tr_velocity: float | None, anatomic_sites: int) -> str:
    """Matrix only. None means explicitly nonmeasurable, never an absent input."""
    if not isinstance(anatomic_sites, int) or not 0 <= anatomic_sites <= 3:
        raise ValueError("Anatomic sites must be an integer from 0 to 3")
    if tr_velocity is not None and (_number(tr_velocity) is None or tr_velocity <= 0):
        raise ValueError("TR velocity must be positive and finite or explicitly nonmeasurable")
    if tr_velocity is None or tr_velocity <= 3.0:
        return "alta" if anatomic_sites == 3 else "intermediaria" if anatomic_sites == 2 else "baixa"
    if tr_velocity <= 3.4:
        return "alta" if anatomic_sites >= 2 else "intermediaria"
    return "alta" if anatomic_sites >= 1 else "intermediaria"


def evaluate_pulmonary_probability(measurements: dict[str, Any] | None, species: Any) -> dict[str, Any]:
    m = measurements or {}
    active = _text(m.get("HP_ativa")) == "sim"
    applicable = _species(species) == "Canina"
    review_valid = has_valid_pulmonary_review(m, species)
    trv = _number(m.get("IT_Vmax"))
    trv = trv if trv is not None and trv > 0 and _text(m.get("HP_TRV")) == "adequado" else None
    result = {
        "active": active, "applicable": applicable,
        "status": "inactive" if not active else "pending" if applicable else "unsupported",
        "probability": None, "positive_sites": [], "assessed_sites": [], "missing": [],
        "notes": [], "suggestions": [], "review_valid": review_valid, "evidence": [],
        "summary": "Avaliação de probabilidade de hipertensão pulmonar não ativada.",
        "metrics": {"trv": trv, "rpad": None, "at_et": None, "ap_ao": None, "pr_early": None},
        "psap_usable": not active or (review_valid and trv is not None and _text(m.get("HP_VSVD")) == "sem_obstrucao"),
    }
    if not active:
        return result
    missing, notes, metrics = result["missing"], result["notes"], result["metrics"]
    if applicable and not review_valid:
        missing.append("Reconfirmar avaliação após preencher, editar ou reimportar medidas.")
    trv_state = _text(m.get("HP_TRV"))
    if applicable and trv_state not in {"adequado", "nao_mensuravel"}:
        missing.append("Confirmar qualidade/mensurabilidade da regurgitação tricúspide.")
    elif applicable and trv_state == "adequado" and trv is None:
        missing.append("Informar velocidade tricúspide positiva e finita.")
    if trv_state == "nao_mensuravel":
        notes.append("Regurgitação tricúspide não mensurável; sua ausência não exclui hipertensão pulmonar.")
    rvot = _text(m.get("HP_VSVD"))
    if applicable and rvot != "sem_obstrucao":
        missing.append("Obstrução da via de saída do VD presente; matriz não interpretável." if rvot == "obstrucao" else "Confirmar ausência de obstrução da via de saída do VD.")

    for site in HP_SITES:
        state = _text(m.get("HP_" + site))
        if state in {"sem_sinais", "com_sinais"}:
            result["assessed_sites"].append(site)
        if state == "com_sinais":
            result["positive_sites"].append(site)

    ap_ao = _number(m.get("AP_Ao"))
    if ap_ao is None or ap_ao <= 0:
        ambiguous = ambiguous_echo_length_keys(_length_context(m)) & {"AP", "Ao_nivel_AP"}
        raw_ap, raw_ao = _number(m.get("AP")), _number(m.get("Ao_nivel_AP"))
        # Validate the original syntax before the generic unit normalizer,
        # whose float parser also accepts representations outside HP's grammar.
        normalized = normalize_confirmed_echo_lengths({
            "AP": raw_ap, "Ao_nivel_AP": raw_ao,
            "unidade_confirmada_AP": m.get("unidade_confirmada_AP"),
            "unidade_confirmada_Ao_nivel_AP": m.get("unidade_confirmada_Ao_nivel_AP"),
        })
        ap, ao = _number(normalized.get("AP")), _number(normalized.get("Ao_nivel_AP"))
        ap_unit, ao_unit = _text(m.get("unidade_confirmada_AP")), _text(m.get("unidade_confirmada_Ao_nivel_AP"))
        if ambiguous:
            ap_ao = None
            message = "Confirmar unidade de AP/Ao antes de usar a razão derivada: " + ", ".join(sorted(ambiguous)) + "."
            if applicable and _text(m.get("HP_suporte_automatico")) != "nao":
                missing.append(message)
            else:
                notes.append(message)
        elif ap is not None and ao is not None and ap > 0 and ao > 0 and ap_unit in {"", "cm", "mm"} and ao_unit in {"", "cm", "mm"}:
            ap_ao = ap / ao
        else:
            ap_ao = None
            if raw_ap is not None and raw_ao is not None and raw_ap > 0 and raw_ao > 0 and ap_unit in {"", "cm", "mm"} and ao_unit in {"", "cm", "mm"} and (ap is None or ao is None):
                missing.append("Revisar AP/Ao calculado: resultado deve ser positivo e finito.")
        if ap_ao is not None and (not math.isfinite(ap_ao) or ap_ao <= 0):
            missing.append("Revisar AP/Ao calculado: resultado deve ser positivo e finito.")
            ap_ao = None
    metrics["ap_ao"] = ap_ao
    pr_early = _number(m.get("HP_IP_inicio"))
    metrics["pr_early"] = pr_early if pr_early is not None and pr_early > 0 else None
    rpa_max, rpa_min = _number(m.get("HP_RPA_max")), _number(m.get("HP_RPA_min"))
    has_calipers = bool(_text(m.get("HP_RPA_max")) or _text(m.get("HP_RPA_min")))
    if has_calipers:
        if rpa_max is not None and rpa_min is not None and 0 < rpa_min <= rpa_max:
            metrics["rpad"] = (rpa_max - rpa_min) / rpa_max * 100
            notes.append("RPAD calculado pelos diâmetros máximo e mínimo no mesmo local/ciclo.")
        else:
            missing.append("Revisar diâmetros da artéria pulmonar direita: exigir 0 < mínimo ≤ máximo.")
    else:
        rpad = _number(m.get("HP_RPAD"))
        if rpad is not None and 0 <= rpad <= 100:
            metrics["rpad"] = rpad
            notes.append("RPAD informado diretamente (%).")
        elif _text(m.get("HP_RPAD")):
            missing.append("Revisar RPAD informado: exigir 0 a 100%.")
    ta, te = _number(m.get("HP_TA")), _number(m.get("HP_TE"))
    if ta is not None and te is not None and 0 < ta <= te:
        metrics["at_et"] = ta / te
    elif _text(m.get("HP_TA")) and _text(m.get("HP_TE")):
        missing.append("Revisar TA/TE: exigir 0 < TA ≤ TE no mesmo traçado.")
    elif _text(m.get("HP_TA")) or _text(m.get("HP_TE")):
        notes.append("TA isolado é dado de consulta; não aplicado corte universal de probabilidade.")

    if not applicable:
        result["summary"] = "Matriz canina de probabilidade de hipertensão pulmonar não aplicável à espécie."
        notes.append("Os critérios ACVIM caninos não estabelecem classificação validada para felinos ou outras espécies; métricas e sítios são apenas descritivos, sem aplicação de limiares caninos.")
        return result

    reasons = []
    if ap_ao is not None and ap_ao > 1:
        reasons.append("AP/Ao > 1,0")
    if metrics["pr_early"] is not None and metrics["pr_early"] > 2.5:
        reasons.append("Regurgitação pulmonar no início da diástole > 2,5 m/s")
    if metrics["rpad"] is not None and metrics["rpad"] < 30:
        reasons.append("RPAD < 30%")
    if metrics["at_et"] is not None and metrics["at_et"] < 0.30:
        reasons.append("TA/TE < 0,30")
    if reasons:
        result["suggestions"].append({"site": "arteria_pulmonar", "reasons": reasons})
    if _text(m.get("Remodelamento_AD")) in {"leve", "moderado", "importante"}:
        result["suggestions"].append({"site": "atrio_cava", "reasons": ["Remodelamento do átrio direito informado"]})
    automatic_support = _text(m.get("HP_suporte_automatico")) != "nao"
    if automatic_support:
        for suggestion in result["suggestions"]:
            if suggestion["site"] not in result["positive_sites"]:
                missing.append("Revisar sugestão de sinais em " + HP_SITE_LABELS[suggestion["site"]] + " ou excluir suporte automático por técnica inadequada.")
    else:
        notes.append("Métricas de suporte automático excluídas pelo examinador; sítios classificados pela revisão anatômica.")

    trv_ready = (trv_state == "nao_mensuravel" or trv is not None)
    minimum_probability = canine_ph_probability(trv, len(result["positive_sites"])) if trv_ready else None
    unassessed = [site for site in HP_SITES if site not in result["assessed_sites"]]
    if unassessed and minimum_probability != "alta":
        missing.append("Avaliar os três sítios anatômicos; ausência de preenchimento não significa ausência de sinais.")
    elif unassessed:
        notes.append("Alta probabilidade já sustentada pelos sítios positivos; há sítios não avaliados.")
    result["evidence"] = [
        "TRV não mensurável" if trv_state == "nao_mensuravel" else f"TRV: {trv:g} m/s" if trv is not None else "TRV pendente",
        f"Sítios com sinais: {len(result['positive_sites'])}/3; avaliados: {len(result['assessed_sites'])}/3",
    ]
    if not missing:
        result["status"] = "classified"
        result["probability"] = minimum_probability
        label = "intermediária" if minimum_probability == "intermediaria" else minimum_probability
        result["summary"] = f"Probabilidade ecocardiográfica {label} de hipertensão pulmonar (critérios ACVIM caninos)."
    else:
        result["summary"] = "Probabilidade ecocardiográfica de hipertensão pulmonar pendente de revisão."
    notes.append("PSAP estimada é informação complementar; não define isoladamente a probabilidade ou o diagnóstico de hipertensão pulmonar.")
    return result


def encode_pulmonary_measurement(value: Any) -> str:
    """A JSON string per description line preserves quotes/newlines without injection."""
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def decode_pulmonary_measurement(value: str) -> str:
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else value
    except (ValueError, TypeError):
        return value
