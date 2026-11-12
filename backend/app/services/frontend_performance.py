from __future__ import annotations

import logging
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError

from app.services.runtime_observability import get_http_latency_persistence_config

logger = logging.getLogger(__name__)

ALLOWED_ROUTE_GROUPS = (
    "/dashboard",
    "/atendimento",
    "/laudos",
    "/configuracoes",
)
ALLOWED_NAVIGATION_TYPES = ("initial", "client")
ALLOWED_OUTCOMES = ("ready", "partial", "error", "timeout", "cancelled")
MAX_DURATION_MS = 120_000.0
SLOW_CONTENT_THRESHOLD_MS = 3_000.0

_CLEANUP_LOCK = threading.Lock()
_LAST_CLEANUP_MONOTONIC: Optional[float] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_release_id(raw_value: Any) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]", "", str(raw_value or "").strip())
    return normalized[:80] or "unknown"


def _duration(raw_value: Any, *, required: bool) -> Optional[float]:
    if raw_value is None and not required:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("duracao invalida") from exc
    if not math.isfinite(value) or value < 0 or value > MAX_DURATION_MS:
        raise ValueError("duracao fora da faixa permitida")
    return round(value, 3)


def build_frontend_performance_sample(payload: Mapping[str, Any]) -> Dict[str, Any]:
    route_group = str(payload.get("route_group") or "").strip()
    navigation_type = str(payload.get("navigation_type") or "").strip()
    outcome = str(payload.get("outcome") or "").strip()
    if route_group not in ALLOWED_ROUTE_GROUPS:
        raise ValueError("rota nao monitorada")
    if navigation_type not in ALLOWED_NAVIGATION_TYPES:
        raise ValueError("tipo de navegacao invalido")
    if outcome not in ALLOWED_OUTCOMES:
        raise ValueError("desfecho invalido")

    shell_ms = _duration(payload.get("shell_ms"), required=True)
    content_ms = _duration(payload.get("content_ms"), required=False)
    if outcome in {"ready", "partial", "error"} and content_ms is None:
        raise ValueError("content_ms obrigatorio para carga concluida")
    if content_ms is not None and shell_ms is not None and content_ms < shell_ms:
        raise ValueError("content_ms nao pode ser menor que shell_ms")

    config = get_http_latency_persistence_config()
    return {
        "route_group": route_group,
        "release_id": _safe_release_id(config["release_id"]),
        "navigation_type": navigation_type,
        "outcome": outcome,
        "shell_ms": shell_ms,
        "content_ms": content_ms,
        "created_at": _utc_now(),
    }


def _claim_cleanup(now_monotonic: float, interval_seconds: int) -> bool:
    global _LAST_CLEANUP_MONOTONIC
    with _CLEANUP_LOCK:
        if (
            _LAST_CLEANUP_MONOTONIC is not None
            and now_monotonic - _LAST_CLEANUP_MONOTONIC < interval_seconds
        ):
            return False
        _LAST_CLEANUP_MONOTONIC = now_monotonic
        return True


def persist_frontend_performance_sample(sample: Mapping[str, Any]) -> bool:
    config = get_http_latency_persistence_config()
    if not config["enabled"]:
        return False

    try:
        safe_sample = build_frontend_performance_sample(sample)
    except ValueError:
        logger.warning("Amostra de desempenho do frontend descartada por formato invalido.")
        return False

    # O release e o instante preparados pelo endpoint devem permanecer estaveis
    # mesmo se a tarefa de fundo iniciar depois de uma troca de configuracao.
    safe_sample["release_id"] = _safe_release_id(
        sample.get("release_id") or safe_sample["release_id"]
    )
    safe_sample["created_at"] = sample.get("created_at") or safe_sample["created_at"]

    from app.db.database import SessionLocal
    from app.models.runtime_frontend_performance_metric import RuntimeFrontendPerformanceMetric

    db = None
    try:
        db = SessionLocal()
        db.add(RuntimeFrontendPerformanceMetric(**safe_sample))
        db.commit()

        if _claim_cleanup(time.monotonic(), int(config["cleanup_interval_seconds"])):
            cutoff = _utc_now() - timedelta(days=int(config["retention_days"]))
            db.query(RuntimeFrontendPerformanceMetric).filter(
                RuntimeFrontendPerformanceMetric.created_at < cutoff
            ).delete(synchronize_session=False)
            db.commit()
        return True
    except Exception:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
        logger.exception("Falha ao persistir telemetria de desempenho do frontend.")
        return False
    finally:
        if db is not None:
            db.close()


def _percentile(values: List[float], percentile: int) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return round(float(ordered[rank - 1]), 2)


def get_frontend_performance_summary(db: Any, *, hours: int) -> Dict[str, Any]:
    from app.models.runtime_frontend_performance_metric import RuntimeFrontendPerformanceMetric

    config = get_http_latency_persistence_config()
    max_samples = int(config["query_max_samples"])
    cutoff = _utc_now() - timedelta(hours=int(hours))
    try:
        rows = (
            db.query(RuntimeFrontendPerformanceMetric)
            .filter(RuntimeFrontendPerformanceMetric.created_at >= cutoff)
            .order_by(desc(RuntimeFrontendPerformanceMetric.created_at))
            .limit(max_samples + 1)
            .all()
        )
    except SQLAlchemyError:
        logger.exception("Falha ao consultar telemetria de desempenho do frontend.")
        return {
            "available": False,
            "hours": int(hours),
            "retention_days": int(config["retention_days"]),
            "query_max_samples": max_samples,
            "slow_content_threshold_ms": SLOW_CONTENT_THRESHOLD_MS,
            "truncated": False,
            "groups": [],
        }

    truncated = len(rows) > max_samples
    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for row in rows[:max_samples]:
        key = (
            str(row.route_group),
            str(row.release_id or "unknown"),
            str(row.navigation_type),
        )
        group = groups.setdefault(
            key,
            {
                "route_group": key[0],
                "release_id": key[1],
                "navigation_type": key[2],
                "shell_values": [],
                "content_values": [],
                "outcomes": {item: 0 for item in ALLOWED_OUTCOMES},
                "last_seen_at": None,
            },
        )
        group["shell_values"].append(float(row.shell_ms or 0.0))
        if row.content_ms is not None:
            group["content_values"].append(float(row.content_ms))
        if row.outcome in group["outcomes"]:
            group["outcomes"][row.outcome] += 1
        if group["last_seen_at"] is None:
            group["last_seen_at"] = row.created_at.isoformat() if row.created_at else None

    result_groups = []
    for group in groups.values():
        shell_values = group.pop("shell_values")
        content_values = group.pop("content_values")
        outcomes = group.pop("outcomes")
        result_groups.append(
            {
                **group,
                "sample_count": len(shell_values),
                "shell_p50_ms": _percentile(shell_values, 50),
                "shell_p95_ms": _percentile(shell_values, 95),
                "shell_p99_ms": _percentile(shell_values, 99),
                "content_p50_ms": _percentile(content_values, 50),
                "content_p95_ms": _percentile(content_values, 95),
                "content_p99_ms": _percentile(content_values, 99),
                "content_max_ms": round(max(content_values), 2) if content_values else None,
                "slow_content_count": sum(
                    1 for value in content_values if value > SLOW_CONTENT_THRESHOLD_MS
                ),
                "ready_count": outcomes["ready"],
                "partial_count": outcomes["partial"],
                "error_count": outcomes["error"],
                "timeout_count": outcomes["timeout"],
                "cancelled_count": outcomes["cancelled"],
            }
        )

    result_groups.sort(
        key=lambda group: (
            group["content_p95_ms"] is not None,
            group["content_p95_ms"] or 0.0,
        ),
        reverse=True,
    )
    return {
        "available": True,
        "hours": int(hours),
        "retention_days": int(config["retention_days"]),
        "query_max_samples": max_samples,
        "slow_content_threshold_ms": SLOW_CONTENT_THRESHOLD_MS,
        "truncated": truncated,
        "groups": result_groups,
    }


def reset_frontend_performance_state_for_tests() -> None:
    global _LAST_CLEANUP_MONOTONIC
    with _CLEANUP_LOCK:
        _LAST_CLEANUP_MONOTONIC = None
