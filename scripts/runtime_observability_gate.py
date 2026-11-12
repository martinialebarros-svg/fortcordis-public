#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple


def _fetch_json(url: str, timeout_seconds: int) -> Tuple[int, Dict[str, Any]]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200))
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Payload JSON invalido: objeto esperado.")
            return status, payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} ao consultar {url}. Body: {body[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexao ao consultar {url}: {exc}") from exc


def _load_health_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.health_json:
        payload = json.loads(args.health_json)
        if not isinstance(payload, dict):
            raise RuntimeError("health_json invalido: objeto JSON esperado.")
        return payload
    _, payload = _fetch_json(args.health_url, args.timeout_seconds)
    return payload


def _validate_health_payload(health: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    readiness = str(health.get("readiness") or "").strip().lower()
    if readiness != "ready":
        errors.append(f"health.readiness esperado 'ready', recebido '{readiness or 'vazio'}'.")

    checks = health.get("checks")
    if not isinstance(checks, dict):
        return errors + ["health.checks ausente ou invalido."]

    observability = checks.get("observability")
    if not isinstance(observability, dict):
        return errors + ["health.checks.observability ausente ou invalido."]

    http_5xx_monitor = observability.get("http_5xx_monitor")
    if not isinstance(http_5xx_monitor, dict):
        errors.append("observability.http_5xx_monitor ausente ou invalido.")
    else:
        if bool(http_5xx_monitor.get("alert_active")):
            errors.append(
                "observability.http_5xx_monitor.alert_active=true (deve ser false para liberar deploy)."
            )

    cleanup_worker = observability.get("upload_dedupe_cleanup_worker")
    if not isinstance(cleanup_worker, dict):
        errors.append("observability.upload_dedupe_cleanup_worker ausente ou invalido.")
    else:
        workers_managed_externally = bool(health.get("background_workers_managed_externally"))
        enabled = bool(cleanup_worker.get("enabled"))
        status = str(cleanup_worker.get("status") or "").strip().lower()
        thread_alive = bool(cleanup_worker.get("thread_alive"))
        if enabled and not workers_managed_externally and status != "running":
            errors.append(
                "worker de cleanup habilitado com status diferente de running "
                f"(status atual: {status or 'vazio'})."
            )
        if enabled and not workers_managed_externally and not thread_alive:
            errors.append("worker de cleanup habilitado com thread_alive=false.")

    return errors


def _validate_ready_endpoint(ready_url: str, timeout_seconds: int) -> List[str]:
    errors: List[str] = []
    status, payload = _fetch_json(ready_url, timeout_seconds)
    if status != 200:
        errors.append(f"/ready retornou HTTP {status} (esperado 200).")
    readiness = str(payload.get("readiness") or "").strip().lower()
    if readiness != "ready":
        errors.append(f"/ready.readiness esperado 'ready', recebido '{readiness or 'vazio'}'.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate pos-deploy para observabilidade/runtime."
    )
    parser.add_argument(
        "--health-url",
        default="http://127.0.0.1:8000/health",
        help="URL do endpoint /health do backend.",
    )
    parser.add_argument(
        "--ready-url",
        default="http://127.0.0.1:8000/ready",
        help="URL do endpoint /ready do backend.",
    )
    parser.add_argument(
        "--skip-ready-check",
        action="store_true",
        help="Pula validacao do endpoint /ready.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=8,
        help="Timeout de chamadas HTTP em segundos.",
    )
    parser.add_argument(
        "--health-json",
        default="",
        help="Payload JSON de /health (modo offline de validacao).",
    )
    args = parser.parse_args()

    all_errors: List[str] = []
    try:
        health_payload = _load_health_payload(args)
        all_errors.extend(_validate_health_payload(health_payload))
    except Exception as exc:
        all_errors.append(f"Falha ao validar /health: {exc}")
        health_payload = {}

    if not args.skip_ready_check and not args.health_json:
        try:
            all_errors.extend(_validate_ready_endpoint(args.ready_url, args.timeout_seconds))
        except Exception as exc:
            all_errors.append(f"Falha ao validar /ready: {exc}")

    observability = (
        health_payload.get("checks", {}).get("observability", {})
        if isinstance(health_payload, dict)
        else {}
    )
    http_5xx = observability.get("http_5xx_monitor", {}) if isinstance(observability, dict) else {}
    worker = (
        observability.get("upload_dedupe_cleanup_worker", {})
        if isinstance(observability, dict)
        else {}
    )
    workers_managed_externally = bool(
        health_payload.get("background_workers_managed_externally")
        if isinstance(health_payload, dict)
        else False
    )
    print("[gate] readiness:", health_payload.get("readiness"))
    if isinstance(http_5xx, dict):
        print(
            "[gate] http_5xx:",
            f"count={http_5xx.get('recent_5xx_count')}",
            f"alert_active={http_5xx.get('alert_active')}",
            f"window={http_5xx.get('window_minutes')}",
            f"threshold={http_5xx.get('threshold')}",
        )
    if workers_managed_externally:
        print("[gate] cleanup_worker: managed_externally=True")
    elif isinstance(worker, dict):
        print(
            "[gate] cleanup_worker:",
            f"enabled={worker.get('enabled')}",
            f"status={worker.get('status')}",
            f"thread_alive={worker.get('thread_alive')}",
        )

    if all_errors:
        print("[gate] FAILED")
        for item in all_errors:
            print(f"[gate] - {item}")
        return 1

    print("[gate] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
