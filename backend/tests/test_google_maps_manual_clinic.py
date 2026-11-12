"""Explicit manual clinic scope. Isolated ledger, no external calls."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_google_maps_cost_control import GoogleMapsCostControlTest
from app.services import google_maps_cost_control as guard, google_maps_cost_middleware as middleware


class ManualClinicGeocodeTest(unittest.TestCase):
    configure = GoogleMapsCostControlTest.configure
    claim = GoogleMapsCostControlTest.claim
    reserve = GoogleMapsCostControlTest.reserve
    tearDown = GoogleMapsCostControlTest.tearDown
    postgres = False
    path = '/api/v1/clinicas/geocode-endereco'

    def setUp(self):
        GoogleMapsCostControlTest.setUp(self)
        self.config['clinic_geocode_manual_enabled'] = True
        self.config['action_call_caps'] = {key: 0 for key in ('matrix_recalculate', 'route_lookup', 'tutor_geocode', 'assistant_chat', 'assistant_decision')}
        self.config['action_call_caps']['clinic_geocode'] = 1
        # Stage runner supplies only a disposable schema.

    def direct(self):
        return self.claim(None, path=self.path, body={'endereco': 'synthetic'})

    def test_manual_preview_no_popup_or_scope(self):
        self.configure()
        quote = guard.create_preview(7, 'POST', self.path, body={'endereco': 'synthetic'})
        self.assertFalse(quote['required'])
        self.assertFalse(quote['blocked'])
        self.assertEqual(quote['confirmation_mode'], 'server_recorded')
        self.assertEqual(quote['max_calls'], 1)
        with self.engine.connect() as conn:
            self.assertEqual(list(conn.execute(select(guard.ACTIONS))), [])

    def test_manual_http_scope_records_one_attempt_and_closes(self):
        self.configure()
        app = FastAPI()
        app.add_middleware(middleware.GoogleMapsCostMiddleware)
        @app.post(self.path)
        def explicit_geocode():
            guard.authorize_google_call('geocoding')
            return {'ok': True}
        with patch.object(middleware, '_authenticate', return_value=7), TestClient(app) as client:
            result = client.post(self.path, json={'endereco': 'synthetic'})
        self.assertEqual(result.status_code, 200, result.text)
        with self.engine.connect() as conn:
            rows = conn.execute(select(guard.ACTIONS)).mappings().all()
            events = conn.execute(select(guard.EVENTS)).mappings().all()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['max_calls'], row['used_calls'], row['state']), (1, 1, 'finished'))
        self.assertEqual(row['expires_at'] - row['claimed_at'], 600)
        self.assertIsNone(row['token_hash'])
        self.assertTrue(any(e['kind'] == 'internal_authorized' and e['reason'] == 'clinic_manual_record' for e in events))
        self.assertEqual(sum(e['calls'] for e in events if e['kind'] == 'reserved'), 1)
        self.assertFalse(any(e['kind'] in ('confirmed', 'quoted') for e in events))

    def test_manual_real_geocoding_adapter_reserves_before_transport(self):
        from app.services import geocoding_service
        self.configure()
        execution = self.direct()
        token = guard.bind_execution(execution)
        try:
            with patch.object(geocoding_service, '_http_get_json', return_value={'status': 'ZERO_RESULTS'}) as outbound:
                with self.assertRaises(geocoding_service.GeocodingError):
                    geocoding_service.geocodificar_endereco_google('Synthetic', 'synthetic-not-real')
                self.assertEqual(outbound.call_count, 1)
                with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                    geocoding_service.geocodificar_endereco_google('Synthetic', 'synthetic-not-real')
                self.assertEqual(exc.exception.reason, 'action_limit')
                self.assertEqual(outbound.call_count, 1)
        finally:
            guard.reset_execution(token)
            guard.finish_execution(execution)

    def test_manual_expired_prices_and_disabled_block_before_scope(self):
        self.configure()
        with patch.object(guard, '_now', return_value=guard._now() + 172800):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                self.direct()
        self.assertEqual(exc.exception.reason, 'pricing_expired')
        self.config['enabled'] = False
        self.configure(revision=1)
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            self.direct()
        self.assertEqual(exc.exception.reason, 'disabled')

    def test_manual_second_sku_expiry_and_background_blocked(self):
        self.configure()
        execution = self.direct()
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            self.reserve(execution, 'routes_essentials')
        self.assertEqual(exc.exception.reason, 'sku_not_authorized')
        self.reserve(execution, 'geocoding')
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            self.reserve(execution, 'geocoding')
        self.assertEqual(exc.exception.reason, 'action_limit')
        guard.finish_execution(execution)
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            self.reserve(execution, 'geocoding')
        self.assertEqual(exc.exception.reason, 'invalid_grant')
        execution = self.direct()
        with patch.object(guard, '_now', return_value=guard._now() + 601):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                self.reserve(execution, 'geocoding')
        self.assertEqual(exc.exception.reason, 'invalid_grant')

    def test_manual_parallel_budget_remains_hard_and_durable(self):
        self.config['limits']['day']['calls'] = 1
        self.configure()
        scopes = [self.direct() for _ in range(8)]
        def attempt(scope):
            try:
                self.reserve(scope, 'geocoding')
                return 'reserved'
            except guard.GoogleMapsCostBlocked as exc:
                return exc.reason
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, scopes))
        self.assertEqual(results.count('reserved'), 1)
        self.assertEqual(results.count('day_limit'), 7)
        self.engine.dispose()
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            self.direct()
        self.assertEqual(exc.exception.reason, 'day_limit')

    def test_manual_approved_references_remain_650_25_and_13000_500(self):
        self.config['limits'] = {'action': {'calls': 4096, 'estimated_brl': 5},
                                 'day': {'calls': 650, 'estimated_brl': 25},
                                 'month': {'calls': 13000, 'estimated_brl': 500}}
        self.config['opening_usage']['day'] = {'calls': 649, 'estimated_brl': 24.94}
        self.config['opening_usage']['month'] = {'calls': 12999, 'estimated_brl': 499.94}
        self.configure()
        self.reserve(self.direct(), 'geocoding')
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            self.direct()
        self.assertEqual(exc.exception.reason, 'day_limit')
        saved = guard.get_status()['config']['limits']
        for period, limit in self.config['limits'].items():
            self.assertEqual(saved[period]['calls'], limit['calls'])
            self.assertEqual(float(saved[period]['estimated_brl']), limit['estimated_brl'])
        self.assertEqual(guard.get_status()['config']['automatic_policies'], {})

    def test_manual_month_cost_and_revision_remain_hard(self):
        self.config['limits']['month']['estimated_brl'] = 0.06
        self.configure()
        first, second = self.direct(), self.direct()
        self.reserve(first, 'geocoding')
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            self.reserve(second, 'geocoding')
        self.assertEqual(exc.exception.reason, 'month_limit')
        self.config['clinic_geocode_manual_enabled'] = False
        self.config['action_call_caps']['clinic_geocode'] = 0
        self.configure(revision=1)
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            self.reserve(second, 'geocoding')
        self.assertEqual(exc.exception.reason, 'configuration_changed')

    def test_manual_disabled_zero_cap_reports_action_not_day(self):
        self.config['clinic_geocode_manual_enabled'] = False
        self.config['action_call_caps']['clinic_geocode'] = 0
        self.configure()
        quote = guard.create_preview(7, 'POST', self.path)
        self.assertTrue(quote['blocked'])
        self.assertEqual(quote['reason'], 'action_limit')
        with self.assertRaises(guard.GoogleMapsCostBlocked):
            self.direct()

    def test_manual_flag_requires_exact_cap_and_paid_mode(self):
        for cap in (0, 2, None):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                self.config['action_call_caps']['clinic_geocode'] = cap
                guard.CostConfiguration.model_validate(self.config)
        self.config['action_call_caps']['clinic_geocode'] = 1
        self.config['operation_mode'] = 'cache_only'
        with self.assertRaises(ValueError):
            guard.CostConfiguration.model_validate(self.config)

    def test_manual_ledger_failure_never_opens_scope(self):
        self.configure()
        with patch.object(guard, '_locked', side_effect=guard.GoogleMapsCostBlocked('ledger_unavailable', status_code=503)):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                self.direct()
        self.assertEqual(exc.exception.reason, 'ledger_unavailable')

    def test_manual_permission_does_not_enroll_automatic_or_other_extras(self):
        self.configure()
        for path in ('/api/v1/tutores/geocode-endereco', '/api/v1/logistica/matriz/recalcular'):
            spec = guard.identify_action('POST', path)
            if spec:
                self.assertTrue(guard.create_preview(7, 'POST', path)['blocked'])
        with guard.automatic_execution('clinic_geocode', 'synthetic-run'):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                guard.authorize_google_call('geocoding')
        self.assertEqual(exc.exception.reason, 'automatic_policy_required')


@unittest.skipUnless(os.environ.get('MAPS_COST_TEST_POSTGRES_URL'), 'Disposable PostgreSQL URL not configured')
class ManualClinicGeocodePostgreSQLTest(ManualClinicGeocodeTest):
    postgres = True


if __name__ == '__main__':
    unittest.main()
