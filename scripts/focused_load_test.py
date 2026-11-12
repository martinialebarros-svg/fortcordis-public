#!/usr/bin/env python3
"""Focused load test for critical FortCordis API endpoints.

Runs concurrent GET requests across selected endpoints and reports:
- throughput
- error rate
- latency percentiles (p50/p95/p99)
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any


DEFAULT_ENDPOINTS = [
    "/api/v1/agenda",
    "/api/v1/atendimentos",
    "/api/v1/relatorios",
    "/api/v1/fiscal",
    "/api/v1/logistica",
]


@dataclass
class RequestResult:
    endpoint: str
    status_code: int
    latency_ms: float
    ok: bool
    error: str | None = None


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return float(ordered[low])
    weight = rank - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


def normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def build_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "fortcordis-focused-load-test/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def request_once(
    *,
    base_url: str,
    endpoint: str,
    timeout_sec: int,
    headers: dict[str, str],
) -> RequestResult:
    started = time.perf_counter()
    status_code = 0
    try:
        req = urllib.request.Request(
            url=f"{base_url}{endpoint}",
            method="GET",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            _ = response.read()
            status_code = int(response.getcode() or 0)
            latency_ms = (time.perf_counter() - started) * 1000.0
            ok = 200 <= status_code < 500
            return RequestResult(
                endpoint=endpoint,
                status_code=status_code,
                latency_ms=latency_ms,
                ok=ok,
            )
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        status_code = int(exc.code or 0)
        # 4xx are functional/auth errors but still relevant; 5xx considered failure.
        ok = 400 <= status_code < 500
        return RequestResult(
            endpoint=endpoint,
            status_code=status_code,
            latency_ms=latency_ms,
            ok=ok,
            error=f"HTTP {status_code}",
        )
    except Exception as exc:  # pragma: no cover - runtime/network failure path
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RequestResult(
            endpoint=endpoint,
            status_code=status_code,
            latency_ms=latency_ms,
            ok=False,
            error=str(exc),
        )


def run_endpoint_burst(
    *,
    base_url: str,
    endpoint: str,
    total_requests: int,
    concurrency: int,
    timeout_sec: int,
    headers: dict[str, str],
) -> list[RequestResult]:
    results: list[RequestResult] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                request_once,
                base_url=base_url,
                endpoint=endpoint,
                timeout_sec=timeout_sec,
                headers=headers,
            )
            for _ in range(total_requests)
        ]
        for future in as_completed(futures):
            result = future.result()
            with lock:
                results.append(result)
    return results


def summarize(results: list[RequestResult]) -> dict[str, Any]:
    latencies = [item.latency_ms for item in results]
    ok_count = sum(1 for item in results if item.ok)
    err_count = len(results) - ok_count
    status_histogram: dict[str, int] = {}
    for item in results:
        key = str(item.status_code or 0)
        status_histogram[key] = status_histogram.get(key, 0) + 1

    return {
        "total_requests": len(results),
        "ok_count": ok_count,
        "error_count": err_count,
        "error_rate_percent": round((err_count / max(1, len(results))) * 100, 2),
        "latency_ms": {
            "avg": round(statistics.fmean(latencies), 2) if latencies else None,
            "p50": round(percentile(latencies, 0.50) or 0.0, 2) if latencies else None,
            "p95": round(percentile(latencies, 0.95) or 0.0, 2) if latencies else None,
            "p99": round(percentile(latencies, 0.99) or 0.0, 2) if latencies else None,
        },
        "status_histogram": status_histogram,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Focused load test for FortCordis critical endpoints.")
    parser.add_argument("--base-url", required=True, help="API base URL, e.g. https://app.fortcordis.com.br")
    parser.add_argument(
        "--endpoints",
        default=",".join(DEFAULT_ENDPOINTS),
        help="Comma-separated endpoint paths.",
    )
    parser.add_argument("--requests-per-endpoint", type=int, default=120, help="Total requests per endpoint.")
    parser.add_argument("--concurrency", type=int, default=12, help="Concurrent workers per endpoint.")
    parser.add_argument("--timeout-sec", type=int, default=8, help="HTTP timeout in seconds.")
    parser.add_argument("--bearer-token", default="", help="Optional bearer token.")
    parser.add_argument("--max-error-rate", type=float, default=5.0, help="Fail gate when error rate is above this percent.")
    parser.add_argument("--max-p95-ms", type=float, default=1200.0, help="Fail gate when p95 latency is above this threshold.")
    parser.add_argument("--output-json", default="", help="Optional output path for JSON summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = normalize_base_url(args.base_url)
    headers = build_headers(args.bearer_token)
    endpoints = [item.strip() for item in str(args.endpoints).split(",") if item.strip()]
    started = time.perf_counter()

    all_results: dict[str, list[RequestResult]] = {}
    for endpoint in endpoints:
        all_results[endpoint] = run_endpoint_burst(
            base_url=base_url,
            endpoint=endpoint,
            total_requests=max(1, int(args.requests_per_endpoint)),
            concurrency=max(1, int(args.concurrency)),
            timeout_sec=max(1, int(args.timeout_sec)),
            headers=headers,
        )

    duration_sec = time.perf_counter() - started
    summary: dict[str, Any] = {
        "base_url": base_url,
        "duration_sec": round(duration_sec, 2),
        "requests_per_endpoint": int(args.requests_per_endpoint),
        "concurrency": int(args.concurrency),
        "endpoints": {},
    }

    fail_reasons: list[str] = []
    for endpoint, rows in all_results.items():
        endpoint_summary = summarize(rows)
        summary["endpoints"][endpoint] = endpoint_summary

        if float(endpoint_summary["error_rate_percent"]) > float(args.max_error_rate):
            fail_reasons.append(
                f"{endpoint}: error_rate={endpoint_summary['error_rate_percent']}% > {args.max_error_rate}%"
            )

        p95_value = endpoint_summary["latency_ms"]["p95"]
        if p95_value is not None and float(p95_value) > float(args.max_p95_ms):
            fail_reasons.append(f"{endpoint}: p95={p95_value}ms > {args.max_p95_ms}ms")

    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fp:
            json.dump(summary, fp, indent=2, ensure_ascii=False)
            fp.write("\n")

    if fail_reasons:
        print("LOAD_TEST_GATE_FAILED")
        for reason in fail_reasons:
            print(f"- {reason}")
        return 2

    print("LOAD_TEST_GATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
