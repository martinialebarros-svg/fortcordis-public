"""Real Agenda transactions, separate test ledger, zero external Google traffic."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker
import test_agenda_maps_budget_atomicity as fixtures
from app.api.v1.endpoints import agenda, google_maps_cost_control as control_api
from app.core.security import get_current_user
from app.models.agendamento import Agendamento
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.google_maps_cost_control import COST_TABLES
from app.services import google_maps_cost_control as guard, google_maps_cost_middleware as middleware
from app.services import logistica_service as routes

class GoogleMapsAgendaCacheFirstTest(unittest.TestCase):

    def setUp(self):
        fixtures.AgendaMapsBudgetAtomicityTest.setUp(self)
        p = patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', True)
        p.start()
        self.addCleanup(p.stop)
        self.ledger = getattr(self, '_isolated_engine', None)
        if self.ledger is None:
            self.ledger = create_engine('sqlite:///' + str(Path(self.temp.name) / 'ledger.db'), connect_args={'check_same_thread': False})
        self.addCleanup(self.ledger.dispose)
        for table in COST_TABLES:
            table.create(self.ledger, checkfirst=True)
        for p in (patch.object(guard.database, 'engine', self.ledger), patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_CACHE_FIRST', True), patch.object(guard.settings, 'GOOGLE_MAPS_COST_EMERGENCY_RELEASE', False), patch.object(guard.settings, 'SECRET_KEY', 'cache-first-synthetic-secret-not-real-123456789'), patch.object(routes.settings, 'GOOGLE_ROUTES_CACHE_MAX_AGE_DAYS', 7), patch.object(middleware, '_authenticate', return_value=7), patch.object(routes, 'urlopen', side_effect=AssertionError('Real network forbidden')), patch.object(routes, '_http_get_json', side_effect=AssertionError('Unexpected fallback'))):
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(routes, '_http_post_json', return_value={'routes': [{'distanceMeters': 1000, 'duration': '600s'}]})
        self.outbound = p.start()
        self.addCleanup(p.stop)
        self.app = FastAPI()
        self.app.include_router(agenda.router, prefix='/api/v1/agenda')
        self.app.include_router(control_api.router, prefix='/api/v1/google-maps-control')
        self.app.add_middleware(middleware.GoogleMapsCostMiddleware)

        def db_dependency():
            with self.sessions() as db:
                with guard.agenda_business_session(db):
                    yield db
        self.app.dependency_overrides[agenda.get_db] = db_dependency
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, nome='Synthetic reception', tem_papel=lambda _: True)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(guard._execution.set, None)
        self.path = f'/api/v1/agenda/{self.id}'
        self.body = {'inicio': '2099-05-25T11:30:00', 'fim': '2099-05-25T12:00:00'}

    def tearDown(self):
        fixtures.AgendaMapsBudgetAtomicityTest.tearDown(self)

    def test_internal_monitor_direct_request_records_without_popup_or_confirmation(self):
        self.configure(monitor=True)
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False):
            self.assertFalse(self.preview().json()['required'])
            self.assertFalse(self.preview(paid=True).json()['required'])
            result = self.client.put(self.path, json=self.body)
            self.assertEqual(result.status_code, 200, result.text)
            status = guard.get_status()
        self.assertEqual(self.outbound.call_count, 2)
        self.assertFalse(status['agenda_confirmation_required'])
        self.assertEqual(status['consumption']['day']['calls'], 2)
        self.assertTrue(status['alerts'])  # References are zero in this fixture.
        self.assertEqual(sum(e['kind']=='internal_authorized' for e in status['history']), 1)
        self.assertFalse(any(e['kind']=='confirmed' for e in status['history']))
        with self.ledger.connect() as conn:
            rows = conn.execute(select(guard.ACTIONS)).mappings().all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['state'], 'finished')
        self.assertEqual(rows[0]['max_calls'], 4)
        self.assertEqual(rows[0]['used_calls'], 2)
        self.assertIsNone(rows[0]['token_hash'])
        self.assertEqual(len(rows[0]['fingerprint']), 64)

    def test_internal_monitor_cached_request_needs_no_ledger_or_estimate(self):
        self.seed_cache()
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False), \
                patch.object(guard, '_locked', side_effect=AssertionError('Cached request opened ledger')), \
                patch.object(middleware, '_estimate_agenda_action', side_effect=AssertionError('Cached request planned paid work')):
            result = self.client.put(self.path, json=self.body)
        self.assertEqual(result.status_code, 200, result.text)
        self.outbound.assert_not_called()

    def test_internal_monitor_cold_ledger_failure_never_sends(self):
        self.configure(monitor=True)
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False), \
                patch.object(guard, '_locked', side_effect=guard.GoogleMapsCostBlocked('ledger_unavailable', status_code=503)):
            result = self.client.put(self.path, json=self.body)
        self.assertEqual(result.status_code, 503, result.text)
        self.outbound.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)

    def test_internal_monitor_finite_scope_expires_closes_and_cannot_authorize_background(self):
        self.configure(monitor=True)
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False):
            execution = guard.claim_execution(7, None, 'PUT', self.path, None, self.body)
            token = guard.bind_execution(execution)
            try:
                for _ in range(4):
                    guard.authorize_google_call('routes_essentials')
                with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                    guard.authorize_google_call('routes_essentials')
                self.assertEqual(exc.exception.reason, 'action_limit')
                guard.finish_execution(execution)
                with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                    guard.authorize_google_call('routes_essentials')
                self.assertEqual(exc.exception.reason, 'invalid_grant')
            finally:
                guard.reset_execution(token)
            other = guard.claim_execution(7, None, 'PUT', self.path, None, self.body)
            self.assertNotEqual(execution.action_id, other.action_id)
            token = guard.bind_execution(other)
            try:
                guard.authorize_google_call('routes_essentials')
                with patch.object(guard, '_now', return_value=guard._now()+guard.EXECUTION_TTL_SECONDS+1):
                    with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                        guard.authorize_google_call('routes_essentials')
                    self.assertEqual(exc.exception.reason, 'invalid_grant')
            finally:
                guard.reset_execution(token)
                guard.finish_execution(other)
            with guard.automatic_execution('not_enabled', 'synthetic-background'):
                with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                    guard.authorize_google_call('routes_essentials')
                self.assertEqual(exc.exception.reason, 'automatic_policy_required')
            self.assertTrue(guard.create_preview(7, 'POST', '/api/v1/logistica/recalcular')['blocked'])
        self.assertEqual(guard.get_status()['consumption']['day']['calls'], 5)
        self.outbound.assert_not_called()  # Reservations only; no provider in this scope test.

    def test_internal_monitor_does_not_bypass_enforce_mode(self):
        self.configure()
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False):
            result = self.client.put(self.path, json=self.body)
            self.assertEqual(result.status_code, 409, result.text)
            self.assertEqual(result.json()['detail']['reason'], 'confirmation_required')
            self.assertTrue(self.preview(paid=True).json()['required'])
            self.assertTrue(guard.get_status()['agenda_confirmation_required'])
        self.outbound.assert_not_called()

    def test_internal_monitor_parallel_scopes_remain_finite_after_reconnect(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.configure(monitor=True)
        barrier = Barrier(2)
        def reserve(index):
            execution = guard.claim_execution(7, None, 'PUT', self.path, None, {**self.body, 'synthetic_request': index})
            token = guard.bind_execution(execution)
            try:
                barrier.wait(timeout=10)
                for _ in range(4):
                    guard.authorize_google_call('routes_essentials')
                with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                    guard.authorize_google_call('routes_essentials')
                self.assertEqual(exc.exception.reason, 'action_limit')
                guard.finish_execution(execution)
            finally:
                guard.reset_execution(token)
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(reserve, range(2)))
        self.ledger.dispose()
        with self.ledger.connect() as conn:
            rows = conn.execute(select(guard.ACTIONS)).mappings().all()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['state']=='finished' and row['used_calls']==row['max_calls']==4 for row in rows))
        self.assertEqual(guard.get_status()['consumption']['day']['calls'], 8)
        self.outbound.assert_not_called()

    def test_internal_monitor_background_task_cannot_extend_http_authorization(self):
        from fastapi import BackgroundTasks
        self.configure(monitor=True)
        app = FastAPI()
        background_denials = []
        def background():
            try:
                guard.authorize_google_call('routes_essentials')
            except guard.GoogleMapsCostBlocked as exc:
                background_denials.append(exc.reason)
        @app.post('/api/v1/agenda')
        def synthetic_scope(tasks: BackgroundTasks):
            guard.authorize_google_call('routes_essentials')
            tasks.add_task(background)
            return {'synthetic_scope_only': True}
        app.add_middleware(middleware.GoogleMapsCostMiddleware)
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False), TestClient(app) as client:
            result = client.post('/api/v1/agenda', json={})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(background_denials, ['invalid_grant'])
        self.assertEqual(guard.get_status()['consumption']['day']['calls'], 1)
        self.outbound.assert_not_called()

    def test_internal_monitor_rollout_can_restore_interactive_policy(self):
        self.configure(monitor=True)
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False):
            execution = guard.claim_execution(7, None, 'PUT', self.path, None, self.body)
        # The default/rollback setting is True again before any paid attempt.
        token = guard.bind_execution(execution)
        try:
            with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                guard.authorize_google_call('routes_essentials')
            self.assertEqual(exc.exception.reason, 'confirmation_required')
        finally:
            guard.reset_execution(token)
            guard.finish_execution(execution)
        self.assertEqual(guard.get_status()['consumption']['day']['calls'], 0)
        self.outbound.assert_not_called()

    def test_internal_monitor_real_search_uses_requested_period_and_cache(self):
        from app.models.configuracao import Configuracao
        from app.models.clinica import Clinica
        self.configure(monitor=True)
        self.seed_cached_today_with_uncached_other_days()
        with self.sessions() as db:
            db.get(Configuracao, 1).agenda_rota_regras = json.dumps({
                'base': {'address': 'Synthetic base', 'lat': -3.7, 'lng': -38.5},
                'route_policy': {'reject_clear_inefficiency': False}})
            for clinic in db.query(Clinica):
                clinic.latitude = -3.7-clinic.id/1000
            db.commit()
        body = {'clinica_id': 2, 'data': '2099-05-25', 'data_contato': '2099-05-25',
                'preferencia': {'data_inicio': '2099-05-25', 'data_fim': '2099-05-25'}}
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False), \
                patch.object(middleware, 'SessionLocal', self.sessions):
            result = self.client.post('/api/v1/agenda/assistente/ofertas', json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['panorama_ofertas']['items'])
        self.assertTrue(all(str(item['inicio'])[:10]=='2099-05-25' for item in result.json()['panorama_ofertas']['items']))
        self.assertEqual(self.outbound.call_count, 1)
        with self.ledger.connect() as conn:
            row = conn.execute(select(guard.ACTIONS)).mappings().one()
        self.assertEqual(row['max_calls'], 2)  # First departure and its possible fallback only.
        self.assertEqual(row['used_calls'], 1)
        self.assertEqual(row['state'], 'finished')

    def test_internal_monitor_planner_reuses_business_connection_under_concurrency(self):
        from concurrent.futures import ThreadPoolExecutor
        from app.db import database
        from app.services import google_maps_agenda_estimate as estimator
        from threading import Lock
        from time import sleep
        options = {'connect_args': {'check_same_thread': False}} if self.engine.dialect.name == 'sqlite' else {}
        bounded = create_engine(self.engine.url, pool_size=1, max_overflow=0, pool_timeout=3, **options)
        sessions = sessionmaker(bind=bounded, autoflush=False)
        checkouts, identities = [], set()
        lock = Lock()
        @event.listens_for(bounded, 'checkout')
        def checkout(*_):
            with lock:
                checkouts.append(1)
        def estimate(db, action, body):
            self.assertEqual(db.scalar(text('SELECT 1')), 1)
            self.assertEqual(bounded.pool.checkedout(), 1)
            with lock:
                identities.add(id(db))
            sleep(0.01)
            return {'max_calls': 2}
        app = FastAPI()
        @app.post('/api/v1/agenda/assistente/ofertas')
        def search(db=Depends(database.get_db)):
            self.assertEqual(db.scalar(text('SELECT 1')), 1)
            result = middleware._estimate_agenda_action('agenda_offers', {})
            self.assertIs(guard.current_agenda_business_session(), db)
            return result
        app.add_middleware(middleware.GoogleMapsCostMiddleware)
        try:
            with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False), \
                    patch.object(database, 'SessionLocal', sessions), \
                    patch.object(middleware, 'SessionLocal', side_effect=AssertionError('Planner opened another session')), \
                    patch.object(estimator, 'estimate_search', side_effect=estimate), TestClient(app) as client:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: client.post('/api/v1/agenda/assistente/ofertas', json={}), range(8)))
            self.assertTrue(all(r.status_code == 200 for r in results), [r.status_code for r in results])
            self.assertEqual(len(checkouts), 8)  # Exactly one business checkout per request.
            self.assertEqual(len(identities), 8)
            self.assertEqual(bounded.pool.checkedout(), 0)
            self.outbound.assert_not_called()
        finally:
            bounded.dispose()

    def test_internal_monitor_failed_estimate_never_uses_generic_cap(self):
        self.configure(monitor=True)
        body = {'clinica_id': 2, 'data': '2099-05-25', 'data_contato': '2099-05-25'}
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False), \
                patch.object(middleware, '_estimate_agenda_action', side_effect=RuntimeError('Synthetic unavailable plan')):
            result = self.client.post('/api/v1/agenda/assistente/ofertas', json=body)
        self.assertEqual(result.status_code, 503, result.text)
        self.assertEqual(result.json()['detail']['reason'], 'estimate_unavailable')
        self.outbound.assert_not_called()
        with self.ledger.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(guard.ACTIONS)).scalar(), 0)

    def test_internal_monitor_expired_prices_warn_internally_and_extras_remain_closed(self):
        self.configure(monitor=True)
        self.review_date()
        with patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', False):
            result = self.client.put(self.path, json=self.body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.outbound.call_count, 2)
        alerts = [v for v in guard.get_status()['history'] if v['reason']=='pricing_review_due']
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['kind'], 'budget_alert')
        self.assertTrue(guard.create_preview(7, 'POST', '/api/v1/logistica/recalcular')['blocked'])

    def configure(self, day_calls=20, monitor=False):
        cfg = guard.CostConfiguration.model_validate({'enabled': True, 'limits': {'action': {'calls': 4, 'estimated_brl': 1}, 'day': {'calls': day_calls, 'estimated_brl': 5}, 'month': {'calls': 100, 'estimated_brl': 20}}, 'prices_usd': {sku: '0.01' for sku in guard.SKUS}, 'fx_brl_per_usd_upper': 6, 'price_multiplier': 1, 'pricing_valid_until': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), 'opening_usage': {'day': {'calls': 0, 'estimated_brl': 0}, 'month': {'calls': 0, 'estimated_brl': 0}}, 'opening_usage_as_of': guard._periods(guard._now())[0], 'opening_usage_basis': 'synthetic_stage'})
        if monitor:
            data = cfg.model_dump(mode="json")
            data["agenda_budget_mode"] = "monitor"
            data["limits"]["action"]["estimated_brl"] = 0
            data["limits"]["day"] = data["limits"]["month"] = {"calls": 0, "estimated_brl": 0}
            data["automatic_policies"] = {"synthetic_job": {"enabled": True, "limits": {key: {"calls": 5, "estimated_brl": 1} for key in ("action", "day", "month")}, "skus": ["routes_essentials"]}}
            cfg = guard.CostConfiguration.model_validate(data)
        return guard.update_configuration(7, cfg, 0)

    def seed_cache(self, age_days=0, source='google_routes_api'):
        with self.sessions() as db:
            for a, b in ((1, 2), (2, 3)):
                for profile in ('comercial', 'plantao'):
                    db.add(ClinicaDeslocamento(origem_clinica_id=a, destino_clinica_id=b, perfil=profile, distancia_km=1, duracao_min=10, fonte=source, updated_at=datetime.utcnow() - timedelta(days=age_days)))
            db.commit()

    def test_proposed_monitor_config_keeps_reception_above_references_and_extras_closed(self):
        proposal = Path(__file__).resolve().parents[2] / 'docs/specs/google-maps-enforced-budget/proposed-monitor-config.json'
        data = json.loads(proposal.read_text())
        self.assertFalse(data['enabled'])
        data.update(enabled=True, opening_usage_as_of=guard._periods(guard._now())[0],
                    opening_usage_basis='synthetic_stage',
                    pricing_valid_until=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    opening_usage={'day': {'calls': 651, 'estimated_brl': 26},
                                   'month': {'calls': 13001, 'estimated_brl': 501}})
        guard.update_configuration(7, guard.CostConfiguration.model_validate(data), 0)
        quote = self.preview(paid=True).json()
        self.assertFalse(quote['blocked'])
        self.assertFalse(quote['financial_limit_enforced'])
        self.assertEqual(quote['max_calls'], 64)
        self.assertEqual(quote['estimated_cost_max_brl'], 4.608)
        self.assertTrue(quote['alerts'])
        self.outbound.assert_not_called()  # Displaying/cancelling the quote is unpaid.
        token = self.client.post('/api/v1/google-maps-control/confirm', json={'quote_id': quote['quote_id']}).json()['token']
        result = self.client.put(self.path, json=self.body, headers={'X-Google-Maps-Action': token})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.outbound.call_count, 2)
        replay = self.client.put(self.path, json=self.body, headers={'X-Google-Maps-Action': token})
        self.assertEqual(replay.status_code, 409)
        for path in ('/api/v1/logistica/recalcular', '/api/v1/tutores/geocode-endereco'):
            extra = self.client.post('/api/v1/google-maps-control/preview', json={'method': 'POST', 'path': path, 'body': {}}).json()
            self.assertTrue(extra['blocked'])
        with self.assertRaises(guard.GoogleMapsCostBlocked) as denied:
            with guard.automatic_action('whatsapp_agenda', 'synthetic-proposal-job'):
                guard.authorize_google_call('routes_essentials')
        self.assertEqual(denied.exception.reason, 'automatic_policy_required')
        self.assertEqual(self.outbound.call_count, 2)

    def preview(self, paid=False):
        return self.client.post('/api/v1/google-maps-control/preview', json={'method': 'PUT', 'path': self.path, 'body': self.body, 'paid_call_required': paid})

    def test_local_preview_and_cached_booking_work_with_unavailable_ledger(self):
        self.seed_cache()
        broken = Mock()
        broken.connect.side_effect = AssertionError('Local Agenda accessed ledger')
        with patch.object(guard.database, 'engine', broken):
            preview = self.preview()
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()['operation_mode'], 'cache_first')
            self.assertFalse(preview.json()['required'])
            self.assertFalse(preview.json()['paid_calls_allowed'])
            response = self.client.put(self.path, json=self.body)
        self.assertEqual(response.status_code, 200, response.text)
        self.outbound.assert_not_called()
        broken.connect.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(agenda._to_local_naive(db.get(Agendamento, self.id).inicio), datetime(2099, 5, 25, 11, 30))

    def test_unpaid_probe_rolls_back_then_one_confirmed_execution_succeeds(self):
        self.configure()
        probe = self.client.put(self.path, json=self.body)
        self.assertEqual(probe.status_code, 409, probe.text)
        self.assertEqual(probe.json()['detail']['reason'], 'confirmation_required')
        self.assertTrue(probe.json()['detail']['can_retry_with_confirmation'])
        self.outbound.assert_not_called()
        agenda._notificar_agenda_update.assert_not_called()
        agenda.registrar_auditoria.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 0)
        quote = self.preview(paid=True).json()
        self.assertTrue(quote['required'])
        token = self.client.post('/api/v1/google-maps-control/confirm', json={'quote_id': quote['quote_id']}).json()['token']
        result = self.client.put(self.path, json=self.body, headers={'X-Google-Maps-Action': token})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.outbound.call_count, 2)
        replay = self.client.put(self.path, json=self.body, headers={'X-Google-Maps-Action': token})
        self.assertEqual(replay.status_code, 409, replay.text)
        self.assertEqual(replay.json()['detail']['reason'], 'invalid_grant')
        self.assertEqual(self.outbound.call_count, 2)
        self.assertEqual(guard.get_status()['consumption']['day']['calls'], 2)

    def test_cache_continues_after_daily_budget_exhaustion(self):
        self.configure(day_calls=0)
        self.seed_cache()
        self.assertTrue(self.preview(paid=True).json()['blocked'])
        r = self.client.put(self.path, json=self.body)
        self.assertEqual(r.status_code, 200, r.text)
        self.outbound.assert_not_called()

    def test_missing_policy_only_blocks_lookup_not_normal_form_validation(self):
        r = self.client.post('/api/v1/agenda', json={})
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.put(self.path, json=self.body)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()['detail']['reason'], 'unconfigured')
        self.outbound.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)

    def test_cold_cache_and_unavailable_ledger_never_send_or_commit(self):
        broken = Mock()
        broken.connect.side_effect = RuntimeError('private connection details')
        with patch.object(guard.database, 'engine', broken):
            r = self.client.put(self.path, json=self.body)
        self.assertEqual(r.status_code, 503, r.text)
        self.assertEqual(r.json()['detail']['reason'], 'ledger_unavailable')
        self.assertNotIn('private connection', r.text)
        self.outbound.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)

    def test_expired_or_heuristic_cache_requires_consent_without_renewal(self):
        self.configure()
        for source, age in (('google_routes_api', 8), ('heuristica_haversine', 0)):
            with self.subTest(source=source):
                with self.sessions() as db:
                    db.query(ClinicaDeslocamento).delete()
                    db.commit()
                self.seed_cache(age_days=age, source=source)
                # Legacy expiry remains an explicit opt-in, never the default.
                with patch.object(routes.settings, 'GOOGLE_ROUTES_CACHE_EXPIRE_BY_AGE', True):
                    r = self.client.put(self.path, json=self.body)
                self.assertEqual(r.status_code, 409, r.text)
                self.assertEqual(r.json()['detail']['reason'], 'confirmation_required')
                with self.sessions() as db:
                    self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)
        self.outbound.assert_not_called()

    def test_old_cached_routes_complete_agenda_without_finance_or_google(self):
        self.seed_cache(age_days=3650)
        with self.sessions() as db:
            before = {row.id: row.updated_at for row in db.query(ClinicaDeslocamento).all()}
        broken = Mock()
        broken.connect.side_effect = RuntimeError('Ledger must not be needed for cached routes')
        with patch.object(guard.database, 'engine', broken):
            response = self.client.put(self.path, json=self.body)
        self.assertEqual(response.status_code, 200, response.text)
        self.outbound.assert_not_called()
        with self.sessions() as db:
            start = db.get(Agendamento, self.id).inicio
            self.assertEqual((start.astimezone(agenda.LOCAL_TZ) if start.tzinfo else start).hour, 11)
            self.assertEqual({row.id: row.updated_at for row in db.query(ClinicaDeslocamento).all()}, before)

    def test_old_cache_with_new_geocode_still_requires_consent_and_never_commits(self):
        from app.models.clinica import Clinica
        self.seed_cache(age_days=3650)
        self.configure()
        with self.sessions() as db:
            db.get(Clinica, 2).geocode_at = datetime.utcnow()
            db.commit()
        response = self.client.put(self.path, json=self.body)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['reason'], 'confirmation_required')
        self.outbound.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)

    def test_old_heuristic_does_not_become_valid_by_disabling_age_expiry(self):
        self.seed_cache(age_days=3650, source='heuristica_haversine')
        self.configure()
        response = self.client.put(self.path, json=self.body)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['reason'], 'confirmation_required')
        self.outbound.assert_not_called()

    def test_missing_key_never_invents_new_route(self):
        with patch.object(routes.settings, 'GOOGLE_MAPS_API_KEY', ''):
            r = self.client.put(self.path, json=self.body)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()['detail']['reason'], 'route_unavailable')
        self.outbound.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 0)

    def test_authentication_and_background_boundaries_preserved(self):
        with patch.object(middleware, '_authenticate', side_effect=HTTPException(401, 'Unauthorized')):
            self.assertEqual(self.client.put(self.path, json=self.body).status_code, 401)
        self.configure()
        execution = guard.claim_execution(7, None, 'PUT', self.path, None, self.body)
        guard.finish_execution(execution)
        context = guard.bind_execution(execution)
        try:
            with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                guard.authorize_google_call('routes_essentials')
            self.assertEqual(exc.exception.reason, 'invalid_grant')
        finally:
            guard.reset_execution(context)
        self.outbound.assert_not_called()

    def test_create_booking_with_cache_succeeds_without_financial_policy(self):
        self.seed_cache()
        with self.sessions() as db:
            source = db.get(Agendamento, self.id)
            payload = {'paciente_id': source.paciente_id, 'tutor_id': source.tutor_id, 'clinica_id': source.clinica_id, 'servico_id': source.servico_id, 'inicio': '2099-05-25T12:30:00', 'fim': '2099-05-25T13:00:00', 'status': 'Agendado'}
        broken = Mock()
        broken.connect.side_effect = AssertionError('Cached create accessed ledger')
        with patch.object(guard.database, 'engine', broken):
            response = self.client.post('/api/v1/agenda', json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.outbound.assert_not_called()
        broken.connect.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.query(Agendamento).count(), 4)

    def test_new_booking_stops_before_google_and_requires_single_use_consent(self):
        self.configure()
        with self.sessions() as db:
            row = db.get(Agendamento, self.id)
            payload = {"paciente_id": row.paciente_id, "tutor_id": row.tutor_id, "clinica_id": row.clinica_id,
                       "servico_id": row.servico_id, "inicio": "2099-05-25T12:30:00", "fim": "2099-05-25T13:00:00", "status": "Agendado"}
        path = "/api/v1/agenda"
        first = self.client.post(path, json=payload)
        self.assertEqual(first.status_code, 409, first.text)
        self.assertTrue(first.json()["detail"]["can_retry_with_confirmation"])
        self.outbound.assert_not_called()
        agenda._notificar_agenda_update.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.query(Agendamento).count(), 3)
        quoted = self.client.post("/api/v1/google-maps-control/preview", json={"method": "POST", "path": path, "body": payload, "paid_call_required": True}).json()
        token = self.client.post("/api/v1/google-maps-control/confirm", json={"quote_id": quoted["quote_id"]}).json()["token"]
        created = self.client.post(path, json=payload, headers={"X-Google-Maps-Action": token})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(self.outbound.call_count, 1)
        replay = self.client.post(path, json=payload, headers={"X-Google-Maps-Action": token})
        self.assertEqual(replay.status_code, 409, replay.text)
        with self.sessions() as db:
            self.assertEqual(db.query(Agendamento).count(), 4)

    def test_monitor_allows_new_booking_above_references_but_keeps_consent_and_replay_guard(self):
        original = self.configure
        self.configure = lambda: original(monitor=True)
        self.test_new_booking_stops_before_google_and_requires_single_use_consent()
        status = guard.get_status()
        self.assertEqual(status["agenda_budget_mode"], "monitor")
        self.assertEqual(status["consumption"]["day"], {"calls": 1, "estimated_brl": 0.06})
        self.assertEqual(status["remaining"]["day"], {"calls": 0, "estimated_brl": 0})
        self.assertEqual(len([event for event in status["history"] if event["kind"] == "budget_alert"]), 2)
        self.assertEqual(len(status["alerts"]), 2)

    def test_monitor_quote_and_cancel_do_not_send_and_extras_automatics_still_stop(self):
        self.configure(monitor=True)
        q = self.preview(paid=True).json()
        self.assertFalse(q["blocked"])
        self.assertEqual(q["budget_policy"], "agenda_monitor")
        self.assertEqual(q["max_calls"], 4)
        self.assertEqual(q["estimated_cost_max_brl"], 0.24)
        self.assertEqual(len(q["alerts"]), 2)
        # Discard/cancel the quote. Neither a provider reservation nor send.
        self.assertEqual(guard.get_status()["consumption"]["day"]["calls"], 0)
        self.outbound.assert_not_called()
        extras = guard.create_preview(7, "POST", "/api/v1/logistica/recalcular")
        self.assertTrue(extras["blocked"])
        self.assertEqual(extras["budget_policy"], "enforced")
        # This fixture has a zero per-action cost cap; daily usage is still zero.
        self.assertEqual(extras["reason"], "action_limit")
        data = guard.get_status()["config"]
        data["limits"]["action"]["estimated_brl"] = 1
        guard.update_configuration(7, guard.CostConfiguration.model_validate(data), 1)
        with guard.automatic_execution("synthetic_job", "one-stable-run"):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as caught:
                guard.authorize_google_call("routes_essentials")
            self.assertEqual(caught.exception.reason, "day_limit")
        with guard.automatic_execution("no_policy", "another-run"):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as caught:
                guard.authorize_google_call("routes_essentials")
            self.assertEqual(caught.exception.reason, "automatic_policy_required")
        self.outbound.assert_not_called()

    def test_monitor_parallel_grants_remain_finite_and_durable(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.configure(monitor=True)
        executions = []
        for i in range(2):
            q = self.preview(paid=True).json()
            token = guard.confirm_preview(7, q["quote_id"])["token"]
            executions.append(guard.claim_execution(7, token, "PUT", self.path, None, self.body))
        barrier = Barrier(2)
        def reserve(execution):
            context = guard.bind_execution(execution)
            try:
                barrier.wait(timeout=10)
                for _ in range(4): guard.authorize_google_call("routes_essentials")
                with self.assertRaises(guard.GoogleMapsCostBlocked) as caught:
                    guard.authorize_google_call("routes_essentials")
                self.assertEqual(caught.exception.reason, "action_limit")
                guard.finish_execution(execution)
            finally: guard.reset_execution(context)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(reserve, executions))
        self.ledger.dispose() # Reopen connections: the ledger survives restart.
        status = guard.get_status()
        self.assertEqual(status["consumption"]["day"], {"calls": 8, "estimated_brl": 0.48})
        self.assertEqual(len([e for e in status["history"] if e["kind"] == "budget_alert"]), 4)
        self.outbound.assert_not_called()

    def test_agenda_tutor_geocode_uses_one_confirmed_unit_above_references(self):
        from app.services import geocoding_service
        self.configure(monitor=True)
        path = "/api/v1/agenda/geocode-endereco-tutor"
        body = {"endereco": "Synthetic address", "numero": "1", "cidade": "Synthetic city", "estado": "CE"}
        response = {"status": "OK", "results": [{"geometry": {"location": {"lat": -3.7, "lng": -38.5}}, "formatted_address": "Synthetic address", "place_id": "synthetic"}]}
        with patch.object(geocoding_service, "_http_get_json", return_value=response) as transport:
            empty = self.client.post(path, json={})
            self.assertEqual(empty.status_code, 422, empty.text)
            transport.assert_not_called()
            probe = self.client.post(path, json=body)
            self.assertEqual(probe.status_code, 409, probe.text)
            self.assertTrue(probe.json()["detail"]["can_retry_with_confirmation"])
            transport.assert_not_called()
            quote = self.client.post("/api/v1/google-maps-control/preview", json={"method": "POST", "path": path, "body": body, "paid_call_required": True}).json()
            self.assertFalse(quote["blocked"])
            self.assertEqual(quote["max_calls"], 1)
            self.assertEqual(quote["services"], ["geocoding"])
            self.assertEqual(quote["budget_policy"], "agenda_monitor")
            # Cancel/discard without confirming: no provider request.
            transport.assert_not_called()
            token = self.client.post("/api/v1/google-maps-control/confirm", json={"quote_id": quote["quote_id"]}).json()["token"]
            result = self.client.post(path, json=body, headers={"X-Google-Maps-Action": token})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["item"]["latitude"], -3.7)
            self.assertEqual(transport.call_count, 1)
            replay = self.client.post(path, json=body, headers={"X-Google-Maps-Action": token})
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(transport.call_count, 1)
        self.assertTrue(guard.create_preview(7, "POST", "/api/v1/tutores/geocode-endereco", body=body)["blocked"])
        self.assertEqual(guard.get_status()["consumption"]["day"]["calls"], 1)

    def review_date(self, seconds=-5):
        status = guard.get_status()
        data = status["config"]
        data["pricing_valid_until"] = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        return guard.update_configuration(7, guard.CostConfiguration.model_validate(data), status["revision"])

    def test_expired_monitor_prices_warn_and_complete_booking_without_freeing_extras(self):
        self.configure(monitor=True)
        status = self.review_date()
        self.assertFalse(status["blocked"])
        self.assertTrue(status["paid_calls_allowed"])
        self.assertTrue(status["pricing_review_due"])
        self.assertIn(guard.REASONS["pricing_review_due"], status["alerts"])
        unpaid = self.client.put(self.path, json=self.body)
        self.assertEqual(unpaid.status_code, 409, unpaid.text)
        self.assertTrue(unpaid.json()["detail"]["can_retry_with_confirmation"])
        self.outbound.assert_not_called()
        quote = self.preview(paid=True).json()
        self.assertFalse(quote["blocked"])
        self.assertTrue(quote["pricing_review_due"])
        self.assertEqual(quote["max_calls"], 4)
        self.assertEqual(quote["estimated_cost_max_brl"], 0.24)
        self.assertIn(guard.REASONS["pricing_review_due"], quote["alerts"])
        self.outbound.assert_not_called()  # Cancelling the warning sends nothing.
        confirmed = self.client.post('/api/v1/google-maps-control/confirm', json={'quote_id': quote['quote_id']})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        token = confirmed.json()['token']
        result = self.client.put(self.path, json=self.body, headers={'X-Google-Maps-Action': token})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.outbound.call_count, 2)
        self.assertEqual(self.client.put(self.path, json=self.body, headers={'X-Google-Maps-Action': token}).status_code, 409)
        events = [event for event in guard.get_status()['history'] if event['reason']=='pricing_review_due']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'budget_alert')
        self.assertEqual(events[0]['estimated_brl'], 0)
        for path in ('/api/v1/logistica/recalcular', '/api/v1/tutores/geocode-endereco'):
            extra = guard.create_preview(7, 'POST', path)
            self.assertTrue(extra['blocked'])
            self.assertEqual(extra['reason'], 'pricing_expired')
        with guard.automatic_execution('synthetic_job', 'expired-explicit-policy'):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as denied:
                guard.authorize_google_call('routes_essentials')
            self.assertEqual(denied.exception.reason, 'pricing_expired')

    def test_monitor_quote_survives_review_date_but_not_its_own_expiry_or_cap(self):
        self.configure(monitor=True)
        self.review_date(seconds=3)
        quote = self.preview(paid=True).json()
        now = guard._now()
        with patch.object(guard, '_now', return_value=now+6):
            token = guard.confirm_preview(7, quote['quote_id'])['token']
            execution = guard.claim_execution(7, token, 'PUT', self.path, None, self.body)
            context = guard.bind_execution(execution)
            try:
                for _ in range(4): guard.authorize_google_call('routes_essentials')
                with self.assertRaises(guard.GoogleMapsCostBlocked) as limit:
                    guard.authorize_google_call('routes_essentials')
                self.assertEqual(limit.exception.reason, 'action_limit')
            finally:
                guard.reset_execution(context)
                guard.finish_execution(execution)
            with self.assertRaises(guard.GoogleMapsCostBlocked):
                guard.claim_execution(7, token, 'PUT', self.path, None, self.body)
        self.outbound.assert_not_called()
        fresh = self.preview(paid=True).json()
        with patch.object(guard, '_now', return_value=now+guard.QUOTE_TTL_SECONDS+10):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as expired:
                guard.confirm_preview(7, fresh['quote_id'])
            self.assertEqual(expired.exception.reason, 'invalid_grant')

    def test_expired_monitor_prices_keep_tutor_geocode_single_use(self):
        configure = self.configure
        def expired_configure(*args, **kwargs):
            configure(*args, **kwargs)
            return self.review_date()
        self.configure = expired_configure
        self.test_agenda_tutor_geocode_uses_one_confirmed_unit_above_references()

    def test_expired_monitor_parallel_confirmations_remain_finite(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.configure(monitor=True)
        self.review_date()
        executions=[]
        for _ in range(2):
            quote=self.preview(paid=True).json()
            token=guard.confirm_preview(7,quote['quote_id'])['token']
            executions.append(guard.claim_execution(7,token,'PUT',self.path,None,self.body))
        barrier=Barrier(2)
        def reserve(execution):
            context=guard.bind_execution(execution)
            try:
                barrier.wait(timeout=10)
                for _ in range(4):guard.authorize_google_call('routes_essentials')
                with self.assertRaises(guard.GoogleMapsCostBlocked) as denied:guard.authorize_google_call('routes_essentials')
                self.assertEqual(denied.exception.reason,'action_limit')
            finally:
                guard.reset_execution(context)
                guard.finish_execution(execution)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(reserve,executions))
        self.ledger.dispose()
        status=guard.get_status()
        self.assertEqual(status['consumption']['day']['calls'],8)
        self.assertEqual(len([event for event in status['history'] if event['reason']=='pricing_review_due']),2)
        self.outbound.assert_not_called()

    def test_expired_monitor_date_does_not_override_admin_suspension(self):
        self.configure(monitor=True)
        status=self.review_date()
        data=status['config'];data['enabled']=False
        guard.update_configuration(7,guard.CostConfiguration.model_validate(data),status['revision'])
        quote=self.preview(paid=True).json()
        self.assertTrue(quote['blocked'])
        self.assertEqual(quote['reason'],'disabled')
        self.outbound.assert_not_called()

    def search_preview(self, body=None):
        return self.client.post('/api/v1/google-maps-control/preview', json={
            'method': 'POST', 'path': '/api/v1/agenda/assistente/ofertas',
            'body': body or {'clinica_id': 2, 'data': '2099-05-25', 'data_contato': '2099-05-25'},
            'paid_call_required': True,
        })

    def test_search_quote_uses_missing_matrix_directions_instead_of_generic_cap(self):
        self.configure(monitor=True)
        self.seed_cache(age_days=3650)
        with guard._locked() as conn:
            cfg, _ = guard._configuration(conn)
            data = cfg.model_dump(mode='json')
            data['limits']['action']['calls'] = 4096
            data['limits']['day'] = {'calls': 650, 'estimated_brl': 25}
            data['limits']['month'] = {'calls': 13000, 'estimated_brl': 500}
            data['action_call_caps'] = {'agenda_offers': 4096}
        guard.update_configuration(7, guard.CostConfiguration.model_validate(data), 1)
        response = self.search_preview()
        self.assertEqual(response.status_code, 200, response.text)
        quote = response.json()
        self.assertEqual(quote['route_estimate']['cached_directions'], 2)
        self.assertEqual(quote['max_calls'], 6)  # Three missing directions, Routes + fallback.
        self.assertEqual(quote['estimated_cost_max_brl'], 0.36)
        self.assertEqual(quote['alerts'], [])
        self.assertEqual(quote['services'], ['routes_essentials', 'distance_matrix_essentials'])
        self.outbound.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.query(Agendamento).count(), 3)
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 4)

    def test_complete_search_matrix_needs_no_paid_grant_or_refresh(self):
        self.configure(monitor=True)
        with self.sessions() as db:
            for a in (1, 2, 3):
                for b in (1, 2, 3):
                    if a != b:
                        db.add(ClinicaDeslocamento(origem_clinica_id=a, destino_clinica_id=b,
                            perfil='comercial', distancia_km=1, duracao_min=10,
                            fonte='google_routes_api', updated_at=datetime.utcnow()-timedelta(days=3650)))
            db.commit()
        broken = Mock()
        broken.connect.side_effect = AssertionError('Cached plan accessed financial ledger')
        with patch.object(guard.database, 'engine', broken):
            q = self.search_preview().json()
        broken.connect.assert_not_called()
        self.assertEqual(q['max_calls'], 0)
        self.assertFalse(q['required'])
        self.assertFalse(q['paid_calls_allowed'])
        self.assertFalse(q.get('quote_id'))
        self.assertEqual(q['route_estimate']['missing_directions'], 0)
        self.outbound.assert_not_called()

    def test_search_geocoding_fallback_and_readonly_plan_are_explicit(self):
        from app.models.configuracao import Configuracao
        from sqlalchemy import event
        self.configure(monitor=True)
        with self.sessions() as db:
            db.get(Configuracao, 1).agenda_rota_regras = json.dumps({'base': {'address': 'Synthetic base'}})
            for a in (1, 2, 3):
                for b in (1, 2, 3):
                    if a != b:
                        db.add(ClinicaDeslocamento(origem_clinica_id=a, destino_clinica_id=b,
                            perfil='comercial', distancia_km=1, duracao_min=10, fonte='google_routes_api', updated_at=datetime.utcnow()))
            db.commit()
        mutations = []
        def observe(conn, cursor, statement, parameters, context, executemany):
            sql = statement.lower().strip()
            if sql.startswith(('insert ', 'update ', 'delete ')) and any(name in sql for name in ('agendamentos', 'clinica_deslocamentos', 'configuracoes')):
                mutations.append(sql.split()[0])
        event.listen(self.engine, 'before_cursor_execute', observe)
        try:
            q = self.search_preview().json()
        finally:
            event.remove(self.engine, 'before_cursor_execute', observe)
        self.assertEqual(q['max_calls'], 3)  # One base route + fallback + geocoding.
        self.assertEqual(q['route_estimate']['geocoding_units'], 1)
        self.assertIn('geocoding', q['services'])
        self.assertEqual(mutations, [])
        self.outbound.assert_not_called()

    def test_offer_validation_plan_uses_fortaleza_date_at_utc_boundary(self):
        from app.services.google_maps_agenda_estimate import estimate_search
        with self.sessions() as db:
            plan = estimate_search(db, 'agenda_validate_offer', {'clinica_id': 2, 'inicio': '2099-05-26T01:30:00+00:00'})
        self.assertEqual(plan['search_start'], '2099-05-25')
        self.assertEqual(plan['search_end'], '2099-05-25')
        self.assertGreater(plan['missing_directions'], 0)

    def seed_cached_today_with_uncached_other_days(self):
        from app.models.clinica import Clinica
        with self.sessions() as db:
            template = db.get(Agendamento, self.id)
            for a in (1, 2, 3):
                for b in (1, 2, 3):
                    if a != b:
                        db.add(ClinicaDeslocamento(origem_clinica_id=a, destino_clinica_id=b,
                            perfil='comercial', distancia_km=1, duracao_min=10,
                            fonte='google_routes_api', updated_at=datetime.utcnow()-timedelta(days=3650)))
            for cid, day in ((4, 24), (5, 27)):
                db.add(Clinica(id=cid, nome=f'Outside-period synthetic {cid}', ativo=True,
                    latitude=-3.7-cid/1000, longitude=-38.5, place_id=f'synthetic-{cid}'))
                start = datetime(2099, 5, day, 10, tzinfo=agenda.LOCAL_TZ)
                db.add(Agendamento(clinica_id=cid, tutor_id=template.tutor_id,
                    paciente_id=template.paciente_id, servico_id=template.servico_id,
                    inicio=start, fim=start+timedelta(minutes=30), data=f'2099-05-{day}',
                    hora='10:00', status='Agendado'))
            db.commit()

    def test_explicit_today_ignores_other_days_and_uses_cache_without_paid_ledger(self):
        self.seed_cached_today_with_uncached_other_days()
        body = {'clinica_id': 2, 'data': '2099-05-25', 'data_contato': '2099-05-25',
            'preferencia': {'data_inicio': '2099-05-25', 'data_fim': '2099-05-25'}}
        broken = Mock()
        broken.connect.side_effect = AssertionError('Cached requested period accessed paid ledger')
        with patch.object(guard.database, 'engine', broken):
            response = self.search_preview(body)
        self.assertEqual(response.status_code, 200, response.text)
        quote = response.json()
        self.assertFalse(quote['required'])
        self.assertEqual(quote['max_calls'], 0)
        self.assertEqual(quote['route_estimate']['search_start'], '2099-05-25')
        self.assertEqual(quote['route_estimate']['search_end'], '2099-05-25')
        self.assertEqual(quote['route_estimate']['missing_directions'], 0)
        self.assertGreater(quote['route_estimate']['cached_directions'], 0)
        broken.connect.assert_not_called()
        self.outbound.assert_not_called()

    def test_explicit_interval_overrides_reference_contact_and_policy_dates(self):
        from app.services.google_maps_agenda_estimate import estimate_search
        self.seed_cached_today_with_uncached_other_days()
        for action in ('agenda_offers', 'agenda_proximity'):
            with self.subTest(action=action), self.sessions() as db:
                plan = estimate_search(db, action, {'clinica_id': 2,
                    'data': '2099-05-01', 'data_contato': '2099-05-01',
                    'janela_dias_proximidade': 30,
                    'preferencia': {'data_inicio': '2099-05-25', 'data_fim': '2099-05-26'}})
            self.assertEqual((plan['search_start'], plan['search_end']), ('2099-05-25', '2099-05-26'))
            self.assertEqual(plan['missing_directions'], 0)
            self.assertEqual(plan['max_calls'], 0)
        self.outbound.assert_not_called()

    def test_requested_period_still_counts_missing_routes_inside_interval(self):
        from app.services.google_maps_agenda_estimate import estimate_search
        self.seed_cached_today_with_uncached_other_days()
        with self.sessions() as db:
            plan = estimate_search(db, 'agenda_offers', {'clinica_id': 2,
                'data': '2099-05-25', 'data_contato': '2099-05-25',
                'preferencia': {'data_inicio': '2099-05-25', 'data_fim': '2099-05-27'}})
        self.assertEqual(plan['search_start'], '2099-05-25')
        self.assertEqual(plan['search_end'], '2099-05-27')
        self.assertEqual(plan['missing_directions'], 2)  # Target <-> new clinic on the 27th.
        self.assertEqual(plan['max_calls'], 4)
        self.outbound.assert_not_called()

    def test_explicit_today_real_offers_never_pay_for_outside_policy_anchors(self):
        from app.models.configuracao import Configuracao
        from app.models.clinica import Clinica
        self.configure(monitor=True)
        self.seed_cached_today_with_uncached_other_days()
        with self.sessions() as db:
            db.get(Configuracao, 1).agenda_rota_regras = json.dumps({
                'base': {'address': 'Synthetic base', 'lat': -3.7, 'lng': -38.5},
                'route_policy': {'reject_clear_inefficiency': False}})
            for clinic in db.query(Clinica):
                clinic.latitude = -3.7-clinic.id/1000
            db.commit()
        body = {'clinica_id': 2, 'data': '2099-05-25', 'data_contato': '2099-05-25',
            'preferencia': {'data_inicio': '2099-05-25', 'data_fim': '2099-05-25'}}
        path = '/api/v1/agenda/assistente/ofertas'
        unpaid = self.client.post(path, json=body)
        self.assertEqual(unpaid.status_code, 409, unpaid.text)
        self.outbound.assert_not_called()
        quote = self.search_preview(body).json()
        self.assertEqual(quote['max_calls'], 2)  # Only first departure + its possible fallback.
        self.assertEqual(quote['route_estimate']['missing_directions'], 0)
        self.outbound.assert_not_called()  # Cancelling at this point costs nothing.
        token = self.client.post('/api/v1/google-maps-control/confirm',
            json={'quote_id': quote['quote_id']}).json()['token']
        with patch.object(agenda, '_existe_ancora_proxima_no_dia', wraps=agenda._existe_ancora_proxima_no_dia) as anchors:
            result = self.client.post(path, json=body, headers={'X-Google-Maps-Action': token})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['panorama_ofertas']['items'])
        self.assertTrue(all(call.kwargs['data_iso']=='2099-05-25' for call in anchors.call_args_list))
        self.assertEqual(self.outbound.call_count, 1)
        for item in result.json()['panorama_ofertas']['items']:
            self.assertEqual(str(item['inicio'])[:10], '2099-05-25')
        count = self.outbound.call_count
        self.assertEqual(self.client.post(path, json=body, headers={'X-Google-Maps-Action': token}).status_code, 409)
        self.assertEqual(self.outbound.call_count, count)
        with self.sessions() as db:
            self.assertEqual(db.query(Agendamento).count(), 5)

    def test_search_confirmation_is_finite_and_extras_stay_closed(self):
        self.configure(monitor=True)
        response = self.search_preview()
        self.assertEqual(response.status_code, 200, response.text)
        q = response.json()
        self.outbound.assert_not_called()  # Quoting/cancelling never pays.
        confirmation = self.client.post('/api/v1/google-maps-control/confirm', json={'quote_id': q['quote_id']}).json()
        body = {'clinica_id': 2, 'data': '2099-05-25', 'data_contato': '2099-05-25'}
        execution = guard.claim_execution(7, confirmation['token'], 'POST', '/api/v1/agenda/assistente/ofertas', None, body)
        context = guard.bind_execution(execution)
        try:
            for _ in range(q['max_calls']):
                guard.authorize_google_call('routes_essentials')
            with self.assertRaises(guard.GoogleMapsCostBlocked) as denied:
                guard.authorize_google_call('routes_essentials')
            self.assertEqual(denied.exception.reason, 'action_limit')
        finally:
            guard.reset_execution(context)
            guard.finish_execution(execution)
        with self.assertRaises(guard.GoogleMapsCostBlocked):
            guard.claim_execution(7, confirmation['token'], 'POST', '/api/v1/agenda/assistente/ofertas', None, body)
        self.assertTrue(guard.create_preview(7, 'POST', '/api/v1/logistica/recalcular')['blocked'])
        with guard.automatic_execution('not_enabled', 'one-job'):
            with self.assertRaises(guard.GoogleMapsCostBlocked):
                guard.authorize_google_call('routes_essentials')
        self.outbound.assert_not_called()

    def test_search_plan_unavailable_never_uses_generic_quote_or_google(self):
        self.configure(monitor=True)
        with patch('app.services.google_maps_agenda_estimate.estimate_search', side_effect=RuntimeError('private detail')):
            response = self.search_preview()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()['detail']['reason'], 'estimate_unavailable')
        self.assertNotIn('private detail', response.text)
        self.outbound.assert_not_called()

    def test_real_offer_search_respects_calculated_envelope_and_reuses_route_results(self):
        from app.models.configuracao import Configuracao
        from app.models.clinica import Clinica
        self.configure(monitor=True)
        with guard._locked() as conn:
            cfg, _ = guard._configuration(conn)
            data = cfg.model_dump(mode='json')
        data['limits']['action']['calls'] = 4096
        guard.update_configuration(7, guard.CostConfiguration.model_validate(data), 1)
        with self.sessions() as db:
            db.get(Configuracao, 1).agenda_rota_regras = json.dumps({
                'base': {'address': 'Synthetic base', 'lat': -3.6, 'lng': -38.4},
                'route_policy': {'reject_clear_inefficiency': False},
            })
            for row in db.query(Clinica):
                row.latitude = -3.7 - row.id / 100
            db.commit()
        body = {'clinica_id': 2, 'data': '2099-05-25', 'data_contato': '2099-05-25'}
        path = '/api/v1/agenda/assistente/ofertas'
        unpaid = self.client.post(path, json=body)
        self.assertEqual(unpaid.status_code, 409, unpaid.text)
        self.outbound.assert_not_called()
        q = self.search_preview(body).json()
        self.assertEqual(q['max_calls'], 12)
        self.assertEqual(q['route_estimate']['first_departure_routes'], 1)
        token = self.client.post('/api/v1/google-maps-control/confirm', json={'quote_id': q['quote_id']}).json()['token']
        result = self.client.post(path, json=body, headers={'X-Google-Maps-Action': token})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['panorama_ofertas']['items'])
        self.assertGreater(self.outbound.call_count, 0)
        self.assertLessEqual(self.outbound.call_count, q['max_calls'])
        payloads = [json.dumps(call.args[1], sort_keys=True) for call in self.outbound.call_args_list]
        self.assertEqual(len(payloads), len(set(payloads)), 'No duplicate paid route between slots/days/profiles')
        count = self.outbound.call_count
        replay = self.client.post(path, json=body, headers={'X-Google-Maps-Action': token})
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(self.outbound.call_count, count)
        with self.sessions() as db:
            self.assertEqual(db.query(Agendamento).count(), 3)

    def test_reference_alerts_distinguish_actual_from_potential_overage(self):
        self.configure()
        with guard._locked() as conn:
            cfg, _ = guard._configuration(conn)
        usage = {'day': {'calls': 1, 'cost': 0}, 'month': {'calls': 1, 'cost': 0}}
        self.assertEqual(guard._reference_alerts(cfg, usage, 1, 1), [])
        self.assertEqual(guard._reference_alerts(cfg, usage, 20, 1), ['day_reference_may_exceed'])
        usage['day']['calls'] = 20
        self.assertEqual(guard._reference_alerts(cfg, usage, 20, 1), ['day_reference_exceeded'])
        usage['month']['cost'] = guard._micros(20)
        self.assertEqual(guard._reference_alerts(cfg, usage, 0, 0), ['day_reference_exceeded', 'month_reference_exceeded'])

    def test_cache_only_rejects_monitor_exception(self):
        with self.assertRaises(ValueError):
            guard.CostConfiguration.model_validate({"operation_mode": "cache_only", "agenda_budget_mode": "monitor", "enabled": True, "limits": {p: {"calls": 0, "estimated_brl": 0} for p in ("action", "day", "month")}})

import test_google_maps_postgres_integration as pg_fixtures

class GoogleMapsCacheFirstPostgresTest(pg_fixtures.GoogleMapsPostgresIntegrationTest):

    def setUp(self):
        super().setUp()
        p = patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION', True)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(guard.settings, 'GOOGLE_MAPS_AGENDA_CACHE_FIRST', True)
        p.start()
        self.addCleanup(p.stop)

    def _execute_update(self):
        original = control_api.create_preview

        def paid_quote(*args, **kwargs):
            kwargs['paid_call_required'] = True
            return original(*args, **kwargs)
        with patch.object(control_api, 'create_preview', side_effect=paid_quote):
            return super()._execute_update()

    def test_unpaid_phase_reaches_provider_but_sends_nothing_and_rolls_back(self):
        self._configure(action_calls=2)
        with patch.object(routes, '_http_post_json', side_effect=AssertionError('Unpaid transport')) as outbound, TestClient(self.app) as client:
            response = client.put(f'/api/v1/agenda/{self.appointment_id}', json={'inicio': '2099-05-25T11:30:00-03:00', 'fim': '2099-05-25T12:00:00-03:00'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue(response.json()['detail']['can_retry_with_confirmation'])
        outbound.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.appointment_id).inicio, self.original_start)
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 0)
        self.assertEqual(guard.get_status()['consumption']['day']['calls'], 0)
