#!/usr/bin/env python3
"""Stage-only real Agenda proof in disposable schemas; zero Google or real-data writes."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if root != Path('/var/www/fortcordis-stage') or not re.fullmatch('[a-f0-9]{40}', args.expected_sha):
        raise RuntimeError('Only exact stage checkout is allowed')
    installed = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    assert installed == args.expected_sha, 'Unexpected stage snapshot'
    backend = root/'backend'
    os.chdir(backend)
    sys.path[:0] = [str(backend),str(backend/'tests'),str(root/'scripts')]
    from app.core.config import settings
    from fiscal_rotina_stage_canary import _validar_destino
    _validar_destino(root, settings.APP_ENV, settings.DATABASE_URL)
    assert settings.GOOGLE_MAPS_AGENDA_CACHE_FIRST is True
    assert settings.GOOGLE_ROUTES_CACHE_EXPIRE_BY_AGE is False
    assert settings.GOOGLE_MAPS_COST_EMERGENCY_RELEASE is False
    from deploy_authenticated_canary import _token_from_internal_backend
    with ExitStack() as cleanup:
        bearer = _token_from_internal_backend(str(backend), cleanup)
        def live(path, body=None):
            request = Request('http://127.0.0.1:8001/api/v1'+path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'Authorization':'Bearer '+bearer,'Content-Type':'application/json'})
            try:
                with urlopen(request,timeout=20) as response: return response.status,json.loads(response.read())
            except HTTPError as exc: return exc.code,json.loads(exc.read())
        code,status = live('/google-maps-control/status')
        assert code == 200 and status['agenda_cache_first'] and status['operation_mode'] != 'temporary_open'
        assert not status['paid_calls_allowed'], 'Operational stage must have no paid budget enabled'
        code,route_policy = live('/logistica/google-maps/resumo?dias=1')
        assert code == 200 and route_policy['cache_expires_by_age'] is False
        code,preview = live('/google-maps-control/preview',{'method':'POST','path':'/api/v1/agenda','body':{}})
        assert code == 200 and not preview['required'] and not preview['blocked'] and preview['max_calls'] == 0
        code,_ = live('/agenda',{})
        assert code == 422, 'Unconfigured finance must not mask normal Agenda form validation'
    from sqlalchemy import create_engine,event,text
    from sqlalchemy.pool import NullPool
    from app.services import geocoding_service
    from test_google_maps_agenda_cache_first import GoogleMapsAgendaCacheFirstTest
    admin = create_engine(settings.DATABASE_URL,poolclass=NullPool)
    checks = []
    cases = [
        'test_internal_monitor_direct_request_records_without_popup_or_confirmation',
        'test_internal_monitor_cached_request_needs_no_ledger_or_estimate',
        'test_internal_monitor_cold_ledger_failure_never_sends',
        'test_internal_monitor_finite_scope_expires_closes_and_cannot_authorize_background',
        'test_internal_monitor_does_not_bypass_enforce_mode',
        'test_internal_monitor_parallel_scopes_remain_finite_after_reconnect',
        'test_internal_monitor_background_task_cannot_extend_http_authorization',
        'test_internal_monitor_rollout_can_restore_interactive_policy',
        'test_internal_monitor_real_search_uses_requested_period_and_cache',
        'test_internal_monitor_planner_reuses_business_connection_under_concurrency',
        'test_internal_monitor_failed_estimate_never_uses_generic_cap',
        'test_internal_monitor_expired_prices_warn_internally_and_extras_remain_closed',
        'test_local_preview_and_cached_booking_work_with_unavailable_ledger',
        'test_old_cached_routes_complete_agenda_without_finance_or_google',
        'test_old_cache_with_new_geocode_still_requires_consent_and_never_commits',
        'test_old_heuristic_does_not_become_valid_by_disabling_age_expiry',
        'test_create_booking_with_cache_succeeds_without_financial_policy',
        'test_cache_continues_after_daily_budget_exhaustion',
        'test_unpaid_probe_rolls_back_then_one_confirmed_execution_succeeds',
        'test_new_booking_stops_before_google_and_requires_single_use_consent',
        'test_cold_cache_and_unavailable_ledger_never_send_or_commit',
        'test_monitor_allows_new_booking_above_references_but_keeps_consent_and_replay_guard',
        'test_monitor_quote_and_cancel_do_not_send_and_extras_automatics_still_stop',
        'test_monitor_parallel_grants_remain_finite_and_durable',
        'test_cache_only_rejects_monitor_exception',
        'test_agenda_tutor_geocode_uses_one_confirmed_unit_above_references',
        'test_proposed_monitor_config_keeps_reception_above_references_and_extras_closed',
        'test_expired_monitor_prices_warn_and_complete_booking_without_freeing_extras',
        'test_monitor_quote_survives_review_date_but_not_its_own_expiry_or_cap',
        'test_expired_monitor_prices_keep_tutor_geocode_single_use',
        'test_expired_monitor_parallel_confirmations_remain_finite',
        'test_expired_monitor_date_does_not_override_admin_suspension',
        'test_search_quote_uses_missing_matrix_directions_instead_of_generic_cap',
        'test_complete_search_matrix_needs_no_paid_grant_or_refresh',
        'test_search_confirmation_is_finite_and_extras_stay_closed',
        'test_search_plan_unavailable_never_uses_generic_quote_or_google',
        'test_real_offer_search_respects_calculated_envelope_and_reuses_route_results',
        'test_reference_alerts_distinguish_actual_from_potential_overage',
        'test_search_geocoding_fallback_and_readonly_plan_are_explicit',
        'test_offer_validation_plan_uses_fortaleza_date_at_utc_boundary',
        'test_explicit_today_ignores_other_days_and_uses_cache_without_paid_ledger',
        'test_explicit_interval_overrides_reference_contact_and_policy_dates',
        'test_requested_period_still_counts_missing_routes_inside_interval',
        'test_explicit_today_real_offers_never_pay_for_outside_policy_anchors',

    ]
    try:
        for name in cases:
            schema = 'maps_canary_' + uuid4().hex
            with admin.begin() as conn: conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            engine = create_engine(settings.DATABASE_URL,pool_size=2,max_overflow=0,pool_pre_ping=True,
                execution_options={'schema_translate_map':{None:schema}})
            @event.listens_for(engine,'begin')
            def isolate_transaction(conn):
                # Raw legacy SQL/introspection must never resolve real tables.
                conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            try:
                case = GoogleMapsAgendaCacheFirstTest(name)
                case._isolated_engine = engine
                result = unittest.TestResult()
                with patch.object(geocoding_service,'urlopen',side_effect=AssertionError('Real Google forbidden')):
                    case.run(result)
                checks.append({'case':name,'passed':result.wasSuccessful() and result.testsRun==1,
                    'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)})
                if not checks[-1]['passed']: break
            finally:
                engine.dispose()
                with admin.begin() as conn: conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        with admin.begin() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            remaining = conn.scalar(text("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'maps_canary_%'"))
        proof = {'checked_at':datetime.now(timezone.utc).isoformat(),'expected_sha':installed,
            'live_cache_first_preview_passed':True,'live_empty_form_validation':422,
            'live_cache_expires_by_age':False,
            'operational_paid_budget_enabled':False,'isolated_postgresql':True,'checks':checks,
            'temporary_schemas_remaining':remaining,'real_google_calls':0,'existing_operational_records_modified':0}
        proof['passed'] = len(checks)==len(cases) and all(c['passed'] for c in checks) and remaining==0
        print(json.dumps(proof))
        if not proof['passed']: raise SystemExit(1)
    finally: admin.dispose()


if __name__ == '__main__': main()
