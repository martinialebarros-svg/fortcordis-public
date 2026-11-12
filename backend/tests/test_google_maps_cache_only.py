"""Zero-new-charge mode against real middleware, database and route lookups.

All fixtures are synthetic. Every Google transport is forbidden; no pricing,
exchange-rate or previous usage is fabricated to activate cache-only policy.
"""
import os
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "cache-only-test-secret-synthetic-123456789")

from app.api.v1.endpoints import agenda, logistica, google_maps_cost_control as control_api
from app.core.security import get_current_user
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.google_maps_cost_control import COST_TABLES
from app.services import google_maps_cost_control as guard
from app.services import google_maps_cost_middleware as middleware
from app.services import logistica_service as routes, geocoding_service


def cache_configuration():
    return {"operation_mode": "cache_only", "enabled": True,
            "limits": {period: {"calls": 0, "estimated_brl": 0} for period in ("action", "day", "month")}}


class GoogleMapsCacheOnlyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.directory.name) / "cache.db"), connect_args={"check_same_thread": False})
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        for table in (*COST_TABLES, Clinica.__table__, ClinicaDeslocamento.__table__):
            table.create(self.engine)
        with self.sessions() as db:
            db.add_all([Clinica(id=1, nome="Synthetic A", latitude=-3.7, longitude=-38.5),
                        Clinica(id=2, nome="Synthetic B", latitude=-3.8, longitude=-38.6)])
            db.commit()
        self.app = FastAPI()
        self.app.include_router(logistica.router, prefix="/api/v1/logistica")
        self.app.include_router(control_api.router, prefix="/api/v1/google-maps-control")
        self.app.add_middleware(middleware.GoogleMapsCostMiddleware)
        def get_db():
            with self.sessions() as db:
                yield db
        self.app.dependency_overrides[logistica.get_db] = get_db
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, tem_papel=lambda _: True)
        self.transports = []
        for service, name in ((routes, "_http_post_json"), (routes, "_http_get_json"), (routes, "urlopen"),
                              (geocoding_service, "_http_get_json"), (geocoding_service, "urlopen")):
            p = patch.object(service, name, side_effect=AssertionError("No real or synthetic Google transport is allowed"))
            self.transports.append(p.start())
            self.addCleanup(p.stop)
        for p in (patch.object(guard.database, "engine", self.engine),
                  patch.object(guard.settings, "SECRET_KEY", "cache-only-test-secret-synthetic-123456789"),
                  patch.object(middleware, "_authenticate", return_value=7),
                  patch.object(routes.settings, "GOOGLE_MAPS_API_KEY", "synthetic-key"),
                  patch.object(routes.settings, "GOOGLE_ROUTES_CACHE_MAX_AGE_DAYS", 7)):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def tearDown(self):
        for transport in self.transports:
            transport.assert_not_called()
        guard._execution.set(None)
        self.engine.dispose()
        self.directory.cleanup()

    def configure(self):
        response = self.client.put("/api/v1/google-maps-control/config", json={**cache_configuration(), "expected_revision": 0})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def seed_route(self, *, source="google_routes_api", age_days=0, manual=False):
        timestamp = datetime.utcnow() - timedelta(days=age_days)
        with self.sessions() as db:
            db.add(ClinicaDeslocamento(origem_clinica_id=1, destino_clinica_id=2, perfil="comercial",
                distancia_km=5, duracao_min=20, fonte=source, manual_override=manual, updated_at=timestamp))
            db.commit()
        return timestamp

    def lookup(self, **query):
        return self.client.get("/api/v1/logistica/deslocamento", params={"origem_clinica_id": 1, "destino_clinica_id": 2, **query})

    def assert_cache_block(self, fn):
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            fn()
        self.assertEqual(exc.exception.reason, "cache_only")

    def test_minimal_configuration_has_no_fake_financial_baseline_and_no_paid_quote(self):
        status = self.configure()
        self.assertTrue(status["enabled"])
        self.assertFalse(status["blocked"])
        self.assertFalse(status["paid_calls_allowed"])
        self.assertIsNone(status["opening_usage"])
        self.assertIsNone(status["consumed_since"])
        for field in ("prices_usd", "fx_brl_per_usd_upper", "price_multiplier", "pricing_valid_until", "opening_usage", "opening_usage_as_of", "opening_usage_basis"):
            self.assertNotIn(field, status["config"])
        preview = self.client.post("/api/v1/google-maps-control/preview", json={"method": "GET", "path": "/api/v1/logistica/deslocamento"}).json()
        self.assertFalse(preview["required"])
        self.assertFalse(preview["blocked"])
        self.assertIsNone(preview["quote_id"])
        self.assertEqual((preview["max_calls"], preview["estimated_cost_max_brl"]), (0, 0))
        self.assertIn("R$ 0", preview["message"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(guard.ACTIONS.c.id)).all(), [])
            self.assertEqual(conn.execute(select(guard.EVENTS.c.id).where(guard.EVENTS.c.kind == "opening")).all(), [])

    def test_cache_mode_rejects_positive_limits_financial_values_and_auto_policies(self):
        for extra in ({"limits": {p: {"calls": 1, "estimated_brl": 0} for p in ("action", "day", "month")}},
                      {"limits": {p: {"calls": 0, "estimated_brl": "0.01"} for p in ("action", "day", "month")}},
                      {"prices_usd": {s: "0.01" for s in guard.SKUS}},
                      {"fx_brl_per_usd_upper": 5}, {"action_call_caps": {"route_lookup": 1}}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                guard.CostConfiguration.model_validate({**cache_configuration(), **extra})
        with self.assertRaises(ValidationError):
            guard.CostConfiguration.model_validate({**cache_configuration(), "operation_mode": "paid_budget"})

    def test_direct_real_api_reuses_google_cache_without_grant_or_ttl_extension(self):
        timestamp = self.seed_route()
        self.configure()
        for _ in range(2):
            response = self.lookup()
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["item"]["duracao_min"], 20)
        with self.sessions() as db:
            self.assertEqual(db.query(ClinicaDeslocamento).one().updated_at, timestamp)
        with self.engine.connect() as conn:
            rows = conn.execute(select(guard.ACTIONS)).mappings().all()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["max_calls"] == 0 and row["max_cost_micros"] == 0 and row["state"] == "finished" for row in rows))
        self.assertEqual(guard.get_status()["consumption"]["month"], {"calls": 0, "estimated_brl": 0})

    def test_authorized_manual_override_remains_available(self):
        self.seed_route(source="manual", age_days=100, manual=True)
        self.configure()
        response = self.lookup(recalcular="true")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["item"]["manual_override"])

    def test_cold_cache_blocks_before_network_or_new_cache_write(self):
        self.configure()
        response = self.lookup()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["reason"], "cache_only")
        with self.sessions() as db:
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 0)
        self.assertTrue(any(row["reason"] == "cache_only" for row in guard.get_status()["history"]))

    def test_stale_google_cache_is_not_reused_or_renewed(self):
        timestamp = self.seed_route(age_days=8)
        self.configure()
        with patch.object(routes.settings, "GOOGLE_ROUTES_CACHE_EXPIRE_BY_AGE", True):
            self.assertEqual(self.lookup().status_code, 409)
        with self.sessions() as db:
            self.assertEqual(db.query(ClinicaDeslocamento).one().updated_at, timestamp)

    def test_unbounded_ttl_does_not_make_old_google_cache_valid(self):
        self.seed_route(age_days=100)
        self.configure()
        with patch.object(routes.settings, "GOOGLE_ROUTES_CACHE_MAX_AGE_DAYS", 0), \
             patch.object(routes.settings, "GOOGLE_ROUTES_CACHE_EXPIRE_BY_AGE", True):
            self.assertEqual(self.lookup().status_code, 409)

    def test_old_google_cache_remains_free_without_age_expiry(self):
        timestamp = self.seed_route(age_days=3650)
        self.configure()
        self.assertFalse(routes.settings.GOOGLE_ROUTES_CACHE_EXPIRE_BY_AGE)
        self.assertEqual(self.lookup().status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.query(ClinicaDeslocamento).one().updated_at, timestamp)

    def test_changed_geocode_invalidates_google_cache(self):
        self.seed_route(age_days=1)
        with self.sessions() as db:
            db.get(Clinica, 1).geocode_at = datetime.utcnow()
            db.commit()
        self.configure()
        self.assertEqual(self.lookup().status_code, 409)

    def test_fresh_heuristic_and_unapproved_manual_rows_cannot_supply_availability(self):
        self.configure()
        for source in ("heuristica_haversine", "manual", "unknown", "google_unrecognized"):
            with self.subTest(source=source):
                with self.sessions() as db:
                    db.query(ClinicaDeslocamento).delete()
                    db.commit()
                self.seed_route(source=source)
                self.assertEqual(self.lookup().status_code, 409)

    def test_key_missing_and_live_flag_disabled_do_not_enable_heuristic(self):
        self.configure()
        with self.sessions() as db, patch.object(routes.settings, "GOOGLE_MAPS_API_KEY", ""), patch.object(routes.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", False):
            a, b = db.get(Clinica, 1), db.get(Clinica, 2)
            for fn in (lambda: routes.estimar_deslocamento(a, b, permitir_google_lookup=False),
                       lambda: routes.obter_duracao_deslocamento(db, origem_clinica_id=1, destino_clinica_id=2, permitir_estimativa_fallback=False),
                       lambda: routes.obter_duracao_deslocamento_entidades(db, origem=a, destino=b, permitir_estimativa_fallback=False)):
                self.assert_cache_block(fn)

    def test_all_real_providers_block_without_context_or_with_automatic_policy(self):
        self.configure()
        operations = (lambda: routes._consultar_google_routes_api_raw({"address": "synthetic A"}, {"address": "synthetic B"}),
                      lambda: routes._consultar_google_distance_matrix_raw("synthetic A", "synthetic B"),
                      lambda: geocoding_service.geocodificar_endereco_google("synthetic address", "synthetic-key"))
        for operation in operations:
            self.assert_cache_block(operation)
            with guard.automatic_action("whatsapp_agenda", "synthetic-job"):
                self.assert_cache_block(operation)

    def test_automatic_job_can_reuse_cache_but_not_a_missing_pair(self):
        self.seed_route()
        self.configure()
        with guard.automatic_action("whatsapp_agenda", "synthetic-job"), self.sessions() as db:
            self.assertEqual(routes.obter_duracao_deslocamento(db, origem_clinica_id=1, destino_clinica_id=2), (20, "google_routes_api"))
            self.assert_cache_block(lambda: routes.obter_duracao_deslocamento(db, origem_clinica_id=2, destino_clinica_id=1))

    def test_first_departure_cannot_make_a_new_estimate(self):
        self.configure()
        with self.sessions() as db:
            destination = {"tipo": "clinica", "entity_id": 2, "clinica_id": 2, "nome": "Synthetic B", "latitude": -3.8, "longitude": -38.6, "localizacao_confiavel": True}
            self.assert_cache_block(lambda: agenda._obter_deslocamento_primeira_saida(db, destino=destination,
                base_cfg={"address": "Synthetic base", "lat": -3.7, "lng": -38.5}, perfil="comercial"))

    def test_unversioned_first_departure_session_cache_is_not_freshness_proof(self):
        self.configure()
        with self.sessions() as db:
            destination = {"tipo": "clinica", "entity_id": 2, "nome": "Synthetic B", "latitude": -3.8, "longitude": -38.6, "localizacao_confiavel": True}
            base = {"address": "Synthetic base", "lat": -3.7, "lng": -38.5}
            key = (agenda._endereco_base_primeira_saida(base), -3.7, -38.5, "clinica", 2, -3.8, -38.6, None, "comercial")
            db.info["_agenda_primeira_saida_deslocamento"] = {key: (10, "google_routes_api")}
            self.assert_cache_block(lambda: agenda._obter_deslocamento_primeira_saida(db, destino=destination, base_cfg=base, perfil="comercial"))

    def test_paid_execution_observes_cache_only_toggle_before_heuristic_fallback(self):
        # The old execution object is not authority to ignore a tighter durable
        # mode. In particular, key-missing fallback never reaches the provider.
        execution = guard.Execution("previous-paid-execution", operation_mode="paid_budget")
        token = guard.bind_execution(execution)
        try:
            self.assertFalse(guard.cache_only_operation())
            self.configure()
            with self.sessions() as db, patch.object(routes.settings, "GOOGLE_MAPS_API_KEY", ""):
                self.assert_cache_block(lambda: routes.estimar_deslocamento(db.get(Clinica, 1), db.get(Clinica, 2), permitir_google_lookup=False))
            self.assertEqual(execution.operation_mode, "cache_only")
        finally:
            guard.reset_execution(token)

    def test_stage_canary_cache_probe_uses_real_api_in_isolated_database(self):
        script = BACKEND.parent / "scripts/google_maps_stage_canary.py"
        spec = importlib.util.spec_from_file_location("cache_canary_real_probe", script)
        canary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(canary)
        isolated = create_engine("sqlite:///" + str(Path(self.directory.name) / "isolated-canary.db"), connect_args={"check_same_thread": False})
        try:
            for table in COST_TABLES:
                table.create(isolated)
            with patch.object(guard.database, "engine", isolated):
                proof = canary.probe_cache_only(guard, isolated)
                self.assertTrue(all(proof.values()))
        finally:
            isolated.dispose()

    def test_restart_and_config_change_cannot_upgrade_zero_call_execution(self):
        self.configure()
        execution = guard.claim_execution(7, None, "GET", "/api/v1/logistica/deslocamento")
        self.engine.dispose()
        self.assertEqual(guard.get_status()["operation_mode"], "cache_only")
        # Switching to a fully specified paid policy still cannot upgrade the
        # already running cache-only action, even if a caller retains its token.
        paid = guard.CostConfiguration.model_validate({"enabled": True,
            "limits": {p: {"calls": 10, "estimated_brl": 10} for p in ("action", "day", "month")},
            "prices_usd": {s: "0.01" for s in guard.SKUS}, "fx_brl_per_usd_upper": 5, "price_multiplier": 1,
            "pricing_valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "opening_usage": {p: {"calls": 3, "estimated_brl": "0.2"} for p in ("day", "month")},
            "opening_usage_as_of": guard._periods(guard._now())[0], "opening_usage_basis": "verified_telemetry"})
        guard.update_configuration(7, paid, 1)
        token = guard.bind_execution(execution)
        try:
            self.assert_cache_block(lambda: guard.authorize_google_call("routes_essentials"))
            self.assertTrue(guard.cache_only_operation())
        finally:
            guard.reset_execution(token)
        # A reconstructed execution still has a stale revision and durable cap0.
        token = guard.bind_execution(guard.Execution(execution.action_id))
        try:
            with self.assertRaises(guard.GoogleMapsCostBlocked):
                guard.authorize_google_call("routes_essentials")
        finally:
            guard.reset_execution(token)
        back = guard.update_configuration(7, guard.CostConfiguration.model_validate(cache_configuration()), 2)
        self.assertEqual(back["opening_usage"], paid.opening_usage.model_dump(mode="json"))
        self.assertEqual(back["consumption"]["month"], {"calls": 3, "estimated_brl": 0.2})

    def test_unavailable_ledger_blocks_cache_entry_without_executing_endpoint(self):
        self.seed_route()
        self.configure()
        with patch.object(self.engine, "connect", side_effect=RuntimeError("PRIVATE DB URL")):
            response = self.lookup()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("PRIVATE", response.text)
        self.assertEqual(response.json()["detail"]["reason"], "ledger_unavailable")


if __name__ == "__main__":
    unittest.main()
