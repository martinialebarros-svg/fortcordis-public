"""Helpers for clinic travel matrix (phase 1)."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace
from typing import Iterable, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.google_maps_usage_metrica import GoogleMapsUsageMetrica
from app.services.google_maps_cost_control import (
    GoogleMapsCostBlocked, authorize_google_call, block_cache_only_lookup, cache_only_operation, cache_first_operation, agenda_execution_route_cache,
)

PERFIS_VALIDOS = {"comercial", "plantao"}
VELOCIDADE_MEDIA_KMH = {
    "comercial": 26.0,
    "plantao": 32.0,
}
BUFFER_MINUTOS = {
    "comercial": 8,
    "plantao": 5,
}
DEFAULT_KM_MESMA_CIDADE = 12.0
DEFAULT_KM_OUTRA_CIDADE = 42.0
MIN_DURACAO_MINUTOS = 5
GOOGLE_DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GOOGLE_ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GOOGLE_ROUTES_FIELD_MASK = "routes.distanceMeters,routes.duration,routes.staticDuration"
GOOGLE_TIMEOUT_SECONDS = 8.0
DEFAULT_METRICAS_WINDOW_DIAS = 30
GOOGLE_MAPS_COST_MODEL_VERSION = "2026-05-29"
ROUTES_QPM_HARD_LIMIT = 3000
DISTANCE_MATRIX_EPM_HARD_LIMIT = 60000

GOOGLE_MAPS_SKU_PRICING = {
    # Routes (new API)
    "routes_compute_routes_essentials": {
        "label": "Routes: Compute Routes Essentials",
        "free_cap": 10000,
        "tiers": [
            (100000, 5.00),
            (500000, 4.00),
            (1000000, 3.00),
            (5000000, 1.50),
            (None, 0.38),
        ],
    },
    "routes_compute_routes_pro": {
        "label": "Routes: Compute Routes Pro",
        "free_cap": 5000,
        "tiers": [
            (100000, 10.00),
            (500000, 8.00),
            (1000000, 6.00),
            (5000000, 3.00),
            (None, 0.75),
        ],
    },
    # Distance Matrix (legacy API)
    "distance_matrix_legacy_basic": {
        "label": "Distance Matrix (Legacy)",
        "free_cap": 10000,
        "tiers": [
            (100000, 5.00),
            (None, 4.00),
        ],
    },
    "distance_matrix_legacy_advanced": {
        "label": "Distance Matrix Advanced (Legacy)",
        "free_cap": 5000,
        "tiers": [
            (100000, 10.00),
            (None, 8.00),
        ],
    },
}


def normalizar_perfil(perfil: Optional[str]) -> str:
    perfil_norm = str(perfil or "comercial").strip().lower() or "comercial"
    return perfil_norm if perfil_norm in PERFIS_VALIDOS else "comercial"


def normalizar_perfis(perfis: Optional[Iterable[str]]) -> list[str]:
    if not perfis:
        return ["comercial", "plantao"]
    perfis_norm = []
    for item in perfis:
        perfil_norm = normalizar_perfil(item)
        if perfil_norm not in perfis_norm:
            perfis_norm.append(perfil_norm)
    return perfis_norm or ["comercial", "plantao"]


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_decimal_2(value: float) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _utc_now_naive() -> datetime:
    return datetime.utcnow()


def _cache_max_age_days() -> int:
    try:
        return max(0, int(getattr(settings, "GOOGLE_ROUTES_CACHE_MAX_AGE_DAYS", 7) or 0))
    except (TypeError, ValueError):
        return 7


def _cache_expires_by_age() -> bool:
    return bool(getattr(settings, "GOOGLE_ROUTES_CACHE_EXPIRE_BY_AGE", False))


def _metrics_retention_days() -> int:
    try:
        return max(1, int(getattr(settings, "GOOGLE_MAPS_USAGE_METRICS_RETENTION_DAYS", 90) or 90))
    except (TypeError, ValueError):
        return 90


def _force_refresh_heuristica_com_api_key() -> bool:
    return bool(getattr(settings, "LOGISTICA_FORCE_REFRESH_HEURISTICA_COM_API_KEY", False))


def _allow_live_google_lookups_on_read() -> bool:
    return bool(getattr(settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", False))


def _google_traffic_aware_enabled() -> bool:
    return bool(getattr(settings, "LOGISTICA_GOOGLE_TRAFFIC_AWARE", False))


def _map_metric_to_google_sku(operation: str, provider: str) -> Optional[str]:
    op = str(operation or "").strip().lower()
    prov = str(provider or "").strip().lower()

    if op in {"compute_routes", "compute_routes_pro"}:
        if "traffic" in prov or prov in {"routes_api", "routes_api_pro"}:
            return "routes_compute_routes_pro"
        return "routes_compute_routes_essentials"

    if op == "distance_matrix":
        if "traffic" in prov or prov in {"distance_matrix", "distance_matrix_advanced"}:
            return "distance_matrix_legacy_advanced"
        return "distance_matrix_legacy_basic"

    return None


def _calcular_custo_tierizado(eventos: int, sku_config: dict) -> float:
    total_eventos = max(0, int(eventos or 0))
    if total_eventos <= 0:
        return 0.0

    free_cap = max(0, int(sku_config.get("free_cap") or 0))
    tiers = sku_config.get("tiers") or []

    custo = 0.0
    cursor = free_cap
    remaining = max(0, total_eventos - free_cap)
    for tier in tiers:
        limite_superior, valor_por_mil = tier
        preco = float(valor_por_mil or 0.0)
        if remaining <= 0:
            break
        if limite_superior is None:
            quantidade = remaining
        else:
            limite_abs = max(cursor, int(limite_superior))
            faixa = max(0, limite_abs - cursor)
            quantidade = min(remaining, faixa)
            cursor = limite_abs

        if quantidade > 0 and preco > 0:
            custo += (quantidade / 1000.0) * preco
        remaining -= quantidade

    return round(custo, 4)


def _resumir_custo_google_maps(metricas: list[GoogleMapsUsageMetrica], dias_janela: int) -> dict:
    dias_norm = max(1, int(dias_janela or DEFAULT_METRICAS_WINDOW_DIAS))
    dias_projecao = 30

    # Cenarios:
    # - conservador: somente status "ok".
    # - teto_pratico: tudo que nao foi "skipped" por politica local.
    cenarios = {
        "conservador": {"statuses": {"ok"}},
        "teto_pratico": {"statuses": {"ok", "empty", "error", "unknown"}},
    }

    breakdown: dict[str, dict[str, dict]] = {}
    custos_por_cenario: dict[str, dict] = {}
    eventos_por_dia: dict[str, dict[str, int]] = {}
    eventos_por_operacao: dict[str, int] = defaultdict(int)
    eventos_por_provider: dict[str, int] = defaultdict(int)

    for item in metricas:
        operation = str(getattr(item, "operation", "") or "unknown").strip().lower() or "unknown"
        provider = str(getattr(item, "provider", "") or "unknown").strip().lower() or "unknown"
        status = str(getattr(item, "status", "") or "unknown").strip().lower() or "unknown"
        created_at = _normalize_datetime(getattr(item, "created_at", None)) or _utc_now_naive()
        dia = created_at.date().isoformat()

        eventos_por_operacao[operation] += 1
        eventos_por_provider[provider] += 1
        eventos_por_dia.setdefault(dia, defaultdict(int))
        eventos_por_dia[dia][operation] += 1

        sku = _map_metric_to_google_sku(operation, provider)
        if not sku:
            continue

        for nome_cenario, cfg in cenarios.items():
            if status not in cfg["statuses"]:
                continue
            cenario = breakdown.setdefault(nome_cenario, {})
            bucket = cenario.setdefault(
                sku,
                {
                    "sku": sku,
                    "label": GOOGLE_MAPS_SKU_PRICING.get(sku, {}).get("label", sku),
                    "events_window": 0,
                },
            )
            bucket["events_window"] += 1

    for nome_cenario in cenarios.keys():
        skus = breakdown.get(nome_cenario, {})
        total_window = 0.0
        total_proj_30d = 0.0
        rows = []
        for sku, bucket in skus.items():
            sku_cfg = GOOGLE_MAPS_SKU_PRICING.get(sku, {})
            events_window = int(bucket.get("events_window") or 0)
            events_proj_30d = int(math.ceil((events_window / max(1, dias_norm)) * dias_projecao))
            cost_window = _calcular_custo_tierizado(events_window, sku_cfg)
            cost_proj_30d = _calcular_custo_tierizado(events_proj_30d, sku_cfg)
            total_window += cost_window
            total_proj_30d += cost_proj_30d
            rows.append(
                {
                    "sku": sku,
                    "label": bucket.get("label"),
                    "events_window": events_window,
                    "events_projected_30d": events_proj_30d,
                    "estimated_cost_window_usd": round(cost_window, 2),
                    "estimated_cost_projected_30d_usd": round(cost_proj_30d, 2),
                }
            )

        rows.sort(key=lambda r: r["estimated_cost_projected_30d_usd"], reverse=True)
        custos_por_cenario[nome_cenario] = {
            "window_days": dias_norm,
            "projected_days": dias_projecao,
            "estimated_total_cost_window_usd": round(total_window, 2),
            "estimated_total_cost_projected_30d_usd": round(total_proj_30d, 2),
            "breakdown": rows,
        }

    chamadas_routing_dia = {
        dia: int(
            op_counts.get("compute_routes", 0)
            + op_counts.get("compute_routes_pro", 0)
            + op_counts.get("distance_matrix", 0)
        )
        for dia, op_counts in eventos_por_dia.items()
    }
    pico_dia = max(chamadas_routing_dia.values()) if chamadas_routing_dia else 0
    media_dia = (
        int(math.ceil(sum(chamadas_routing_dia.values()) / max(1, len(chamadas_routing_dia))))
        if chamadas_routing_dia
        else 0
    )
    quota_diaria_recomendada = max(200, int(math.ceil(pico_dia * 1.25))) if pico_dia > 0 else 200
    alerta_diario = max(100, int(math.floor(quota_diaria_recomendada * 0.8)))
    qpm_soft = max(1, int(math.ceil(quota_diaria_recomendada / 24.0 / 60.0 * 2.0)))

    recomendacoes_quotas = {
        "routes_api": {
            "daily_quota_recommended_requests": quota_diaria_recomendada,
            "daily_alert_threshold_requests": alerta_diario,
            "qpm_soft_limit_recommended": qpm_soft,
            "qpm_hard_limit_google": ROUTES_QPM_HARD_LIMIT,
        },
        "distance_matrix_legacy": {
            # No fluxo atual cada chamada representa 1 origem x 1 destino (1 elemento).
            "daily_quota_recommended_elements": quota_diaria_recomendada,
            "daily_alert_threshold_elements": alerta_diario,
            "epm_soft_limit_recommended": qpm_soft,
            "epm_hard_limit_google": DISTANCE_MATRIX_EPM_HARD_LIMIT,
        },
        "based_on_window": {
            "window_days": dias_norm,
            "average_daily_calls": media_dia,
            "peak_daily_calls": pico_dia,
        },
    }

    return {
        "cost_model_version": GOOGLE_MAPS_COST_MODEL_VERSION,
        "currency": "USD",
        "events_by_operation": dict(sorted(eventos_por_operacao.items())),
        "events_by_provider": dict(sorted(eventos_por_provider.items())),
        "estimated_costs": custos_por_cenario,
        "quota_recommendations": recomendacoes_quotas,
    }


def _http_get_json(url: str, timeout: float = GOOGLE_TIMEOUT_SECONDS) -> dict:
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FortCordis/1.0",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    return json.loads(payload or "{}")


def _http_post_json(url: str, body: dict, headers: dict, timeout: float = GOOGLE_TIMEOUT_SECONDS) -> dict:
    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    return json.loads(payload or "{}")


def _cidade_estado(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _mesma_cidade(origem: Clinica, destino: Clinica) -> bool:
    cidade_origem = _cidade_estado(origem.cidade)
    cidade_destino = _cidade_estado(destino.cidade)
    estado_origem = _cidade_estado(origem.estado)
    estado_destino = _cidade_estado(destino.estado)
    if not cidade_origem or not cidade_destino:
        return False
    if cidade_origem != cidade_destino:
        return False
    if estado_origem and estado_destino and estado_origem != estado_destino:
        return False
    return True


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    raio_terra_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return raio_terra_km * c


def _endereco_texto_clinica(clinica: Clinica) -> str:
    endereco_parts = [
        str(getattr(clinica, "endereco", "") or "").strip(),
        str(getattr(clinica, "numero", "") or "").strip(),
        str(getattr(clinica, "bairro", "") or "").strip(),
        str(getattr(clinica, "cidade", "") or "").strip(),
        str(getattr(clinica, "estado", "") or "").strip(),
        str(getattr(clinica, "cep", "") or "").strip(),
        "Brasil",
    ]
    return ", ".join([p for p in endereco_parts if p]).strip()


def _waypoint_google_routes(clinica: Clinica) -> Optional[dict]:
    place_id = str(getattr(clinica, "place_id", "") or "").strip()
    if place_id:
        return {"placeId": place_id}

    lat = _safe_float(getattr(clinica, "latitude", None))
    lng = _safe_float(getattr(clinica, "longitude", None))
    if None not in (lat, lng):
        return {
            "location": {
                "latLng": {
                    "latitude": float(lat),
                    "longitude": float(lng),
                }
            }
        }

    endereco = _endereco_texto_clinica(clinica)
    if endereco:
        return {"address": endereco}
    return None


def _ref_google_maps(clinica: Clinica) -> Optional[str]:
    place_id = str(getattr(clinica, "place_id", "") or "").strip()
    if place_id:
        return f"place_id:{place_id}"

    lat = _safe_float(getattr(clinica, "latitude", None))
    lng = _safe_float(getattr(clinica, "longitude", None))
    if None not in (lat, lng):
        return f"{lat:.8f},{lng:.8f}"

    endereco = _endereco_texto_clinica(clinica)
    return endereco or None


def _row_base_datetime(row: Optional[ClinicaDeslocamento]) -> Optional[datetime]:
    if row is None:
        return None
    updated = _normalize_datetime(getattr(row, "updated_at", None))
    created = _normalize_datetime(getattr(row, "created_at", None))
    return updated or created


def _clinic_geocode_datetime(clinica: Optional[Clinica]) -> Optional[datetime]:
    return _normalize_datetime(getattr(clinica, "geocode_at", None)) if clinica else None


def _entity_lookup_id(entity: Optional[Clinica]) -> int:
    try:
        return int(getattr(entity, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _build_google_metric_context(origem: Clinica, destino: Clinica, perfil: str) -> dict:
    return {
        "origem_clinica_id": _entity_lookup_id(origem) or None,
        "destino_clinica_id": _entity_lookup_id(destino) or None,
        "perfil": normalizar_perfil(perfil),
    }


def _append_google_metric_event(
    telemetry_events: Optional[list[dict]],
    *,
    service: str,
    operation: str,
    provider: str,
    status: str,
    context: Optional[dict] = None,
) -> None:
    if not isinstance(telemetry_events, list):
        return
    payload = {
        "service": str(service or "").strip() or "maps",
        "operation": str(operation or "").strip() or "unknown",
        "provider": str(provider or "").strip() or "unknown",
        "status": str(status or "").strip().lower() or "unknown",
    }
    if isinstance(context, dict):
        payload.update(
            {
                "origem_clinica_id": context.get("origem_clinica_id"),
                "destino_clinica_id": context.get("destino_clinica_id"),
                "perfil": context.get("perfil"),
            }
        )
    telemetry_events.append(payload)


def registrar_google_maps_metricas(
    db: Session,
    telemetry_events: Optional[list[dict]],
) -> int:
    if not isinstance(telemetry_events, list) or not telemetry_events:
        return 0

    rows = []
    for event in telemetry_events:
        if not isinstance(event, dict):
            continue
        rows.append(
            GoogleMapsUsageMetrica(
                service=str(event.get("service") or "maps").strip() or "maps",
                operation=str(event.get("operation") or "unknown").strip() or "unknown",
                provider=str(event.get("provider") or "unknown").strip() or "unknown",
                status=str(event.get("status") or "unknown").strip().lower() or "unknown",
                origem_clinica_id=event.get("origem_clinica_id"),
                destino_clinica_id=event.get("destino_clinica_id"),
                perfil=str(event.get("perfil") or "").strip() or None,
            )
        )

    if not rows:
        return 0

    db.add_all(rows)
    return len(rows)


def _deslocamento_esta_atual(
    row: Optional[ClinicaDeslocamento],
    *,
    origem: Clinica,
    destino: Clinica,
) -> bool:
    if row is None:
        return False
    if bool(getattr(row, "manual_override", False)):
        return True

    fonte = str(getattr(row, "fonte", "") or "").strip().lower()
    if fonte.startswith("heuristica"):
        origem_ref = _ref_google_maps(origem)
        destino_ref = _ref_google_maps(destino)
        if (
            _force_refresh_heuristica_com_api_key()
            and origem_ref
            and destino_ref
            and str(settings.GOOGLE_MAPS_API_KEY or "").strip()
        ):
            return False

    row_at = _row_base_datetime(row)
    if row_at is None:
        return False

    cache_max_age_days = _cache_max_age_days()
    if _cache_expires_by_age() and fonte.startswith("google_") and cache_max_age_days > 0:
        limite = _utc_now_naive() - timedelta(days=cache_max_age_days)
        if row_at < limite:
            return False

    for clinica_at in (_clinic_geocode_datetime(origem), _clinic_geocode_datetime(destino)):
        if clinica_at and row_at < clinica_at:
            return False

    return True


def _cache_only_route_available(row, *, origem, destino) -> bool:
    """Only existing route evidence may satisfy the zero-new-charge policy.

    Manual overrides retain their existing authorized semantics. Google rows
    must still satisfy the configured age/location checks; this helper
    never refreshes timestamps or treats historical heuristic rows as routes.
    """
    if row is None or row.duracao_min is None:
        return False
    if bool(getattr(row, "manual_override", False)):
        return True
    source = str(getattr(row, "fonte", "") or "").strip().lower()
    age_policy_valid = not _cache_expires_by_age() or _cache_max_age_days() > 0
    return age_policy_valid and source.startswith(("google_routes_api", "google_distance_matrix")) and _deslocamento_esta_atual(row, origem=origem, destino=destino)


def _parse_duration_seconds(duration_value) -> Optional[int]:
    if duration_value is None:
        return None
    text = str(duration_value).strip()
    if not text:
        return None
    if text.endswith("s"):
        text = text[:-1]
    try:
        seconds = float(text)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return int(math.ceil(seconds))


def _consultar_google_routes_api_raw(
    origem_waypoint: dict,
    destino_waypoint: dict,
    *,
    telemetry_events: Optional[list[dict]] = None,
    metric_context: Optional[dict] = None,
) -> Optional[dict]:
    api_key = str(settings.GOOGLE_MAPS_API_KEY or "").strip()
    if not api_key:
        return None

    traffic_aware = _google_traffic_aware_enabled()
    provider = "routes_api_traffic" if traffic_aware else "routes_api_basic"
    body = {
        "origin": origem_waypoint,
        "destination": destino_waypoint,
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE" if traffic_aware else "TRAFFIC_UNAWARE",
        "languageCode": "pt-BR",
        "units": "METRIC",
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "FortCordis/1.0",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": GOOGLE_ROUTES_FIELD_MASK,
    }

    # Reserve before network I/O, outside the provider's fallback handler. A
    # budget/consent failure must never become a second API call or a heuristic.
    authorize_google_call("routes_pro" if traffic_aware else "routes_essentials")
    try:
        data = _http_post_json(GOOGLE_ROUTES_API_URL, body, headers=headers)
    except Exception:
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="compute_routes",
            provider=provider,
            status="error",
            context=metric_context,
        )
        return None

    routes = data.get("routes") or []
    if not isinstance(routes, list) or not routes:
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="compute_routes",
            provider=provider,
            status="empty",
            context=metric_context,
        )
        return None

    route = routes[0] or {}
    distance_meters = route.get("distanceMeters")
    if distance_meters is None:
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="compute_routes",
            provider=provider,
            status="empty",
            context=metric_context,
        )
        return None

    try:
        distance_km = max(0.0, float(distance_meters) / 1000.0)
    except (TypeError, ValueError):
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="compute_routes",
            provider=provider,
            status="error",
            context=metric_context,
        )
        return None

    duration_secs = _parse_duration_seconds(route.get("duration"))
    static_duration_secs = _parse_duration_seconds(route.get("staticDuration"))

    duration_traffic_min = (
        max(0, int(math.ceil(duration_secs / 60.0))) if duration_secs is not None else None
    )
    duration_base_min = (
        max(0, int(math.ceil(static_duration_secs / 60.0)))
        if static_duration_secs is not None
        else duration_traffic_min
    )

    if duration_base_min is None and duration_traffic_min is None:
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="compute_routes",
            provider=provider,
            status="empty",
            context=metric_context,
        )
        return None

    _append_google_metric_event(
        telemetry_events,
        service="routes",
        operation="compute_routes",
        provider=provider,
        status="ok",
        context=metric_context,
    )

    return {
        "provider": provider,
        "distance_km": distance_km,
        "duracao_base_min": duration_base_min,
        "duracao_traffic_min": duration_traffic_min,
    }


def _consultar_google_distance_matrix_raw(
    origem_ref: str,
    destino_ref: str,
    *,
    telemetry_events: Optional[list[dict]] = None,
    metric_context: Optional[dict] = None,
) -> Optional[dict]:
    api_key = str(settings.GOOGLE_MAPS_API_KEY or "").strip()
    if not api_key or not origem_ref or not destino_ref:
        return None

    traffic_aware = _google_traffic_aware_enabled()
    provider = "distance_matrix_traffic" if traffic_aware else "distance_matrix_basic"
    params_payload = {
        "origins": origem_ref,
        "destinations": destino_ref,
        "mode": "driving",
        "language": "pt-BR",
        "region": "br",
        "key": api_key,
    }
    if traffic_aware:
        params_payload["departure_time"] = "now"
        params_payload["traffic_model"] = "best_guess"
    params = urlencode(params_payload)
    url = f"{GOOGLE_DISTANCE_MATRIX_URL}?{params}"

    authorize_google_call("distance_matrix_pro" if traffic_aware else "distance_matrix_essentials")
    try:
        data = _http_get_json(url)
    except Exception:
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="distance_matrix",
            provider=provider,
            status="error",
            context=metric_context,
        )
        return None

    status = str(data.get("status") or "").strip().upper()
    if status != "OK":
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="distance_matrix",
            provider=provider,
            status="empty",
            context=metric_context,
        )
        return None

    rows = data.get("rows") or []
    if not isinstance(rows, list) or not rows:
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="distance_matrix",
            provider=provider,
            status="empty",
            context=metric_context,
        )
        return None

    row0 = rows[0] or {}
    elements = row0.get("elements") or []
    if not isinstance(elements, list) or not elements:
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="distance_matrix",
            provider=provider,
            status="empty",
            context=metric_context,
        )
        return None

    element = elements[0] or {}
    elem_status = str(element.get("status") or "").strip().upper()
    if elem_status != "OK":
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="distance_matrix",
            provider=provider,
            status="empty",
            context=metric_context,
        )
        return None

    distance_value = ((element.get("distance") or {}).get("value"))
    duration_value = ((element.get("duration") or {}).get("value"))
    duration_traffic_value = ((element.get("duration_in_traffic") or {}).get("value"))

    try:
        distance_km = max(0.0, float(distance_value) / 1000.0)
    except (TypeError, ValueError):
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="distance_matrix",
            provider=provider,
            status="error",
            context=metric_context,
        )
        return None

    duration_base_min: Optional[int] = None
    duration_traffic_min: Optional[int] = None
    try:
        if duration_value is not None:
            duration_base_min = max(0, int(math.ceil(float(duration_value) / 60.0)))
    except (TypeError, ValueError):
        duration_base_min = None
    try:
        if duration_traffic_value is not None:
            duration_traffic_min = max(0, int(math.ceil(float(duration_traffic_value) / 60.0)))
    except (TypeError, ValueError):
        duration_traffic_min = None

    if duration_base_min is None and duration_traffic_min is None:
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="distance_matrix",
            provider=provider,
            status="empty",
            context=metric_context,
        )
        return None

    _append_google_metric_event(
        telemetry_events,
        service="routes",
        operation="distance_matrix",
        provider=provider,
        status="ok",
        context=metric_context,
    )

    return {
        "provider": provider,
        "distance_km": distance_km,
        "duracao_base_min": duration_base_min,
        "duracao_traffic_min": duration_traffic_min,
    }


def estimar_deslocamento(
    origem: Clinica,
    destino: Clinica,
    *,
    perfil: str = "comercial",
    permitir_google_lookup: bool = True,
    google_cache: Optional[dict] = None,
    telemetry_events: Optional[list[dict]] = None,
) -> tuple[float, int, str]:
    """Estimate travel distance/duration with Google Distance Matrix + fallback heuristics."""
    if not origem or not destino:
        return 0.0, 0, "indefinido"

    if origem.id == destino.id:
        return 0.0, 0, "mesma_clinica"

    # This function creates a new estimate, including key-missing/flag-disabled
    # heuristic fallbacks. Cache-only callers must use a validated persisted row
    # in the lookup functions instead. An in-memory unversioned dict is not proof.
    if cache_only_operation():
        block_cache_only_lookup()

    perfil_norm = normalizar_perfil(perfil)

    origem_waypoint = _waypoint_google_routes(origem)
    destino_waypoint = _waypoint_google_routes(destino)
    origem_ref = _ref_google_maps(origem)
    destino_ref = _ref_google_maps(destino)
    metric_context = _build_google_metric_context(origem, destino, perfil_norm)
    google_result = None
    if permitir_google_lookup and str(settings.GOOGLE_MAPS_API_KEY or "").strip():
        cache = agenda_execution_route_cache(google_cache if isinstance(google_cache, dict) else None)
        origem_cache_ref = (
            json.dumps(origem_waypoint, ensure_ascii=True, sort_keys=True)
            if origem_waypoint is not None
            else str(origem_ref or "")
        )
        destino_cache_ref = (
            json.dumps(destino_waypoint, ensure_ascii=True, sort_keys=True)
            if destino_waypoint is not None
            else str(destino_ref or "")
        )
        cache_key = (origem_cache_ref, destino_cache_ref)
        if cache is not None and cache_key in cache:
            google_result = cache.get(cache_key)
        else:
            if origem_waypoint and destino_waypoint:
                google_result = _consultar_google_routes_api_raw(
                    origem_waypoint,
                    destino_waypoint,
                    telemetry_events=telemetry_events,
                    metric_context=metric_context,
                )
            if google_result is None and origem_ref and destino_ref:
                google_result = _consultar_google_distance_matrix_raw(
                    origem_ref,
                    destino_ref,
                    telemetry_events=telemetry_events,
                    metric_context=metric_context,
                )
            if cache is not None:
                cache[cache_key] = google_result

    if google_result:
        distancia_km = round(max(0.0, float(google_result.get("distance_km") or 0.0)), 2)
        duracao_base = google_result.get("duracao_base_min")
        duracao_traffic = google_result.get("duracao_traffic_min")
        provider = str(google_result.get("provider") or "google").strip().lower()
        provider_prefix = "google_routes_api" if provider.startswith("routes_api") else "google_distance_matrix"
        if perfil_norm == "comercial":
            duracao_escolhida = duracao_traffic if duracao_traffic is not None else duracao_base
            fonte = f"{provider_prefix}_traffic" if duracao_traffic is not None else provider_prefix
        else:
            duracao_escolhida = duracao_base if duracao_base is not None else duracao_traffic
            fonte = provider_prefix

        duracao_min = max(MIN_DURACAO_MINUTOS, int(duracao_escolhida or 0))
        return distancia_km, duracao_min, fonte

    if cache_first_operation():
        # A financial/configuration/provider failure must never be converted
        # into a newly invented travel time in the cache-first Agenda flow.
        raise GoogleMapsCostBlocked("route_unavailable")

    if not permitir_google_lookup and str(settings.GOOGLE_MAPS_API_KEY or "").strip():
        _append_google_metric_event(
            telemetry_events,
            service="routes",
            operation="google_lookup_skipped",
            provider="local_policy",
            status="skipped",
            context=metric_context,
        )

    lat1 = _safe_float(origem.latitude)
    lon1 = _safe_float(origem.longitude)
    lat2 = _safe_float(destino.latitude)
    lon2 = _safe_float(destino.longitude)

    if None not in (lat1, lon1, lat2, lon2):
        distancia_km = _haversine_km(lat1, lon1, lat2, lon2)
        fonte = "heuristica_haversine"
    elif _mesma_cidade(origem, destino):
        distancia_km = DEFAULT_KM_MESMA_CIDADE
        fonte = "heuristica_mesma_cidade"
    else:
        distancia_km = DEFAULT_KM_OUTRA_CIDADE
        fonte = "heuristica_regional"

    velocidade = VELOCIDADE_MEDIA_KMH.get(perfil_norm, VELOCIDADE_MEDIA_KMH["comercial"])
    buffer_min = BUFFER_MINUTOS.get(perfil_norm, BUFFER_MINUTOS["comercial"])
    duracao_base = (distancia_km / max(1.0, velocidade)) * 60.0
    duracao_min = max(MIN_DURACAO_MINUTOS, int(math.ceil(duracao_base + buffer_min)))

    return round(max(0.0, distancia_km), 2), duracao_min, fonte


def upsert_deslocamento(
    db: Session,
    *,
    origem_clinica_id: int,
    destino_clinica_id: int,
    perfil: str,
    distancia_km: float,
    duracao_min: int,
    fonte: str,
    force_override: bool = False,
) -> tuple[ClinicaDeslocamento, bool, bool]:
    """Upsert matrix record.

    Returns: (row, changed, skipped_manual_override).
    """
    perfil_norm = normalizar_perfil(perfil)
    row = (
        db.query(ClinicaDeslocamento)
        .filter(
            ClinicaDeslocamento.origem_clinica_id == origem_clinica_id,
            ClinicaDeslocamento.destino_clinica_id == destino_clinica_id,
            ClinicaDeslocamento.perfil == perfil_norm,
        )
        .first()
    )

    if row and row.manual_override and not force_override:
        return row, False, True

    mudou = False
    distancia_decimal = _to_decimal_2(distancia_km)
    duracao_int = max(0, int(duracao_min or 0))
    fonte_texto = str(fonte or "heuristica").strip() or "heuristica"

    if row is None:
        row = ClinicaDeslocamento(
            origem_clinica_id=origem_clinica_id,
            destino_clinica_id=destino_clinica_id,
            perfil=perfil_norm,
            distancia_km=distancia_decimal,
            duracao_min=duracao_int,
            fonte=fonte_texto,
            manual_override=False,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        return row, True, False

    if row.distancia_km != distancia_decimal:
        row.distancia_km = distancia_decimal
        mudou = True
    if row.duracao_min != duracao_int:
        row.duracao_min = duracao_int
        mudou = True
    if row.fonte != fonte_texto:
        row.fonte = fonte_texto
        mudou = True

    # A successful revalidation renews TTL even if Google's distance/duration
    # did not change. Otherwise a stable expired route is billed on every read.
    if fonte_texto.startswith("google_"):
        mudou = True
    if mudou:
        row.updated_at = datetime.utcnow()

    return row, mudou, False


def materializar_deslocamento_par(
    db: Session,
    *,
    origem: Clinica,
    destino: Clinica,
    perfis: Optional[Iterable[str]] = None,
    force_override: bool = False,
    permitir_google_lookup: bool = True,
    google_cache: Optional[dict] = None,
    telemetry_events: Optional[list[dict]] = None,
    commit: bool = True,
) -> dict[str, ClinicaDeslocamento]:
    """Resolve a route once and persist the requested profiles.

    A shared in-memory Google cache lets multiple profiles reuse the same
    upstream route lookup for the same clinic pair.
    """
    perfis_norm = normalizar_perfis(perfis)
    rows: dict[str, ClinicaDeslocamento] = {}
    cache_lookup = google_cache if isinstance(google_cache, dict) else {}
    eventos_google = telemetry_events if isinstance(telemetry_events, list) else []

    for perfil in perfis_norm:
        distancia_km, duracao_min, fonte = estimar_deslocamento(
            origem,
            destino,
            perfil=perfil,
            permitir_google_lookup=permitir_google_lookup,
            google_cache=cache_lookup,
            telemetry_events=eventos_google,
        )
        row, _changed, _skipped = upsert_deslocamento(
            db,
            origem_clinica_id=int(origem.id),
            destino_clinica_id=int(destino.id),
            perfil=perfil,
            distancia_km=distancia_km,
            duracao_min=duracao_min,
            fonte=fonte,
            force_override=force_override,
        )
        rows[perfil] = row

    registrar_google_maps_metricas(db, eventos_google)
    if commit:
        db.commit()
    else:
        # Validation may already have pending appointment changes. Make cache
        # rows visible in this transaction without accepting the business write.
        db.flush()
    return rows


def recalcular_matriz_para_clinica(
    db: Session,
    clinica_id: int,
    *,
    perfis: Optional[Iterable[str]] = None,
    force_override: bool = False,
    incluir_inativas: bool = False,
) -> dict:
    perfis_norm = normalizar_perfis(perfis)

    query_clinicas = db.query(Clinica)
    if not incluir_inativas:
        query_clinicas = query_clinicas.filter(Clinica.ativo == True)
    clinicas = query_clinicas.order_by(Clinica.id.asc()).all()
    mapa = {int(c.id): c for c in clinicas if c and c.id is not None}

    origem_principal = mapa.get(int(clinica_id))
    if origem_principal is None:
        return {"ok": False, "updated": 0, "skipped_manual": 0, "profiles": perfis_norm}

    updated = 0
    skipped_manual = 0
    google_cache: dict = {}
    telemetry_events: list[dict] = []
    rows_existentes = (
        db.query(ClinicaDeslocamento)
        .filter(
            ClinicaDeslocamento.perfil.in_(perfis_norm),
            ClinicaDeslocamento.origem_clinica_id.in_(list(mapa.keys())),
            ClinicaDeslocamento.destino_clinica_id.in_(list(mapa.keys())),
        )
        .all()
    )
    rows_map = {
        (int(row.origem_clinica_id), int(row.destino_clinica_id), str(row.perfil or "")): row
        for row in rows_existentes
    }

    for destino in clinicas:
        pares = [(origem_principal, destino)]
        if destino.id != origem_principal.id:
            pares.append((destino, origem_principal))

        for origem, destino_real in pares:
            for perfil in perfis_norm:
                row_existente = rows_map.get((int(origem.id), int(destino_real.id), perfil))
                if (
                    not force_override
                    and _deslocamento_esta_atual(
                        row_existente,
                        origem=origem,
                        destino=destino_real,
                    )
                ):
                    continue
                distancia_km, duracao_min, fonte = estimar_deslocamento(
                    origem,
                    destino_real,
                    perfil=perfil,
                    google_cache=google_cache,
                    telemetry_events=telemetry_events,
                )
                _row, changed, skipped = upsert_deslocamento(
                    db,
                    origem_clinica_id=int(origem.id),
                    destino_clinica_id=int(destino_real.id),
                    perfil=perfil,
                    distancia_km=distancia_km,
                    duracao_min=duracao_min,
                    fonte=fonte,
                    force_override=force_override,
                )
                if changed:
                    updated += 1
                    rows_map[(int(origem.id), int(destino_real.id), perfil)] = _row
                if skipped:
                    skipped_manual += 1

    registrar_google_maps_metricas(db, telemetry_events)
    db.commit()
    return {
        "ok": True,
        "updated": updated,
        "skipped_manual": skipped_manual,
        "profiles": perfis_norm,
    }


def recalcular_matriz_completa(
    db: Session,
    *,
    perfis: Optional[Iterable[str]] = None,
    force_override: bool = False,
    incluir_inativas: bool = False,
) -> dict:
    perfis_norm = normalizar_perfis(perfis)
    query_clinicas = db.query(Clinica)
    if not incluir_inativas:
        query_clinicas = query_clinicas.filter(Clinica.ativo == True)
    clinicas = query_clinicas.order_by(Clinica.id.asc()).all()

    updated = 0
    skipped_manual = 0
    google_cache: dict = {}
    telemetry_events: list[dict] = []
    clinica_ids = [int(clinica.id) for clinica in clinicas if clinica.id is not None]
    rows_existentes = []
    if clinica_ids:
        rows_existentes = (
            db.query(ClinicaDeslocamento)
            .filter(
                ClinicaDeslocamento.perfil.in_(perfis_norm),
                ClinicaDeslocamento.origem_clinica_id.in_(clinica_ids),
                ClinicaDeslocamento.destino_clinica_id.in_(clinica_ids),
            )
            .all()
        )
    rows_map = {
        (int(row.origem_clinica_id), int(row.destino_clinica_id), str(row.perfil or "")): row
        for row in rows_existentes
    }

    for origem in clinicas:
        for destino in clinicas:
            for perfil in perfis_norm:
                row_existente = rows_map.get((int(origem.id), int(destino.id), perfil))
                if (
                    not force_override
                    and _deslocamento_esta_atual(
                        row_existente,
                        origem=origem,
                        destino=destino,
                    )
                ):
                    continue
                distancia_km, duracao_min, fonte = estimar_deslocamento(
                    origem,
                    destino,
                    perfil=perfil,
                    google_cache=google_cache,
                    telemetry_events=telemetry_events,
                )
                _row, changed, skipped = upsert_deslocamento(
                    db,
                    origem_clinica_id=int(origem.id),
                    destino_clinica_id=int(destino.id),
                    perfil=perfil,
                    distancia_km=distancia_km,
                    duracao_min=duracao_min,
                    fonte=fonte,
                    force_override=force_override,
                )
                if changed:
                    updated += 1
                    rows_map[(int(origem.id), int(destino.id), perfil)] = _row
                if skipped:
                    skipped_manual += 1

    registrar_google_maps_metricas(db, telemetry_events)
    db.commit()
    total_celulas = len(clinicas) * len(clinicas) * len(perfis_norm)
    return {
        "ok": True,
        "updated": updated,
        "skipped_manual": skipped_manual,
        "profiles": perfis_norm,
        "total_celulas": total_celulas,
    }


def obter_ou_criar_deslocamento(
    db: Session,
    *,
    origem_clinica_id: int,
    destino_clinica_id: int,
    perfil: str = "comercial",
    force_recalculate: bool = False,
) -> Optional[ClinicaDeslocamento]:
    perfil_norm = normalizar_perfil(perfil)
    origem = db.query(Clinica).filter(Clinica.id == origem_clinica_id).first()
    destino = db.query(Clinica).filter(Clinica.id == destino_clinica_id).first()
    if not origem or not destino:
        return None

    row = (
        db.query(ClinicaDeslocamento)
        .filter(
            ClinicaDeslocamento.origem_clinica_id == origem_clinica_id,
            ClinicaDeslocamento.destino_clinica_id == destino_clinica_id,
            ClinicaDeslocamento.perfil == perfil_norm,
        )
        .first()
    )

    # Regra operacional: ajuste manual sempre prevalece.
    # Mesmo com force_recalculate=True (ex.: "recalcular par"), nao sobrescreve manual_override.
    if cache_only_operation():
        if _cache_only_route_available(row, origem=origem, destino=destino) and (not force_recalculate or bool(row.manual_override)):
            return row
        block_cache_only_lookup()
    if row:
        if bool(row.manual_override):
            return row
        if not force_recalculate and (
            _cache_only_route_available(row, origem=origem, destino=destino)
            if cache_first_operation() else _deslocamento_esta_atual(row, origem=origem, destino=destino)
        ):
            return row

    rows = materializar_deslocamento_par(
        db,
        origem=origem,
        destino=destino,
        perfis=[perfil_norm],
        force_override=force_recalculate,
    )
    return rows.get(perfil_norm)


def obter_duracao_deslocamento(
    db: Session,
    *,
    origem_clinica_id: Optional[int],
    destino_clinica_id: Optional[int],
    perfil: str = "comercial",
    permitir_estimativa_fallback: bool = True,
    commit_cache: bool = True,
) -> tuple[int, str]:
    """Returns travel duration for a clinic pair and persists cache misses."""
    origem_id = int(origem_clinica_id or 0)
    destino_id = int(destino_clinica_id or 0)
    if origem_id <= 0 or destino_id <= 0:
        return 0, "clinica_indefinida"
    if origem_id == destino_id:
        return 0, "mesma_clinica"

    perfil_norm = normalizar_perfil(perfil)
    row = (
        db.query(ClinicaDeslocamento)
        .filter(
            ClinicaDeslocamento.origem_clinica_id == origem_id,
            ClinicaDeslocamento.destino_clinica_id == destino_id,
            ClinicaDeslocamento.perfil == perfil_norm,
        )
        .first()
    )
    origem = db.query(Clinica).filter(Clinica.id == origem_id).first()
    destino = db.query(Clinica).filter(Clinica.id == destino_id).first()
    if not origem or not destino:
        return 0, "clinica_nao_encontrada"
    if cache_only_operation():
        if _cache_only_route_available(row, origem=origem, destino=destino):
            return max(0, int(row.duracao_min)), str(row.fonte)
        block_cache_only_lookup()
    if row and row.duracao_min is not None and (
        _cache_only_route_available(row, origem=origem, destino=destino)
        if cache_first_operation() else _deslocamento_esta_atual(row, origem=origem, destino=destino)
    ):
        return max(0, int(row.duracao_min)), str(row.fonte or "matriz")

    if not permitir_estimativa_fallback:
        return 0, "sem_matriz"

    # On the first miss, populate both operational profiles while the shared
    # Google cache is warm. This keeps accuracy from Google Maps without paying
    # for the same pair again on the next lookup.
    rows = materializar_deslocamento_par(
        db,
        origem=origem,
        destino=destino,
        perfis=["comercial", "plantao"],
        permitir_google_lookup=_allow_live_google_lookups_on_read(),
        commit=commit_cache,
    )
    row = rows.get(perfil_norm)
    if row and row.duracao_min is not None:
        return max(0, int(row.duracao_min)), str(row.fonte or "matriz")
    return 0, "sem_matriz"


def obter_duracao_deslocamento_entidades(
    db: Session,
    *,
    origem: Clinica,
    destino: Clinica,
    perfil: str = "comercial",
    permitir_estimativa_fallback: bool = True,
    permitir_google_lookup_on_refresh: Optional[bool] = None,
    google_cache: Optional[dict] = None,
    telemetry_events: Optional[list[dict]] = None,
    commit_cache: bool = True,
) -> tuple[int, str]:
    """Retorna duracao para quaisquer entidades operacionais persistidas na matriz.

    Clinicas seguem usando IDs positivos. Entidades nao-clinica podem usar IDs
    sinteticos (por exemplo, tutor como inteiro negativo) sem alterar o
    contrato da tabela `clinica_deslocamentos`.
    """

    origem_id = _entity_lookup_id(origem)
    destino_id = _entity_lookup_id(destino)
    if origem_id == 0 or destino_id == 0:
        return 0, "clinica_indefinida"
    if origem_id == destino_id:
        return 0, "mesma_clinica"

    perfil_norm = normalizar_perfil(perfil)
    row = (
        db.query(ClinicaDeslocamento)
        .filter(
            ClinicaDeslocamento.origem_clinica_id == origem_id,
            ClinicaDeslocamento.destino_clinica_id == destino_id,
            ClinicaDeslocamento.perfil == perfil_norm,
        )
        .first()
    )
    if cache_only_operation():
        if _cache_only_route_available(row, origem=origem, destino=destino):
            return max(0, int(row.duracao_min)), str(row.fonte)
        block_cache_only_lookup()
    if row and row.duracao_min is not None and (
        _cache_only_route_available(row, origem=origem, destino=destino)
        if cache_first_operation() else _deslocamento_esta_atual(row, origem=origem, destino=destino)
    ):
        return max(0, int(row.duracao_min)), str(row.fonte or "matriz")

    if not permitir_estimativa_fallback:
        return 0, "sem_matriz"

    permitir_google_lookup = (
        _allow_live_google_lookups_on_read()
        if permitir_google_lookup_on_refresh is None
        else bool(permitir_google_lookup_on_refresh)
    )
    rows = materializar_deslocamento_par(
        db,
        origem=origem,
        destino=destino,
        perfis=["comercial", "plantao"],
        permitir_google_lookup=permitir_google_lookup,
        google_cache=google_cache,
        telemetry_events=telemetry_events,
        commit=commit_cache,
    )
    row = rows.get(perfil_norm)
    if row and row.duracao_min is not None:
        return max(0, int(row.duracao_min)), str(row.fonte or "matriz")
    return 0, "sem_matriz"


def resumir_cobertura_matriz_deslocamentos(
    db: Session,
    *,
    incluir_inativas: bool = False,
) -> dict:
    """Read-only snapshot: persisted matrix rows (Google vs heuristics) vs clinic geolocation.

    Rows are counted only when both endpoints belong to the clinic scope (same rule as /matriz).
    """
    query_clinicas = db.query(Clinica)
    if not incluir_inativas:
        query_clinicas = query_clinicas.filter(Clinica.ativo == True)
    clinicas = query_clinicas.order_by(Clinica.id.asc()).all()
    clinica_ids = [int(c.id) for c in clinicas if c.id is not None]
    n = len(clinica_ids)
    perfis_operacionais = len(normalizar_perfis(None))
    celulas_teoricas = n * n * perfis_operacionais if n else 0

    tem_place_id = 0
    tem_latlng = 0
    sem_endereco_texto = 0
    for c in clinicas:
        if str(getattr(c, "place_id", "") or "").strip():
            tem_place_id += 1
        lat = _safe_float(getattr(c, "latitude", None))
        lng = _safe_float(getattr(c, "longitude", None))
        if lat is not None and lng is not None:
            tem_latlng += 1
        if not _endereco_texto_clinica(c):
            sem_endereco_texto += 1

    if not clinica_ids:
        return {
            "escopo": {
                "incluir_inativas": bool(incluir_inativas),
                "total_clinicas": 0,
                "clinica_ids": [],
            },
            "clinicas_localizacao": {
                "com_place_id": 0,
                "com_latitude_longitude": 0,
                "sem_endereco_texto_minimo": 0,
            },
            "matriz": {
                "perfis_operacionais": perfis_operacionais,
                "celulas_teoricas": 0,
                "linhas_no_escopo": 0,
                "celulas_sem_linha_estimadas": 0,
                "por_bucket": {},
                "por_fonte_top": [],
                "amostra_heuristica": [],
            },
            "contexto": {
                "google_maps_api_key_configurada": bool(str(settings.GOOGLE_MAPS_API_KEY or "").strip()),
                "cache_max_age_days": _cache_max_age_days(),
                "cache_expires_by_age": _cache_expires_by_age(),
                "force_refresh_heuristica_com_api_key": _force_refresh_heuristica_com_api_key(),
                "allow_live_google_lookups_on_read": _allow_live_google_lookups_on_read(),
                "google_traffic_aware_enabled": _google_traffic_aware_enabled(),
            },
        }

    fonte_lower = func.lower(func.coalesce(ClinicaDeslocamento.fonte, ""))
    bucket_expr = case(
        (ClinicaDeslocamento.manual_override == True, "manual_ou_override"),
        (fonte_lower == "manual", "manual_ou_override"),
        (fonte_lower.like("google%"), "google_api"),
        (fonte_lower.like("heuristica%"), "heuristica_local"),
        else_="outros",
    )

    escopo_rows = (
        db.query(bucket_expr.label("bucket"), func.count(ClinicaDeslocamento.id))
        .filter(
            ClinicaDeslocamento.origem_clinica_id.in_(clinica_ids),
            ClinicaDeslocamento.destino_clinica_id.in_(clinica_ids),
        )
        .group_by(bucket_expr)
        .all()
    )
    por_bucket: dict[str, int] = {str(row[0]): int(row[1]) for row in escopo_rows}

    fonte_rows = (
        db.query(
            ClinicaDeslocamento.fonte,
            ClinicaDeslocamento.perfil,
            func.count(ClinicaDeslocamento.id),
        )
        .filter(
            ClinicaDeslocamento.origem_clinica_id.in_(clinica_ids),
            ClinicaDeslocamento.destino_clinica_id.in_(clinica_ids),
        )
        .group_by(ClinicaDeslocamento.fonte, ClinicaDeslocamento.perfil)
        .order_by(func.count(ClinicaDeslocamento.id).desc())
        .limit(40)
        .all()
    )
    por_fonte_top = [
        {"fonte": r[0], "perfil": str(r[1] or ""), "linhas": int(r[2])}
        for r in fonte_rows
    ]

    linhas_no_escopo = sum(por_bucket.values())
    celulas_sem_linha = max(0, celulas_teoricas - linhas_no_escopo)

    amostra = (
        db.query(
            ClinicaDeslocamento.origem_clinica_id,
            ClinicaDeslocamento.destino_clinica_id,
            ClinicaDeslocamento.perfil,
            ClinicaDeslocamento.fonte,
        )
        .filter(
            ClinicaDeslocamento.origem_clinica_id.in_(clinica_ids),
            ClinicaDeslocamento.destino_clinica_id.in_(clinica_ids),
            fonte_lower.like("heuristica%"),
            ClinicaDeslocamento.manual_override == False,
        )
        .order_by(
            ClinicaDeslocamento.origem_clinica_id,
            ClinicaDeslocamento.destino_clinica_id,
            ClinicaDeslocamento.perfil,
        )
        .limit(40)
        .all()
    )
    amostra_heuristica = [
        {
            "origem_clinica_id": int(r[0]),
            "destino_clinica_id": int(r[1]),
            "perfil": str(r[2] or ""),
            "fonte": str(r[3] or ""),
        }
        for r in amostra
    ]

    linhas_fora_escopo: Optional[int] = None
    if not incluir_inativas:
        linhas_fora_escopo = int(
            db.query(func.count(ClinicaDeslocamento.id))
            .filter(
                or_(
                    ClinicaDeslocamento.origem_clinica_id.notin_(clinica_ids),
                    ClinicaDeslocamento.destino_clinica_id.notin_(clinica_ids),
                )
            )
            .scalar()
            or 0
        )

    return {
        "escopo": {
            "incluir_inativas": bool(incluir_inativas),
            "total_clinicas": n,
            "clinica_ids": clinica_ids,
        },
        "clinicas_localizacao": {
            "com_place_id": tem_place_id,
            "com_latitude_longitude": tem_latlng,
            "sem_endereco_texto_minimo": sem_endereco_texto,
        },
        "matriz": {
            "perfis_operacionais": perfis_operacionais,
            "celulas_teoricas": celulas_teoricas,
            "linhas_no_escopo": linhas_no_escopo,
            "celulas_sem_linha_estimadas": celulas_sem_linha,
            "por_bucket": por_bucket,
            "por_fonte_top": por_fonte_top,
            "amostra_heuristica": amostra_heuristica,
        },
        "contexto": {
            "google_maps_api_key_configurada": bool(str(settings.GOOGLE_MAPS_API_KEY or "").strip()),
            "cache_max_age_days": _cache_max_age_days(),
            "cache_expires_by_age": _cache_expires_by_age(),
            "force_refresh_heuristica_com_api_key": _force_refresh_heuristica_com_api_key(),
            "allow_live_google_lookups_on_read": _allow_live_google_lookups_on_read(),
            "google_traffic_aware_enabled": _google_traffic_aware_enabled(),
            "linhas_fora_escopo_clinicas_ativas": linhas_fora_escopo,
        },
    }


def resumir_google_maps_metricas(
    db: Session,
    *,
    dias: int = DEFAULT_METRICAS_WINDOW_DIAS,
    incluir_inativas: bool = False,
) -> dict:
    dias_norm = max(1, min(365, int(dias or DEFAULT_METRICAS_WINDOW_DIAS)))
    inicio_janela = _utc_now_naive() - timedelta(days=dias_norm)

    metricas = (
        db.query(GoogleMapsUsageMetrica)
        .filter(GoogleMapsUsageMetrica.created_at >= inicio_janela)
        .order_by(GoogleMapsUsageMetrica.created_at.asc())
        .all()
    )

    por_dia: dict[str, int] = defaultdict(int)
    por_operacao: dict[str, int] = defaultdict(int)
    por_status: dict[str, int] = defaultdict(int)
    top_pares: dict[tuple[int | None, int | None], dict] = {}

    total_ok = 0
    for item in metricas:
        created_at = _normalize_datetime(getattr(item, "created_at", None)) or _utc_now_naive()
        dia = created_at.date().isoformat()
        por_dia[dia] += 1
        operacao = str(getattr(item, "operation", "") or "unknown").strip() or "unknown"
        status = str(getattr(item, "status", "") or "unknown").strip().lower() or "unknown"
        por_operacao[operacao] += 1
        por_status[status] += 1
        if status == "ok":
            total_ok += 1

        pair_key = (
            getattr(item, "origem_clinica_id", None),
            getattr(item, "destino_clinica_id", None),
        )
        pair_bucket = top_pares.setdefault(
            pair_key,
            {
                "origem_clinica_id": pair_key[0],
                "destino_clinica_id": pair_key[1],
                "calls": 0,
                "last_called_at": None,
            },
        )
        pair_bucket["calls"] += 1
        pair_bucket["last_called_at"] = created_at.isoformat(sep=" ")

    query_clinicas = db.query(
        Clinica.id,
        Clinica.ativo,
        Clinica.endereco,
        Clinica.numero,
        Clinica.bairro,
        Clinica.cidade,
        Clinica.estado,
        Clinica.cep,
        Clinica.place_id,
        Clinica.latitude,
        Clinica.longitude,
        Clinica.geocode_at,
    )
    if not incluir_inativas:
        query_clinicas = query_clinicas.filter(Clinica.ativo == True)
    clinicas = query_clinicas.all()
    clinicas_map = {
        int(item.id): SimpleNamespace(
            id=item.id,
            endereco=item.endereco,
            numero=item.numero,
            bairro=item.bairro,
            cidade=item.cidade,
            estado=item.estado,
            cep=item.cep,
            place_id=item.place_id,
            latitude=item.latitude,
            longitude=item.longitude,
            geocode_at=item.geocode_at,
        )
        for item in clinicas
        if item and item.id is not None
    }
    clinica_ids = list(clinicas_map.keys())

    cache_stats = {
        "total_rows": 0,
        "fresh_rows": 0,
        "stale_rows": 0,
        "manual_rows": 0,
        "google_rows": 0,
    }
    if clinica_ids:
        rows = (
            db.query(ClinicaDeslocamento)
            .filter(
                ClinicaDeslocamento.origem_clinica_id.in_(clinica_ids),
                ClinicaDeslocamento.destino_clinica_id.in_(clinica_ids),
            )
            .all()
        )
        cache_stats["total_rows"] = len(rows)
        for row in rows:
            origem = clinicas_map.get(int(row.origem_clinica_id or 0))
            destino = clinicas_map.get(int(row.destino_clinica_id or 0))
            if not origem or not destino:
                continue
            if bool(getattr(row, "manual_override", False)):
                cache_stats["manual_rows"] += 1
            fonte = str(getattr(row, "fonte", "") or "").strip().lower()
            if fonte.startswith("google_"):
                cache_stats["google_rows"] += 1
            if _deslocamento_esta_atual(row, origem=origem, destino=destino):
                cache_stats["fresh_rows"] += 1
            else:
                cache_stats["stale_rows"] += 1

    success_rate = round((total_ok / len(metricas)) * 100.0, 2) if metricas else 0.0
    top_pairs_sorted = sorted(
        top_pares.values(),
        key=lambda item: (-int(item["calls"]), str(item["last_called_at"] or "")),
    )[:10]
    custo_e_quotas = _resumir_custo_google_maps(metricas, dias_norm)

    return {
        "window_days": dias_norm,
        "cache_max_age_days": _cache_max_age_days(),
        "cache_expires_by_age": _cache_expires_by_age(),
        "metrics_retention_days": _metrics_retention_days(),
        "allow_live_google_lookups_on_read": _allow_live_google_lookups_on_read(),
        "google_traffic_aware_enabled": _google_traffic_aware_enabled(),
        "total_api_calls": len(metricas),
        "success_rate_percent": success_rate,
        "status_counts": dict(sorted(por_status.items())),
        "operation_counts": dict(sorted(por_operacao.items())),
        "calls_by_day": dict(sorted(por_dia.items())),
        "top_pairs": top_pairs_sorted,
        "cache": cache_stats,
        "cost_and_quotas": custo_e_quotas,
    }


def serialize_deslocamento(row: ClinicaDeslocamento) -> dict:
    return {
        "id": row.id,
        "origem_clinica_id": row.origem_clinica_id,
        "destino_clinica_id": row.destino_clinica_id,
        "perfil": row.perfil,
        "distancia_km": float(row.distancia_km or 0),
        "duracao_min": int(row.duracao_min or 0),
        "fonte": row.fonte,
        "manual_override": bool(row.manual_override),
        "observacoes": row.observacoes,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }
