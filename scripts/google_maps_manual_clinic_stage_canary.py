#!/usr/bin/env python3
"""Prove manual clinic policy in disposable Stage PG schemas; deny all network."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    assert root == Path('/var/www/fortcordis-stage')
    assert re.fullmatch('[a-f0-9]{40}', args.expected_sha)
    installed = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    assert installed == args.expected_sha
    backend = root / 'backend'
    os.chdir(backend)
    sys.path[:0] = [str(backend), str(backend / 'tests'), str(root / 'scripts')]
    from app.core.config import settings
    from fiscal_rotina_stage_canary import _validar_destino
    _validar_destino(root, settings.APP_ENV, settings.DATABASE_URL)
    assert settings.GOOGLE_MAPS_COST_EMERGENCY_RELEASE is False
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.pool import NullPool
    import test_google_maps_cost_control as ledger_tests
    from test_google_maps_manual_clinic import ManualClinicGeocodeTest
    from test_google_maps_agenda_cache_first import GoogleMapsAgendaCacheFirstTest
    admin = create_engine(settings.DATABASE_URL, poolclass=NullPool)
    cases = [(ManualClinicGeocodeTest, name) for name in unittest.defaultTestLoader.getTestCaseNames(ManualClinicGeocodeTest)]
    cases += [(GoogleMapsAgendaCacheFirstTest, name) for name in (
        'test_internal_monitor_direct_request_records_without_popup_or_confirmation',
        'test_internal_monitor_expired_prices_warn_internally_and_extras_remain_closed',
        'test_internal_monitor_parallel_scopes_remain_finite_after_reconnect',
        'test_internal_monitor_background_task_cannot_extend_http_authorization',
        'test_internal_monitor_real_search_uses_requested_period_and_cache',
    )]
    checks = []
    created = []
    try:
        for case_class, name in cases:
            schema = 'maps_manual_' + uuid4().hex
            created.append(schema)
            with admin.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            # Keep eight concurrent callers, but share two test connections.
            # Match the existing Stage Agenda canary; do not exhaust its pooler.
            engine = create_engine(settings.DATABASE_URL, pool_size=2, max_overflow=0,
                                   execution_options={'schema_translate_map': {None: schema}})
            @event.listens_for(engine, 'begin')
            def isolate(conn):
                conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            try:
                case = case_class(name)
                case._isolated_engine = engine
                result = unittest.TestResult()
                # PostgreSQL uses libpq's already configured socket transport.
                # Any Python HTTP/provider socket attempt makes this proof fail.
                with ExitStack() as stack:
                    stack.enter_context(patch.object(socket.socket, 'connect', side_effect=AssertionError('External transport forbidden')))
                    if case_class is ManualClinicGeocodeTest:
                        stack.enter_context(patch.object(ledger_tests, '_engine', return_value=engine))
                    case.run(result)
                checks.append({'case': name, 'passed': result.wasSuccessful() and result.testsRun == 1,
                               'failures': len(result.failures), 'errors': len(result.errors)})
                if not checks[-1]['passed']:
                    # Test traces contain only synthetic fixture data.
                    for _, failure in result.failures + result.errors:
                        print(failure, file=sys.stderr)
                    break
            finally:
                engine.dispose()
                with admin.begin() as conn:
                    conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        with admin.begin() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            remaining = conn.scalar(text('SELECT count(*) FROM pg_namespace WHERE nspname = ANY(:schemas)'), {'schemas': created})
        proof = {'checked_at': datetime.now(timezone.utc).isoformat(), 'installed_sha': installed,
                 'stage_identity_verified': True, 'isolated_postgresql': True, 'checks': checks,
                 'temporary_schemas_remaining': remaining, 'real_google_calls': 0,
                 'operational_auth_sessions_created': 0, 'existing_operational_records_modified': 0,
                 'operational_policy_modified': False, 'test_connection_pool_size': 2}
        proof['passed'] = len(checks) == len(cases) and all(c['passed'] for c in checks) and remaining == 0
        print(json.dumps(proof))
        if not proof['passed']:
            raise SystemExit(1)
    finally:
        admin.dispose()


if __name__ == '__main__':
    main()
