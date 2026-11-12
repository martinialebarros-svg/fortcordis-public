#!/usr/bin/env python3
"""Run the installed phrase handler in disposable PostgreSQL stage schemas.

Synthetic identity and fixtures; never mount app.main, access operational tables,
create sessions for real users, or contact providers. Cleanup is mandatory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if root != Path("/var/www/fortcordis-stage") or not re.fullmatch("[a-f0-9]{40}", args.expected_sha):
        raise RuntimeError("Exact stage checkout and full SHA required")
    installed = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if installed != args.expected_sha:
        raise RuntimeError("Unexpected installed snapshot")
    backend = root / "backend"
    os.chdir(backend)
    sys.path[:0] = [str(backend), str(backend / "tests"), str(root / "scripts")]
    from app.core.config import settings
    from fiscal_rotina_stage_canary import _validar_destino
    _validar_destino(root, settings.APP_ENV, settings.DATABASE_URL)

    from sqlalchemy import create_engine, event, text
    from sqlalchemy.pool import NullPool
    from test_clinical_phrase_connection_pool import ClinicalPhraseConnectionPoolTest

    admin = create_engine(settings.DATABASE_URL, poolclass=NullPool)
    checks = []
    schemas = []
    provider_calls = 0

    def forbid_network(*_args, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("Provider network forbidden in phrase canary")

    cases = ["test_occupied_pool_reuses_session_and_preserves_query_contract",
             "test_read_does_not_commit_or_flush_pending_work"] + [
                 "test_three_authenticated_requests_with_three_connections"] * 5
    try:
        with patch("urllib.request.urlopen", side_effect=forbid_network), \
             patch("requests.sessions.Session.request", side_effect=forbid_network):
            for name in cases:
                schema = "clinical_phrase_pool_canary_" + uuid4().hex
                schemas.append(schema)
                with admin.begin() as conn:
                    conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                engine = create_engine(settings.DATABASE_URL, pool_size=3, max_overflow=0,
                    pool_timeout=0.5, execution_options={"schema_translate_map": {None: schema}})

                @event.listens_for(engine, "begin")
                def isolate(conn):
                    # No public fallback, including raw introspection/legacy SQL.
                    conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')

                try:
                    case = ClinicalPhraseConnectionPoolTest(name)
                    case._isolated_engine = engine
                    result = unittest.TestResult()
                    case.run(result)
                    checks.append({"case": name, "passed": result.wasSuccessful() and result.testsRun == 1,
                        "failures": len(result.failures), "errors": len(result.errors),
                        "proof": getattr(case, "proof", None)})
                    if not checks[-1]["passed"]:
                        # Error text can contain connection details; emit only counts.
                        break
                finally:
                    engine.dispose()
                    with admin.begin() as conn:
                        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        with admin.begin() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            remaining = conn.scalar(text("SELECT count(*) FROM pg_namespace WHERE nspname = ANY(:schemas)"),
                                    {"schemas": schemas})
        proof = {"expected_sha": installed, "isolated_postgresql": True, "synthetic_identity": True,
            "checks": checks, "temporary_schemas_remaining": remaining, "provider_calls": provider_calls,
            "operational_records_modified": 0}
        proof["passed"] = len(checks) == len(cases) and all(c["passed"] for c in checks) and remaining == provider_calls == 0
        print(json.dumps(proof))
        if not proof["passed"]:
            raise SystemExit(1)
    finally:
        admin.dispose()


if __name__ == "__main__":
    main()
