#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


DEFAULT_BASE_URL = "https://app.fortcordis.com.br"


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
    req = urllib.request.Request(
        url=url,
        method=method,
        headers=headers or {"Accept": "application/json"},
        data=body,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            status = int(getattr(resp, "status", 200))
            raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise RuntimeError(f"Resposta JSON invalida em {url}: objeto esperado")
            return status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} em {url}: {raw[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de conexao em {url}: {exc}") from exc


def _token_from_login(*, base_url: str, username: str, password: str, timeout_seconds: int) -> str:
    login_url = _join_url(base_url, "/api/v1/auth/login")
    form = urllib.parse.urlencode(
        {
            "username": username,
            "password": password,
            "grant_type": "password",
        }
    ).encode("utf-8")
    status, payload = _http_json(
        login_url,
        timeout_seconds=timeout_seconds,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=form,
    )
    if status != 200:
        raise RuntimeError(f"Login retornou status inesperado: {status}")
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Login sem access_token")
    return token


def _token_from_internal_backend(backend_dir: str) -> str:
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
            "Falha ao carregar backend para token interno. Informe token direto via BASELINE_BEARER_TOKEN."
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
            raise RuntimeError("Nenhum usuario ativo encontrado para gerar token interno")

        papeis = [str(p.nome) for p in getattr(admin_user, "papeis", []) if getattr(p, "nome", None)]
        payload = {
            "sub": str(admin_user.email),
            "user_id": int(admin_user.id),
            "nome": str(getattr(admin_user, "nome", "") or ""),
            "papeis": papeis,
            "exp": datetime.now(timezone.utc).timestamp() + 600,
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        if not token:
            raise RuntimeError("Token interno vazio")
        return token
    finally:
        db.close()
        os.chdir(previous_cwd)


def _resolve_token(args: argparse.Namespace) -> str:
    direct = str(args.bearer_token or "").strip()
    if direct:
        return direct

    env_token = str(os.getenv("BASELINE_BEARER_TOKEN", "") or os.getenv("CANARY_BEARER_TOKEN", "")).strip()
    if env_token:
        return env_token

    username = str(args.username or os.getenv("CANARY_USERNAME", "")).strip()
    password = str(args.password or os.getenv("CANARY_PASSWORD", "")).strip()
    if username and password:
        return _token_from_login(
            base_url=args.base_url,
            username=username,
            password=password,
            timeout_seconds=args.timeout_seconds,
        )

    if args.disable_internal_token:
        raise RuntimeError(
            "Sem token disponivel. Defina BASELINE_BEARER_TOKEN (ou CANARY_BEARER_TOKEN) para coletar baseline em prod."
        )

    return _token_from_internal_backend(args.backend_dir)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta baseline pos-deploy de custo/logistica em producao")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", DEFAULT_BASE_URL), help="Base URL da aplicacao")
    parser.add_argument("--timeout-seconds", type=int, default=12, help="Timeout por request")
    parser.add_argument("--short-days", type=int, default=1, help="Janela curta para resumo")
    parser.add_argument("--long-days", type=int, default=30, help="Janela longa para custo/quotas")
    parser.add_argument("--output-root", default="ops/baseline/prod", help="Diretorio raiz de saida")
    parser.add_argument("--tag", default="", help="Tag opcional para pasta de saida")
    parser.add_argument("--bearer-token", default="", help="Token bearer explicito")
    parser.add_argument("--username", default="", help="Usuario para login")
    parser.add_argument("--password", default="", help="Senha para login")
    parser.add_argument("--backend-dir", default="./backend", help="Diretorio backend para fallback de token interno")
    parser.add_argument("--disable-internal-token", action="store_true", help="Nao tentar token interno local")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = f"-{args.tag}" if str(args.tag).strip() else ""
    out_dir = Path(args.output_root) / f"{stamp}{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        token = _resolve_token(args)
    except Exception as exc:
        print(f"[baseline] FAILED ao resolver token: {exc}")
        print("[baseline] Dica: export BASELINE_BEARER_TOKEN='<token>' e execute novamente.")
        return 2

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    checks = [
        (
            "google_maps_resumo_d1.json",
            f"/api/v1/logistica/google-maps/resumo?dias={max(1, int(args.short_days))}&incluir_inativas=false",
        ),
        (
            "google_maps_custos_quotas_d30.json",
            f"/api/v1/logistica/google-maps/custos-quotas?dias={max(1, int(args.long_days))}&incluir_inativas=false",
        ),
        (
            "hardening_readiness.json",
            "/api/v1/admin/hardening-readiness",
        ),
    ]

    meta: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "output_dir": str(out_dir),
        "results": [],
    }

    failed = False
    for filename, path in checks:
        url = _join_url(args.base_url, path)
        try:
            status, payload = _http_json(
                url,
                timeout_seconds=max(1, int(args.timeout_seconds)),
                headers=headers,
            )
            _write_json(out_dir / filename, payload)
            meta["results"].append({"file": filename, "path": path, "status": status, "ok": True})
            print(f"[baseline] OK {filename} (HTTP {status})")
        except Exception as exc:
            failed = True
            meta["results"].append({"file": filename, "path": path, "ok": False, "error": str(exc)})
            print(f"[baseline] FAIL {filename}: {exc}")

    _write_json(out_dir / "_meta.json", meta)
    print(f"[baseline] Artefatos salvos em: {out_dir}")

    if failed:
        print("[baseline] Concluido com falhas. Veja _meta.json")
        return 1

    print("[baseline] Concluido com sucesso")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
