#!/usr/bin/env python3
"""Validate current prod/stage Supabase project refs from VPS .env files."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

EXPECTED = {
    "PROD": {
        "env_path": Path("/var/www/fortcordis-v2/backend/.env"),
        "expected_ref": "wycxoueogfxdhyouhfhw",
        "expected_root": "/var/www/fortcordis-v2",
    },
    "STAGE": {
        "env_path": Path("/var/www/fortcordis-stage/backend/.env"),
        "expected_ref": "dtguubpzjrkvqjryazjq",
        "expected_root": "/var/www/fortcordis-stage",
    },
}


def _extract_database_url(env_path: Path) -> str:
    text = env_path.read_text(encoding="utf-8")
    match = re.search(r"^DATABASE_URL=(.+)$", text, re.M)
    if not match:
        raise RuntimeError(f"DATABASE_URL not found in {env_path}")
    return match.group(1).strip()


def _extract_project_ref(database_url: str) -> str:
    parsed = urlparse(database_url)
    username = parsed.username or ""
    if username.startswith("postgres."):
        return username.split(".", 1)[1]
    host = parsed.hostname or ""
    if host.startswith("db.") and ".supabase." in host:
        return host.split(".")[1]
    return ""


def main() -> int:
    failures = 0
    print("FortCordis environment matrix check")
    print("=" * 36)

    for name, cfg in EXPECTED.items():
        env_path = cfg["env_path"]
        expected_ref = cfg["expected_ref"]
        print(f"\n[{name}]")
        print(f"env: {env_path}")
        print(f"root: {cfg['expected_root']}")

        if not env_path.exists():
            print("status: FAIL")
            print("reason: env file not found")
            failures += 1
            continue

        try:
            database_url = _extract_database_url(env_path)
            parsed = urlparse(database_url)
            project_ref = _extract_project_ref(database_url)
        except Exception as exc:
            print("status: FAIL")
            print(f"reason: {exc}")
            failures += 1
            continue

        print(f"user: {parsed.username or 'missing'}")
        print(f"host: {parsed.hostname or 'missing'}")
        print(f"project_ref: {project_ref or 'missing'}")
        print(f"expected_ref: {expected_ref}")

        if project_ref != expected_ref:
            print("status: FAIL")
            failures += 1
            continue

        print("status: OK")

    print("\nResult:", "OK" if failures == 0 else f"FAIL ({failures} environment(s))")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
