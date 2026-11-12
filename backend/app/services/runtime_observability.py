from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import deque
from contextvars import ContextVar, Token
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_5XX_WINDOW_MINUTES = 5
_DEFAULT_5XX_THRESHOLD = 20
_MIN_5XX_WINDOW_MINUTES = 1
_MAX_5XX_WINDOW_MINUTES = 60
_MIN_5XX_THRESHOLD = 1
_MAX_5XX_THRESHOLD = 500
_DEFAULT_LATENCY_WINDOW_MINUTES = 30
_MIN_LATENCY_WINDOW_MINUTES = 1
_MAX_LATENCY_WINDOW_MINUTES = 1440
_DEFAULT_LATENCY_MAX_SAMPLES = 2000
_MIN_LATENCY_MAX_SAMPLES = 100
_MAX_LATENCY_MAX_SAMPLES = 20000
_SLOW_REQUEST_THRESHOLD_MS = 1200.0
_DEFAULT_PERSISTENCE_RETENTION_DAYS = 14
_MIN_PERSISTENCE_RETENTION_DAYS = 1
_MAX_PERSISTENCE_RETENTION_DAYS = 90
_DEFAULT_PERSISTENCE_CLEANUP_INTERVAL_SECONDS = 21600
_MIN_PERSISTENCE_CLEANUP_INTERVAL_SECONDS = 60
_MAX_PERSISTENCE_CLEANUP_INTERVAL_SECONDS = 86400
_DEFAULT_PERSISTENCE_QUERY_MAX_SAMPLES = 20000
_MIN_PERSISTENCE_QUERY_MAX_SAMPLES = 100
_MAX_PERSISTENCE_QUERY_MAX_SAMPLES = 100000
_DEFAULT_LATENCY_ENDPOINTS = [
    "/api/v1/agenda",
    "/api/v1/atendimentos",
    "/api/v1/relatorios",
    "/api/v1/fiscal",
    "/api/v1/logistica",
]
_MAX_LATENCY_PREFIX_ENDPOINTS = 5
_MAX_LATENCY_EXACT_ENDPOINTS = 10

_HTTP_5XX_EVENTS: Deque[Tuple[float, datetime]] = deque()
_HTTP_5XX_LOCK = threading.Lock()
_HTTP_LATENCY_EVENTS: Dict[
    str,
    Deque[Tuple[float, float, int, float, float, int, float, datetime]],
] = {}
_HTTP_LATENCY_LOCK = threading.Lock()
_REQUEST_LATENCY_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "fortcordis_request_latency_context",
    default=None,
)
_PERSISTENCE_CLEANUP_LOCK = threading.Lock()
_LAST_PERSISTENCE_CLEANUP_MONOTONIC: Optional[float] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_int_setting(
    raw_value: Any,
    *,
    name: str,
    default: int,
    min_value: int,
    max_value: int,
) -> Tuple[int, Optional[str]]:
    try:
        parsed = int(raw_value)
    except Exception:
        return default, f"{name} invalido. Usando valor padrao {default}."

    if parsed < min_value or parsed > max_value:
        return default, (
            f"{name} fora da faixa [{min_value}, {max_value}]. "
            f"Usando valor padrao {default}."
        )
    return parsed, None


def _parse_endpoint_prefixes(raw_value: Any) -> List[str]:
    if raw_value is None:
        values: List[str] = []
    elif isinstance(raw_value, (list, tuple)):
        values = [str(item).strip() for item in raw_value]
    else:
        values = [item.strip() for item in str(raw_value).split(",")]

    normalized: List[str] = []
    for value in values:
        if not value:
            continue
        if not value.startswith("/"):
            value = f"/{value}"
        if value.endswith("/") and value != "/":
            value = value[:-1]
        normalized.append(value)

    dedup: List[str] = []
    seen = set()
    for item in normalized:
        if item in seen:
            continue
        seen.add(item)
        dedup.append(item)
    return dedup


def get_http_5xx_monitor_config() -> Dict[str, Any]:
    window_minutes, window_warning = _parse_int_setting(
        settings.RUNTIME_HTTP_5XX_ALERT_WINDOW_MINUTES,
        name="RUNTIME_HTTP_5XX_ALERT_WINDOW_MINUTES",
        default=_DEFAULT_5XX_WINDOW_MINUTES,
        min_value=_MIN_5XX_WINDOW_MINUTES,
        max_value=_MAX_5XX_WINDOW_MINUTES,
    )
    threshold, threshold_warning = _parse_int_setting(
        settings.RUNTIME_HTTP_5XX_ALERT_THRESHOLD,
        name="RUNTIME_HTTP_5XX_ALERT_THRESHOLD",
        default=_DEFAULT_5XX_THRESHOLD,
        min_value=_MIN_5XX_THRESHOLD,
        max_value=_MAX_5XX_THRESHOLD,
    )
    warnings = [warning for warning in (window_warning, threshold_warning) if warning]
    return {
        "window_minutes": window_minutes,
        "threshold": threshold,
        "warnings": warnings,
    }


def get_http_latency_monitor_config() -> Dict[str, Any]:
    window_minutes, window_warning = _parse_int_setting(
        settings.RUNTIME_HTTP_LATENCY_WINDOW_MINUTES,
        name="RUNTIME_HTTP_LATENCY_WINDOW_MINUTES",
        default=_DEFAULT_LATENCY_WINDOW_MINUTES,
        min_value=_MIN_LATENCY_WINDOW_MINUTES,
        max_value=_MAX_LATENCY_WINDOW_MINUTES,
    )
    max_samples, samples_warning = _parse_int_setting(
        settings.RUNTIME_HTTP_LATENCY_MAX_SAMPLES_PER_ENDPOINT,
        name="RUNTIME_HTTP_LATENCY_MAX_SAMPLES_PER_ENDPOINT",
        default=_DEFAULT_LATENCY_MAX_SAMPLES,
        min_value=_MIN_LATENCY_MAX_SAMPLES,
        max_value=_MAX_LATENCY_MAX_SAMPLES,
    )
    configured_prefixes = _parse_endpoint_prefixes(
        settings.RUNTIME_HTTP_LATENCY_PRIORITY_ENDPOINTS
    )
    endpoint_warnings: List[str] = []
    if not configured_prefixes:
        configured_prefixes = list(_DEFAULT_LATENCY_ENDPOINTS)
        endpoint_warnings.append(
            "RUNTIME_HTTP_LATENCY_PRIORITY_ENDPOINTS vazio/invalido. "
            "Usando endpoints padrao."
        )
    configured_exact_endpoints = _parse_endpoint_prefixes(
        settings.RUNTIME_HTTP_LATENCY_EXACT_ENDPOINTS
    )
    if len(configured_exact_endpoints) > _MAX_LATENCY_EXACT_ENDPOINTS:
        endpoint_warnings.append(
            "RUNTIME_HTTP_LATENCY_EXACT_ENDPOINTS excede o limite de "
            f"{_MAX_LATENCY_EXACT_ENDPOINTS}; os itens excedentes foram ignorados."
        )
    exact_endpoints = configured_exact_endpoints[:_MAX_LATENCY_EXACT_ENDPOINTS]

    exact_endpoint_set = set(exact_endpoints)
    overlapping_endpoints = [
        endpoint for endpoint in configured_prefixes if endpoint in exact_endpoint_set
    ]
    if overlapping_endpoints:
        endpoint_warnings.append(
            "Endpoint presente nas configuracoes de prefixo e rota exata; "
            "a classificacao exata GET prevalece e o prefixo duplicado foi ignorado."
        )
        configured_prefixes = [
            endpoint for endpoint in configured_prefixes if endpoint not in exact_endpoint_set
        ]

    if len(configured_prefixes) > _MAX_LATENCY_PREFIX_ENDPOINTS:
        endpoint_warnings.append(
            "RUNTIME_HTTP_LATENCY_PRIORITY_ENDPOINTS excede o limite de "
            f"{_MAX_LATENCY_PREFIX_ENDPOINTS}; os itens excedentes foram ignorados."
        )
    prefixes = configured_prefixes[:_MAX_LATENCY_PREFIX_ENDPOINTS]

    endpoints: List[str] = []
    for endpoint in prefixes + exact_endpoints:
        if endpoint not in endpoints:
            endpoints.append(endpoint)

    warnings = [
        warning for warning in (window_warning, samples_warning) if warning
    ]
    warnings.extend(endpoint_warnings)
    return {
        "window_minutes": window_minutes,
        "max_samples_per_endpoint": max_samples,
        "priority_endpoints": endpoints,
        "priority_endpoint_prefixes": prefixes,
        "exact_endpoints": exact_endpoints,
        "warnings": warnings,
    }


def _safe_release_id(raw_value: Any) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]", "", str(raw_value or "").strip())
    return normalized[:80] or "unknown"


def get_http_latency_persistence_config() -> Dict[str, Any]:
    retention_days, retention_warning = _parse_int_setting(
        settings.RUNTIME_HTTP_LATENCY_RETENTION_DAYS,
        name="RUNTIME_HTTP_LATENCY_RETENTION_DAYS",
        default=_DEFAULT_PERSISTENCE_RETENTION_DAYS,
        min_value=_MIN_PERSISTENCE_RETENTION_DAYS,
        max_value=_MAX_PERSISTENCE_RETENTION_DAYS,
    )
    cleanup_interval_seconds, cleanup_warning = _parse_int_setting(
        settings.RUNTIME_HTTP_LATENCY_CLEANUP_INTERVAL_SECONDS,
        name="RUNTIME_HTTP_LATENCY_CLEANUP_INTERVAL_SECONDS",
        default=_DEFAULT_PERSISTENCE_CLEANUP_INTERVAL_SECONDS,
        min_value=_MIN_PERSISTENCE_CLEANUP_INTERVAL_SECONDS,
        max_value=_MAX_PERSISTENCE_CLEANUP_INTERVAL_SECONDS,
    )
    query_max_samples, query_limit_warning = _parse_int_setting(
        settings.RUNTIME_HTTP_LATENCY_QUERY_MAX_SAMPLES,
        name="RUNTIME_HTTP_LATENCY_QUERY_MAX_SAMPLES",
        default=_DEFAULT_PERSISTENCE_QUERY_MAX_SAMPLES,
        min_value=_MIN_PERSISTENCE_QUERY_MAX_SAMPLES,
        max_value=_MAX_PERSISTENCE_QUERY_MAX_SAMPLES,
    )
    warnings = [
        warning
        for warning in (retention_warning, cleanup_warning, query_limit_warning)
        if warning
    ]
    return {
        "enabled": bool(settings.RUNTIME_HTTP_LATENCY_PERSIST_ENABLED),
        "retention_days": retention_days,
        "cleanup_interval_seconds": cleanup_interval_seconds,
        "query_max_samples": query_max_samples,
        "release_id": _safe_release_id(settings.RUNTIME_HTTP_LATENCY_RELEASE_ID),
        "warnings": warnings,
    }


def begin_http_request_observation(
    path: str,
    *,
    method: Optional[str] = None,
) -> Optional[Token]:
    """Abre contexto somente para uma rota monitorada, sem guardar a URL."""

    config = get_http_latency_monitor_config()
    endpoint = _resolve_monitored_endpoint(
        path,
        list(config["priority_endpoint_prefixes"]),
        exact_endpoints=list(config["exact_endpoints"]),
        method=method,
    )
    if endpoint is None:
        return None
    return _REQUEST_LATENCY_CONTEXT.set(
        {
            "endpoint": endpoint,
            "database_ms": 0.0,
            "database_query_count": 0,
            "pool_wait_ms": 0.0,
        }
    )


def end_http_request_observation(token: Optional[Token]) -> None:
    if token is not None:
        _REQUEST_LATENCY_CONTEXT.reset(token)


def _record_request_component(component: str, elapsed_ms: float) -> None:
    context = _REQUEST_LATENCY_CONTEXT.get()
    if context is None:
        return
    try:
        elapsed = max(0.0, float(elapsed_ms))
    except (TypeError, ValueError):
        return
    context[component] = float(context.get(component, 0.0)) + elapsed


def record_database_query_duration(elapsed_ms: float) -> None:
    context = _REQUEST_LATENCY_CONTEXT.get()
    if context is None:
        return
    try:
        elapsed = max(0.0, float(elapsed_ms))
    except (TypeError, ValueError):
        return
    context["database_ms"] = float(context.get("database_ms", 0.0)) + elapsed
    context["database_query_count"] = int(context.get("database_query_count", 0)) + 1


def record_database_pool_wait(elapsed_ms: float) -> None:
    _record_request_component("pool_wait_ms", elapsed_ms)


def _purge_old_events_locked(*, now_monotonic: float, window_seconds: int) -> None:
    cutoff = now_monotonic - window_seconds
    while _HTTP_5XX_EVENTS and _HTTP_5XX_EVENTS[0][0] < cutoff:
        _HTTP_5XX_EVENTS.popleft()


def _purge_old_latency_events_locked(
    events: Deque[Tuple[float, float, int, float, float, int, float, datetime]],
    *,
    now_monotonic: float,
    window_seconds: int,
) -> None:
    cutoff = now_monotonic - window_seconds
    while events and events[0][0] < cutoff:
        events.popleft()


def _resolve_monitored_endpoint(
    path: str,
    endpoints: List[str],
    *,
    exact_endpoints: Optional[List[str]] = None,
    method: Optional[str] = None,
) -> Optional[str]:
    if not path:
        return None
    clean_path = path.strip()
    normalized_method = str(method or "").strip().upper()
    for endpoint in exact_endpoints or []:
        if clean_path == endpoint:
            return endpoint if normalized_method == "GET" else None
    matches = [endpoint for endpoint in endpoints if clean_path.startswith(endpoint)]
    if not matches:
        return None
    # Prioriza o prefixo mais especifico.
    return sorted(matches, key=len, reverse=True)[0]


def record_http_status(status_code: int) -> None:
    if int(status_code) < 500 or int(status_code) > 599:
        return

    config = get_http_5xx_monitor_config()
    window_seconds = int(config["window_minutes"]) * 60
    now_monotonic = time.monotonic()
    now_utc = _utc_now()

    with _HTTP_5XX_LOCK:
        _HTTP_5XX_EVENTS.append((now_monotonic, now_utc))
        _purge_old_events_locked(now_monotonic=now_monotonic, window_seconds=window_seconds)


def record_http_request(
    *,
    path: str,
    status_code: int,
    duration_ms: float,
    method: Optional[str] = None,
    database_ms: Optional[float] = None,
    database_query_count: Optional[int] = None,
    pool_wait_ms: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Registra o resumo em memória e devolve uma amostra segura para persistir.

    A função nunca escreve no banco: a middleware agenda a escrita após a
    resposta para que indisponibilidade da telemetria não afete o usuário.
    """

    status_int = int(status_code)
    duration_float = float(duration_ms)
    if duration_float < 0:
        duration_float = 0.0

    record_http_status(status_int)

    config = get_http_latency_monitor_config()
    endpoint = _resolve_monitored_endpoint(
        path,
        list(config["priority_endpoint_prefixes"]),
        exact_endpoints=list(config["exact_endpoints"]),
        method=method,
    )
    if endpoint is None:
        return None

    request_context = _REQUEST_LATENCY_CONTEXT.get() or {}
    database_float = float(
        request_context.get("database_ms", 0.0) if database_ms is None else database_ms
    )
    pool_wait_float = float(
        request_context.get("pool_wait_ms", 0.0) if pool_wait_ms is None else pool_wait_ms
    )
    database_query_count_int = int(
        request_context.get("database_query_count", 0)
        if database_query_count is None
        else database_query_count
    )
    database_float = max(0.0, database_float)
    pool_wait_float = max(0.0, pool_wait_float)
    database_query_count_int = max(0, database_query_count_int)
    application_float = max(0.0, duration_float - database_float - pool_wait_float)

    window_seconds = int(config["window_minutes"]) * 60
    max_samples = int(config["max_samples_per_endpoint"])
    now_monotonic = time.monotonic()
    now_utc = _utc_now()

    with _HTTP_LATENCY_LOCK:
        events = _HTTP_LATENCY_EVENTS.setdefault(endpoint, deque())
        events.append(
            (
                now_monotonic,
                duration_float,
                status_int,
                database_float,
                pool_wait_float,
                database_query_count_int,
                application_float,
                now_utc,
            )
        )
        _purge_old_latency_events_locked(
            events,
            now_monotonic=now_monotonic,
            window_seconds=window_seconds,
        )
        while len(events) > max_samples:
            events.popleft()

    persistence_config = get_http_latency_persistence_config()
    if not persistence_config["enabled"]:
        return None
    return {
        "endpoint": endpoint,
        "release_id": persistence_config["release_id"],
        "status_code": status_int,
        "duration_ms": round(duration_float, 3),
        "database_ms": round(database_float, 3),
        "database_query_count": database_query_count_int,
        "application_ms": round(application_float, 3),
        "pool_wait_ms": round(pool_wait_float, 3),
        "created_at": now_utc,
    }


def get_http_5xx_monitor_status() -> Dict[str, Any]:
    config = get_http_5xx_monitor_config()
    window_seconds = int(config["window_minutes"]) * 60
    now_monotonic = time.monotonic()

    with _HTTP_5XX_LOCK:
        _purge_old_events_locked(now_monotonic=now_monotonic, window_seconds=window_seconds)
        recent_count = len(_HTTP_5XX_EVENTS)
        last_5xx_at = _HTTP_5XX_EVENTS[-1][1].isoformat() if _HTTP_5XX_EVENTS else None

    threshold = int(config["threshold"])
    return {
        "window_minutes": int(config["window_minutes"]),
        "threshold": threshold,
        "recent_5xx_count": recent_count,
        "alert_active": recent_count >= threshold,
        "last_5xx_at": last_5xx_at,
        "config_warnings": list(config["warnings"]),
    }


def _percentile_ms(values: List[float], percentile: int) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return round(float(ordered[rank - 1]), 2)


def get_http_latency_monitor_status() -> Dict[str, Any]:
    config = get_http_latency_monitor_config()
    window_seconds = int(config["window_minutes"]) * 60
    now_monotonic = time.monotonic()
    endpoints = list(config["priority_endpoints"])
    endpoint_payload: Dict[str, Any] = {}

    with _HTTP_LATENCY_LOCK:
        for endpoint in endpoints:
            events = _HTTP_LATENCY_EVENTS.setdefault(endpoint, deque())
            _purge_old_latency_events_locked(
                events,
                now_monotonic=now_monotonic,
                window_seconds=window_seconds,
            )
            samples = list(events)

            durations = [sample[1] for sample in samples]
            database_durations = [sample[3] for sample in samples]
            pool_waits = [sample[4] for sample in samples]
            database_query_counts = [float(sample[5]) for sample in samples]
            application_durations = [sample[6] for sample in samples]
            request_count = len(samples)
            error_5xx_count = sum(1 for sample in samples if 500 <= int(sample[2]) <= 599)
            avg_ms = round(sum(durations) / request_count, 2) if request_count else None
            database_avg_ms = (
                round(sum(database_durations) / request_count, 2) if request_count else None
            )
            pool_wait_avg_ms = round(sum(pool_waits) / request_count, 2) if request_count else None
            p50_ms = _percentile_ms(durations, 50)
            p95_ms = _percentile_ms(durations, 95)
            p99_ms = _percentile_ms(durations, 99)
            last_seen_at = samples[-1][7].isoformat() if samples else None

            endpoint_payload[endpoint] = {
                "request_count": request_count,
                "error_5xx_count": error_5xx_count,
                "avg_ms": avg_ms,
                "max_ms": round(max(durations), 2) if durations else None,
                "slow_request_count": sum(
                    1 for duration in durations if duration > _SLOW_REQUEST_THRESHOLD_MS
                ),
                "p50_ms": p50_ms,
                "p95_ms": p95_ms,
                "p99_ms": p99_ms,
                "database_avg_ms": database_avg_ms,
                "database_p95_ms": _percentile_ms(database_durations, 95),
                "database_query_count_avg": (
                    round(sum(database_query_counts) / request_count, 2)
                    if request_count
                    else None
                ),
                "database_query_count_p95": _percentile_ms(database_query_counts, 95),
                "application_avg_ms": (
                    round(sum(application_durations) / request_count, 2)
                    if request_count
                    else None
                ),
                "application_p95_ms": _percentile_ms(application_durations, 95),
                "pool_wait_avg_ms": pool_wait_avg_ms,
                "pool_wait_p95_ms": _percentile_ms(pool_waits, 95),
                "last_seen_at": last_seen_at,
            }

    persistence_config = get_http_latency_persistence_config()
    return {
        "window_minutes": int(config["window_minutes"]),
        "max_samples_per_endpoint": int(config["max_samples_per_endpoint"]),
        "slow_request_threshold_ms": _SLOW_REQUEST_THRESHOLD_MS,
        "priority_endpoints": endpoints,
        "priority_endpoint_prefixes": list(config["priority_endpoint_prefixes"]),
        "exact_endpoints": list(config["exact_endpoints"]),
        "endpoints": endpoint_payload,
        "persistence": {
            "enabled": persistence_config["enabled"],
            "retention_days": persistence_config["retention_days"],
            "release_id": persistence_config["release_id"],
        },
        "config_warnings": list(config["warnings"]) + list(persistence_config["warnings"]),
    }


def _claim_persistence_cleanup(now_monotonic: float, interval_seconds: int) -> bool:
    global _LAST_PERSISTENCE_CLEANUP_MONOTONIC
    with _PERSISTENCE_CLEANUP_LOCK:
        if (
            _LAST_PERSISTENCE_CLEANUP_MONOTONIC is not None
            and now_monotonic - _LAST_PERSISTENCE_CLEANUP_MONOTONIC < interval_seconds
        ):
            return False
        _LAST_PERSISTENCE_CLEANUP_MONOTONIC = now_monotonic
        return True


def persist_http_latency_sample(sample: Mapping[str, Any]) -> bool:
    """Persiste uma amostra já higienizada, isolando qualquer falha do request."""

    config = get_http_latency_persistence_config()
    if not config["enabled"]:
        return False

    endpoint = str(sample.get("endpoint") or "")
    allowed_endpoints = set(get_http_latency_monitor_config()["priority_endpoints"])
    if endpoint not in allowed_endpoints:
        logger.warning("Amostra de latencia descartada por endpoint nao priorizado.")
        return False

    try:
        status_code = int(sample["status_code"])
        duration_ms = max(0.0, float(sample["duration_ms"]))
        database_ms = max(0.0, float(sample.get("database_ms", 0.0)))
        database_query_count = max(0, int(sample.get("database_query_count", 0)))
        pool_wait_ms = max(0.0, float(sample.get("pool_wait_ms", 0.0)))
    except (KeyError, TypeError, ValueError):
        logger.warning("Amostra de latencia descartada por formato invalido.")
        return False

    from app.db.database import SessionLocal
    from app.models.runtime_http_latency_metric import RuntimeHttpLatencyMetric

    db = None
    try:
        db = SessionLocal()
        db.add(
            RuntimeHttpLatencyMetric(
                endpoint=endpoint,
                release_id=_safe_release_id(sample.get("release_id") or config["release_id"]),
                status_code=status_code,
                duration_ms=duration_ms,
                database_ms=database_ms,
                database_query_count=database_query_count,
                pool_wait_ms=pool_wait_ms,
                created_at=sample.get("created_at") or _utc_now(),
            )
        )
        db.commit()

        if _claim_persistence_cleanup(
            time.monotonic(),
            int(config["cleanup_interval_seconds"]),
        ):
            cutoff = _utc_now() - timedelta(days=int(config["retention_days"]))
            db.query(RuntimeHttpLatencyMetric).filter(
                RuntimeHttpLatencyMetric.created_at < cutoff
            ).delete(synchronize_session=False)
            db.commit()
        return True
    except Exception:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
        logger.exception("Falha ao persistir telemetria de latencia HTTP.")
        return False
    finally:
        if db is not None:
            db.close()


def get_persisted_http_latency_summary(db: Any, *, hours: int) -> Dict[str, Any]:
    """Agrega amostras persistidas sem devolver registros individuais."""

    from sqlalchemy import desc
    from sqlalchemy.exc import SQLAlchemyError

    from app.models.runtime_http_latency_metric import RuntimeHttpLatencyMetric

    config = get_http_latency_persistence_config()
    max_samples = int(config["query_max_samples"])
    cutoff = _utc_now() - timedelta(hours=int(hours))
    try:
        rows = (
            db.query(RuntimeHttpLatencyMetric)
            .filter(RuntimeHttpLatencyMetric.created_at >= cutoff)
            .order_by(desc(RuntimeHttpLatencyMetric.created_at))
            .limit(max_samples + 1)
            .all()
        )
    except SQLAlchemyError:
        logger.exception("Falha ao consultar telemetria persistida de latencia HTTP.")
        return {
            "available": False,
            "hours": int(hours),
            "retention_days": int(config["retention_days"]),
            "query_max_samples": max_samples,
            "slow_request_threshold_ms": _SLOW_REQUEST_THRESHOLD_MS,
            "truncated": False,
            "groups": [],
        }

    truncated = len(rows) > max_samples
    rows = rows[:max_samples]
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        key = (str(row.endpoint), str(row.release_id or "unknown"))
        group = groups.setdefault(
            key,
            {
                "endpoint": key[0],
                "release_id": key[1],
                "durations": [],
                "database_durations": [],
                "database_query_counts": [],
                "application_durations": [],
                "pool_waits": [],
                "error_5xx_count": 0,
                "last_seen_at": None,
            },
        )
        group["durations"].append(float(row.duration_ms or 0.0))
        database_duration = float(row.database_ms or 0.0)
        pool_wait = float(row.pool_wait_ms or 0.0)
        group["database_durations"].append(database_duration)
        group["database_query_counts"].append(float(row.database_query_count or 0))
        group["application_durations"].append(
            max(0.0, float(row.duration_ms or 0.0) - database_duration - pool_wait)
        )
        group["pool_waits"].append(pool_wait)
        if 500 <= int(row.status_code or 0) <= 599:
            group["error_5xx_count"] += 1
        if group["last_seen_at"] is None:
            group["last_seen_at"] = (
                row.created_at.isoformat() if getattr(row, "created_at", None) else None
            )

    result_groups = []
    for group in groups.values():
        durations = group.pop("durations")
        database_durations = group.pop("database_durations")
        database_query_counts = group.pop("database_query_counts")
        application_durations = group.pop("application_durations")
        pool_waits = group.pop("pool_waits")
        request_count = len(durations)
        result_groups.append(
            {
                **group,
                "request_count": request_count,
                "avg_ms": round(sum(durations) / request_count, 2) if request_count else None,
                "max_ms": round(max(durations), 2) if durations else None,
                "slow_request_count": sum(
                    1 for duration in durations if duration > _SLOW_REQUEST_THRESHOLD_MS
                ),
                "p50_ms": _percentile_ms(durations, 50),
                "p95_ms": _percentile_ms(durations, 95),
                "p99_ms": _percentile_ms(durations, 99),
                "database_avg_ms": (
                    round(sum(database_durations) / request_count, 2)
                    if request_count
                    else None
                ),
                "database_p95_ms": _percentile_ms(database_durations, 95),
                "database_query_count_avg": (
                    round(sum(database_query_counts) / request_count, 2)
                    if request_count
                    else None
                ),
                "database_query_count_p95": _percentile_ms(database_query_counts, 95),
                "application_avg_ms": (
                    round(sum(application_durations) / request_count, 2)
                    if request_count
                    else None
                ),
                "application_p95_ms": _percentile_ms(application_durations, 95),
                "pool_wait_avg_ms": (
                    round(sum(pool_waits) / request_count, 2) if request_count else None
                ),
                "pool_wait_p95_ms": _percentile_ms(pool_waits, 95),
            }
        )

    result_groups.sort(
        key=lambda group: (group["p95_ms"] is not None, group["p95_ms"] or 0.0),
        reverse=True,
    )
    return {
        "available": True,
        "hours": int(hours),
        "retention_days": int(config["retention_days"]),
        "query_max_samples": max_samples,
        "slow_request_threshold_ms": _SLOW_REQUEST_THRESHOLD_MS,
        "truncated": truncated,
        "groups": result_groups,
    }


def reset_http_5xx_monitor_state_for_tests() -> None:
    global _LAST_PERSISTENCE_CLEANUP_MONOTONIC
    with _HTTP_5XX_LOCK:
        _HTTP_5XX_EVENTS.clear()
    with _HTTP_LATENCY_LOCK:
        _HTTP_LATENCY_EVENTS.clear()
    with _PERSISTENCE_CLEANUP_LOCK:
        _LAST_PERSISTENCE_CLEANUP_MONOTONIC = None
    _REQUEST_LATENCY_CONTEXT.set(None)
