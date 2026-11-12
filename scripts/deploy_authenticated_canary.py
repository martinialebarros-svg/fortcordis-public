#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _http_json(
    url: str,
    *,
    timeout_seconds: int,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
) -> Tuple[int, Dict[str, Any]]:
    request = urllib.request.Request(
        url,
        method=method,
        headers=headers or {"Accept": "application/json"},
        data=body,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise RuntimeError(f"Resposta JSON invalida em {url}: objeto esperado.")
            return status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} em {url}: {raw[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexao em {url}: {exc}") from exc


def _token_from_login(
    *,
    base_url: str,
    username: str,
    password: str,
    timeout_seconds: int,
) -> str:
    url = _join_url(base_url, "/api/v1/auth/login")
    form = urllib.parse.urlencode(
        {
            "username": username,
            "password": password,
            "grant_type": "password",
        }
    ).encode("utf-8")
    status, payload = _http_json(
        url,
        timeout_seconds=timeout_seconds,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=form,
    )
    if status != 200:
        raise RuntimeError(f"Login retornou status inesperado: {status}")
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Login sem access_token.")
    return token


def _supabase_canary_token(db, user, cleanup: ExitStack) -> str:
    """Issue a real, locally revoked session; never send email or change a password."""
    from app.services import supabase_auth

    identity = supabase_auth.find_identity(user)
    if identity is None or supabase_auth.load_app_user(db, identity).id != user.id:
        raise RuntimeError("Usuario canary sem identidade Supabase vinculada.")
    generated = supabase_auth.request_auth(
        "POST", "admin/generate_link", admin=True,
        body={"type": "magiclink", "email": user.email},
    )
    if generated.get("id") != identity["id"] or not generated.get("hashed_token"):
        raise RuntimeError("Vinculo Supabase do canary inconsistente.")
    session = supabase_auth.request_auth(
        "POST", "verify", body={"type": "email", "token_hash": generated["hashed_token"]},
    )
    token = session.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Sessao Supabase canary ausente.")
    cleanup.callback(supabase_auth.sign_out, token)
    if supabase_auth.get_user(db, token).id != user.id:
        raise RuntimeError("Sessao Supabase canary inconsistente.")
    return token


def _token_from_internal_backend(backend_dir: str, cleanup: ExitStack) -> str:
    backend_dir = os.path.abspath(backend_dir)
    if not os.path.isdir(backend_dir):
        raise RuntimeError(f"backend_dir invalido: {backend_dir}")

    previous_cwd = os.getcwd()
    os.chdir(backend_dir)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    try:
        from jose import jwt  # type: ignore
        from app.core.config import settings  # type: ignore
        from app.db.database import SessionLocal  # type: ignore
        from app.models.user import User  # type: ignore
    except Exception as exc:
        os.chdir(previous_cwd)
        raise RuntimeError(
            "Falha ao carregar backend para token interno. "
            "Confirme venv/dependencias e backend_dir."
        ) from exc

    db = SessionLocal()
    try:
        users = db.query(User).all()
        admin_user = None
        for user in users:
            try:
                if int(getattr(user, "ativo", 0) or 0) == 1 and user.tem_papel("admin"):
                    admin_user = user
                    break
            except Exception:
                continue
        if admin_user is None:
            for user in users:
                if int(getattr(user, "ativo", 0) or 0) == 1 and getattr(user, "email", None):
                    admin_user = user
                    break
        if admin_user is None:
            raise RuntimeError("Nenhum usuario ativo encontrado para token canary.")

        if settings.AUTH_PROVIDER == "supabase":
            if not admin_user.tem_papel("admin"):
                raise RuntimeError("Nenhum administrador ativo para canary Supabase.")
            return _supabase_canary_token(db, admin_user, cleanup)

        papeis = [str(p.nome) for p in getattr(admin_user, "papeis", []) if getattr(p, "nome", None)]
        payload = {
            "sub": str(admin_user.email),
            "user_id": int(admin_user.id),
            "nome": str(getattr(admin_user, "nome", "") or ""),
            "papeis": papeis,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        if not token:
            raise RuntimeError("Token interno vazio.")
        return token
    finally:
        db.close()
        os.chdir(previous_cwd)


def _resolve_token(args: argparse.Namespace, cleanup: ExitStack) -> str:
    if args.bearer_token:
        return args.bearer_token
    env_token = str(os.getenv("CANARY_BEARER_TOKEN", "")).strip()
    if env_token:
        return env_token

    username = args.username or str(os.getenv("CANARY_USERNAME", "")).strip()
    password = args.password or str(os.getenv("CANARY_PASSWORD", "")).strip()
    if username and password:
        return _token_from_login(
            base_url=args.base_url,
            username=username,
            password=password,
            timeout_seconds=args.timeout_seconds,
        )

    if args.disable_internal_token:
        raise RuntimeError("Token canary indisponivel (sem token, sem login e fallback interno desativado).")

    return _token_from_internal_backend(args.backend_dir, cleanup)


def _validate_admin_payload(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        return ["Payload admin sem bloco runtime."]

    if bool(runtime.get("ready")) is not True:
        errors.append("runtime.ready diferente de true.")

    observability = runtime.get("observability")
    if not isinstance(observability, dict):
        errors.append("runtime.observability ausente ou invalido.")
        return errors

    http_5xx = observability.get("http_5xx_monitor")
    if not isinstance(http_5xx, dict):
        errors.append("runtime.observability.http_5xx_monitor ausente ou invalido.")
    elif bool(http_5xx.get("alert_active")):
        errors.append("http_5xx_monitor.alert_active=true.")

    worker = observability.get("upload_dedupe_cleanup_worker")
    if not isinstance(worker, dict):
        errors.append("runtime.observability.upload_dedupe_cleanup_worker ausente ou invalido.")
    else:
        environment = runtime.get("environment")
        workers_managed_externally = bool(
            environment.get("background_workers_managed_externally")
            if isinstance(environment, dict)
            else False
        )
        enabled = bool(worker.get("enabled"))
        status = str(worker.get("status") or "").strip().lower()
        thread_alive = bool(worker.get("thread_alive"))
        if enabled and not workers_managed_externally and status != "running":
            errors.append(f"worker cleanup habilitado com status invalido: {status or 'vazio'}.")
        if enabled and not workers_managed_externally and not thread_alive:
            errors.append("worker cleanup habilitado com thread_alive=false.")

    return errors


def _validate_agenda_payload(payload: Dict[str, Any]) -> List[str]:
    if not isinstance(payload.get("items"), list):
        return ["Resposta de agenda sem campo items (lista)."]
    return []


def _validate_success_status(status: int, *, expected: int = 200) -> List[str]:
    """401/403 nunca sao canario aprovado, mesmo que tenham JSON valido."""

    if int(status) == int(expected):
        return []
    return [f"HTTP {status} (esperado {expected})."]


def _percentile_ms(values: List[float], percentile: int) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(max(0.0, float(value)) for value in values)
    rank = max(1, math.ceil((float(percentile) / 100.0) * len(ordered)))
    return round(ordered[rank - 1], 2)


def _validate_agenda_latency(
    samples_ms: List[float],
    *,
    expected_samples: int,
    max_p95_ms: float,
) -> List[str]:
    errors: List[str] = []
    if len(samples_ms) != int(expected_samples):
        errors.append(
            "Agenda sem todas as amostras de latencia esperadas "
            f"({len(samples_ms)}/{expected_samples})."
        )
        return errors

    p95_ms = _percentile_ms(samples_ms, 95)
    if p95_ms is None:
        errors.append("Agenda sem amostras de latencia validas.")
    elif p95_ms > float(max_p95_ms):
        errors.append(
            f"Agenda p95={p95_ms:.2f}ms excede o limite de {float(max_p95_ms):.2f}ms."
        )
    return errors


def _validate_cleanup_status_payload(payload: Dict[str, Any]) -> List[str]:
    required_keys = {"last_status", "consecutive_failures", "alert_active"}
    missing = [key for key in required_keys if key not in payload]
    if missing:
        return [f"Resposta cleanup/status sem campos esperados: {', '.join(missing)}."]
    return []


def _validate_assistente_ia_status_payload(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if bool(payload.get("enabled")) is not True:
        errors.append("assistente IA desabilitado.")
    if bool(payload.get("configured")) is not True:
        errors.append("assistente IA sem credencial configurada.")
    if bool(payload.get("admin_only")) is not True:
        errors.append("assistente IA sem restricao admin_only.")
    if not str(payload.get("model") or "").strip():
        errors.append("assistente IA sem modelo configurado.")
    return errors


def _run_agenda_latency_canary(
    args: argparse.Namespace,
    auth_header: Dict[str, str],
) -> List[str]:
    """Mede uma pequena amostra autenticada sem registrar payloads da Agenda."""

    errors: List[str] = []
    samples_ms: List[float] = []
    agenda_url = _join_url(args.base_url, "/api/v1/agenda")
    for sample_number in range(1, int(args.agenda_latency_samples) + 1):
        started_at = time.monotonic()
        try:
            status, payload = _http_json(
                agenda_url,
                timeout_seconds=args.timeout_seconds,
                headers=auth_header,
            )
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            status_errors = _validate_success_status(status)
            payload_errors = _validate_agenda_payload(payload)
            if status_errors or payload_errors:
                errors.extend(f"[agenda_latency amostra {sample_number}] {item}" for item in status_errors)
                errors.extend(f"[agenda_latency amostra {sample_number}] {item}" for item in payload_errors)
                continue
            samples_ms.append(elapsed_ms)
        except Exception as exc:
            errors.append(f"[agenda_latency amostra {sample_number}] falhou: {exc}")

    p50_ms = _percentile_ms(samples_ms, 50)
    p95_ms = _percentile_ms(samples_ms, 95)
    release_id = str(args.expected_release_id or "unknown").strip() or "unknown"
    print(
        "[canary] agenda_latency:",
        f"release={release_id}",
        f"samples={len(samples_ms)}/{args.agenda_latency_samples}",
        f"p50_ms={p50_ms if p50_ms is not None else 'n/a'}",
        f"p95_ms={p95_ms if p95_ms is not None else 'n/a'}",
        f"limit_ms={float(args.agenda_max_p95_ms):.2f}",
    )
    errors.extend(
        f"[agenda_latency] {item}"
        for item in _validate_agenda_latency(
            samples_ms,
            expected_samples=args.agenda_latency_samples,
            max_p95_ms=args.agenda_max_p95_ms,
        )
    )
    return errors


def _run_canary(args: argparse.Namespace) -> List[str]:
    with ExitStack() as cleanup:
        token = _resolve_token(args, cleanup)
        return _run_authenticated_canary(args, token)


def _run_authenticated_canary(args: argparse.Namespace, token: str) -> List[str]:
    errors: List[str] = []
    auth_header = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    checks = [
        (
            "admin_hardening",
            "/api/v1/admin/hardening-readiness",
            _validate_admin_payload,
        ),
        (
            "atendimento_cleanup_status",
            "/api/v1/atendimentos/upload-metrics/dedupe/cleanup/status",
            _validate_cleanup_status_payload,
        ),
        (
            "assistente_ia_status",
            "/api/v1/assistente-ia/status",
            _validate_assistente_ia_status_payload,
        ),
    ]

    for check_name, path, validator in checks:
        url = _join_url(args.base_url, path)
        try:
            status, payload = _http_json(
                url,
                timeout_seconds=args.timeout_seconds,
                headers=auth_header,
            )
            status_errors = _validate_success_status(status)
            if status_errors:
                errors.extend(f"[{check_name}] {item}" for item in status_errors)
                continue
            validation_errors = validator(payload)
            for item in validation_errors:
                errors.append(f"[{check_name}] {item}")
        except Exception as exc:
            errors.append(f"[{check_name}] falhou: {exc}")

    errors.extend(_run_agenda_latency_canary(args, auth_header))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Canary smoke autenticado pos-deploy.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL da API backend para o smoke canary.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=8,
        help="Timeout de cada chamada HTTP.",
    )
    parser.add_argument("--username", default="", help="Usuario para login canary.")
    parser.add_argument("--password", default="", help="Senha para login canary.")
    parser.add_argument("--bearer-token", default="", help="Token bearer pre-existente para canary.")
    parser.add_argument(
        "--backend-dir",
        default="./backend",
        help="Diretorio do backend (usado no fallback de token interno).",
    )
    parser.add_argument(
        "--disable-internal-token",
        action="store_true",
        help="Desativa fallback de token interno gerado no VPS.",
    )
    parser.add_argument(
        "--agenda-latency-samples",
        type=int,
        default=5,
        help="Quantidade de leituras autenticadas da Agenda usadas para o p95.",
    )
    parser.add_argument(
        "--agenda-max-p95-ms",
        type=float,
        default=1200.0,
        help="Limite de p95, em ms, para as leituras autenticadas da Agenda.",
    )
    parser.add_argument(
        "--expected-release-id",
        default="",
        help="Hash curto do release, exibido somente no resumo seguro do canario.",
    )
    args = parser.parse_args()
    if args.agenda_latency_samples < 2:
        parser.error("--agenda-latency-samples deve ser no minimo 2.")
    if args.agenda_max_p95_ms <= 0:
        parser.error("--agenda-max-p95-ms deve ser maior que zero.")

    errors = _run_canary(args)
    if errors:
        print("[canary] FAILED")
        for item in errors:
            print(f"[canary] - {item}")
        return 1
    print("[canary] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
