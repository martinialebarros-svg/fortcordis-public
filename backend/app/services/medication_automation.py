from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from app.models.atendimento_clinico import Medicamento


def _normalize_token(value: Optional[str]) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_string_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]

    return [item.strip() for item in str(raw).split(",") if item.strip()]


def medication_to_dict(medication: Medicamento) -> Dict[str, Any]:
    return {
        "id": medication.id,
        "nome": medication.nome,
        "principio_ativo": medication.principio_ativo or "",
        "concentracao": medication.concentracao or "",
        "forma_farmaceutica": medication.forma_farmaceutica or "",
        "categoria": medication.categoria or "",
        "classe_terapeutica": medication.classe_terapeutica or "",
        "especie_alvo": medication.especie_alvo or "",
        "dose_min_mg_kg": medication.dose_min_mg_kg,
        "dose_max_mg_kg": medication.dose_max_mg_kg,
        "dose_intervalo_horas": medication.dose_intervalo_horas,
        "dose_unidade": medication.dose_unidade or "mg/kg",
        "via_padrao": medication.via_padrao or "",
        "duracao_padrao": medication.duracao_padrao or "",
        "concentracao_mg_ml": medication.concentracao_mg_ml,
        "concentracao_mg_comprimido": medication.concentracao_mg_comprimido,
        "indicacoes": medication.indicacoes or "",
        "contraindicacoes": medication.contraindicacoes or "",
        "interacoes": _load_string_list(medication.interacoes_json),
        "observacao_seguranca": medication.observacao_seguranca or "",
        "parametrizacao_origem": medication.parametrizacao_origem or "manual",
        "observacoes": medication.observacoes or "",
        "ativo": medication.ativo,
        "parametrizado": any(
            value is not None and value != ""
            for value in (
                medication.dose_min_mg_kg,
                medication.dose_max_mg_kg,
                medication.dose_intervalo_horas,
                medication.via_padrao,
                medication.duracao_padrao,
                medication.concentracao_mg_ml,
                medication.concentracao_mg_comprimido,
            )
        ),
    }


def analyze_prescription_items(
    *,
    peso_kg: Optional[float],
    medicamentos: Dict[int, Dict[str, Any]],
    itens: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    items = list(itens)
    alerts: List[Dict[str, Any]] = []

    indexed_items: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        medication = medicamentos.get(int(item["medicamento_id"])) if item.get("medicamento_id") else None
        indexed_items.append(
            {
                "index": index,
                "item": item,
                "medication": medication,
                "item_key": _normalize_token(item.get("medicamento_nome")),
                "active_key": _normalize_token((medication or {}).get("principio_ativo")),
            }
        )

    analyzed_items: List[Dict[str, Any]] = []
    seen_pairs: set[tuple[int, int, str]] = set()

    for indexed in indexed_items:
        index = indexed["index"]
        item = indexed["item"]
        medication = indexed["medication"]
        item_alerts: List[str] = []
        suggestion: Dict[str, Any] = {}

        if medication:
            dose_min = _as_float(medication.get("dose_min_mg_kg"))
            dose_max = _as_float(medication.get("dose_max_mg_kg"))
            dose_hours = medication.get("dose_intervalo_horas")

            if peso_kg and (dose_min is not None or dose_max is not None):
                dose_base = dose_max if dose_max is not None else dose_min
                dose_total_mg = round(peso_kg * float(dose_base or 0), 2) if dose_base is not None else None
                dose_range_mg = None
                if dose_min is not None and dose_max is not None:
                    dose_range_mg = {
                        "min": round(peso_kg * dose_min, 2),
                        "max": round(peso_kg * dose_max, 2),
                    }

                suggestion = {
                    "dose_referencia_mg_kg": {
                        "min": dose_min,
                        "max": dose_max,
                    },
                    "dose_total_mg": dose_total_mg,
                    "dose_range_mg": dose_range_mg,
                    "intervalo_horas": dose_hours,
                    "via": medication.get("via_padrao") or "",
                    "duracao": medication.get("duracao_padrao") or "",
                    "concentracao_mg_ml": _as_float(medication.get("concentracao_mg_ml")),
                    "concentracao_mg_comprimido": _as_float(medication.get("concentracao_mg_comprimido")),
                    "dose_formatada": format_dose_summary(
                        peso_kg=peso_kg,
                        dose_min_mg_kg=dose_min,
                        dose_max_mg_kg=dose_max,
                        dose_total_mg=dose_total_mg,
                        dose_intervalo_horas=dose_hours,
                    ),
                }

                if suggestion["concentracao_mg_ml"] and dose_total_mg is not None:
                    suggestion["volume_ml"] = round(dose_total_mg / suggestion["concentracao_mg_ml"], 2)
                if suggestion["concentracao_mg_comprimido"] and dose_total_mg is not None:
                    suggestion["comprimidos"] = round(dose_total_mg / suggestion["concentracao_mg_comprimido"], 2)
            elif (dose_min is not None or dose_max is not None) and not peso_kg:
                item_alerts.append("Informe o peso do paciente para calcular a dose automatica.")
            elif not medication.get("parametrizado"):
                item_alerts.append("Medicamento sem parametrizacao de dose padrao.")

            if medication.get("observacao_seguranca"):
                item_alerts.append(str(medication["observacao_seguranca"]))

        for other in indexed_items:
            if other["index"] <= index or not medication or not other["medication"]:
                continue

            current_targets = {
                _normalize_token(token)
                for token in medication.get("interacoes", [])
                if _normalize_token(token)
            }
            other_targets = {
                _normalize_token(token)
                for token in other["medication"].get("interacoes", [])
                if _normalize_token(token)
            }

            other_keys = {
                other["item_key"],
                other["active_key"],
                _normalize_token(other["medication"].get("nome")),
            }
            current_keys = {
                indexed["item_key"],
                indexed["active_key"],
                _normalize_token(medication.get("nome")),
            }

            match_current = next((key for key in other_keys if key and key in current_targets), "")
            match_other = next((key for key in current_keys if key and key in other_targets), "")
            if not match_current and not match_other:
                continue

            pair_key = (index, other["index"], medication.get("nome", ""))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            message = (
                f"Interacao potencial entre {item.get('medicamento_nome') or medication.get('nome')} "
                f"e {other['item'].get('medicamento_nome') or other['medication'].get('nome')}."
            )
            alerts.append(
                {
                    "type": "interacao",
                    "severity": "alta",
                    "item_indexes": [index, other["index"]],
                    "message": message,
                }
            )

        analyzed_items.append(
            {
                "index": index,
                "medicamento_id": item.get("medicamento_id"),
                "medicamento_nome": item.get("medicamento_nome") or (medication or {}).get("nome") or "",
                "parametrizado": bool((medication or {}).get("parametrizado")),
                "classe_terapeutica": (medication or {}).get("classe_terapeutica", ""),
                "dose_sugerida": suggestion,
                "alertas": item_alerts,
            }
        )

    return {
        "peso_kg": peso_kg,
        "itens": analyzed_items,
        "alertas_gerais": alerts,
    }


def format_dose_summary(
    *,
    peso_kg: float,
    dose_min_mg_kg: Optional[float],
    dose_max_mg_kg: Optional[float],
    dose_total_mg: Optional[float],
    dose_intervalo_horas: Optional[int],
) -> str:
    range_label = ""
    if dose_min_mg_kg is not None and dose_max_mg_kg is not None:
        range_label = (
            f"{dose_min_mg_kg:.2f} a {dose_max_mg_kg:.2f} mg/kg "
            f"({round(peso_kg * dose_min_mg_kg, 2):.2f} a {round(peso_kg * dose_max_mg_kg, 2):.2f} mg por dose)"
        )
    elif dose_total_mg is not None and dose_max_mg_kg is not None:
        range_label = f"{dose_max_mg_kg:.2f} mg/kg ({dose_total_mg:.2f} mg por dose)"
    elif dose_total_mg is not None and dose_min_mg_kg is not None:
        range_label = f"{dose_min_mg_kg:.2f} mg/kg ({dose_total_mg:.2f} mg por dose)"

    if dose_intervalo_horas:
        return f"{range_label} a cada {dose_intervalo_horas}h".strip()
    return range_label
