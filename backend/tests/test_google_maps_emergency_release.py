"""Explicit, reversible emergency release; all provider transports are synthetic."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "emergency-release-synthetic-secret-key-123456789")

from app.api.v1.endpoints import agenda, logistica, google_maps_cost_control as control_api
from app.core.config import Settings
from app.core.security import get_current_user
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.google_maps_cost_control import COST_TABLES
from app.models.google_maps_usage_metrica import GoogleMapsUsageMetrica
from app.services import google_maps_cost_control as guard
from app.services import google_maps_cost_middleware as middleware
from app.services import logistica_service as routes, geocoding_service


class GoogleMapsEmergencyReleaseTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.business = create_engine("sqlite:///" + str(Path(self.directory.name) / "business.db"), connect_args={"check_same_thread": False})
        self.addCleanup(self.business.dispose)
        self.sessions = sessionmaker(bind=self.business, autoflush=False)
        for table in (Clinica.__table__, ClinicaDeslocamento.__table__, GoogleMapsUsageMetrica.__table__):
            table.create(self.business)
        with self.sessions() as db:
            db.add_all([Clinica(id=1, nome="Synthetic A", latitude=-3.7, longitude=-38.5),
                        Clinica(id=2, nome="Synthetic B", latitude=-3.8, longitude=-38.6)])
            db.commit()
        # The exception must operate even when the cost ledger is unavailable.
        # No real database settings or customer data are used by this fixture.
        self.ledger = Mock()
        self.ledger.connect.side_effect = AssertionError("Emergency release accessed the cost ledger")
        for p in (
            patch.object(guard.database, "engine", self.ledger),
            patch.object(guard.settings, "GOOGLE_MAPS_COST_EMERGENCY_RELEASE", True),
            patch.object(guard.settings, "GOOGLE_MAPS_API_KEY", "private-synthetic-key"),
            patch.object(guard.settings, "SECRET_KEY", "emergency-release-synthetic-secret-key-123456789"),
            patch.object(guard.settings, "LOGISTICA_GOOGLE_TRAFFIC_AWARE", False),
            patch.object(guard.settings, "GOOGLE_ROUTES_CACHE_MAX_AGE_DAYS", 30),
            patch.object(guard.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", True),
            patch.object(routes, "urlopen", side_effect=AssertionError("Real network forbidden")),
            patch.object(geocoding_service, "urlopen", side_effect=AssertionError("Real network forbidden")),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.post = self._patch(routes, "_http_post_json", return_value={"routes": [{"distanceMeters": 5000, "duration": "1200s"}]})
        self.matrix = self._patch(routes, "_http_get_json", return_value={"status": "OK", "rows": [{"elements": [{"status": "OK", "distance": {"value": 5000}, "duration": {"value": 1200}}]}]})
        self.geocode = self._patch(geocoding_service, "_http_get_json", return_value={"status": "OK", "results": [{"geometry": {"location": {"lat": -3.7, "lng": -38.5}}}]})
        self.app = FastAPI()
        self.app.include_router(logistica.router, prefix="/api/v1/logistica")
        self.app.include_router(control_api.router, prefix="/api/v1/google-maps-control")
        self.app.add_middleware(middleware.GoogleMapsCostMiddleware)
        def get_db():
            with self.sessions() as db:
                yield db
        self.app.dependency_overrides[logistica.get_db] = get_db
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, tem_papel=lambda _: True)
        self.authenticate = self._patch(middleware, "_authenticate", return_value=7)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(guard._execution.set, None)

    def _patch(self, target, name, **kwargs):
        p = patch.object(target, name, **kwargs)
        result = p.start()
        self.addCleanup(p.stop)
        return result

    def lookup(self):
        return self.client.get("/api/v1/logistica/deslocamento", params={"origem_clinica_id": 1, "destino_clinica_id": 2})

    def test_flag_is_off_by_default(self):
        self.assertIs(Settings.model_fields["GOOGLE_MAPS_COST_EMERGENCY_RELEASE"].default, False)

    def test_preview_and_status_expose_unknown_cost_without_touching_ledger(self):
        preview = self.client.post("/api/v1/google-maps-control/preview", json={
            "method": "POST", "path": "/api/v1/agenda", "body": {"address": "private address"},
        })
        self.assertEqual(preview.status_code, 200, preview.text)
        data = preview.json()
        self.assertFalse(data["required"])
        self.assertFalse(data["blocked"])
        self.assertTrue(data["paid_calls_allowed"])
        self.assertEqual(data["operation_mode"], "temporary_open")
        for key in ("quote_id", "max_calls", "estimated_cost_min_brl", "estimated_cost_max_brl", "limits", "remaining", "consumption"):
            self.assertIsNone(data[key])
        status = guard.get_status()
        self.assertFalse(status["configured"])
        self.assertFalse(status["enabled"])
        self.assertFalse(status["blocked"])
        self.assertIsNone(status["config"])
        self.assertIsNone(status["consumption"])
        self.assertEqual(status["history"], [])
        self.assertIn("sem teto financeiro", status["message"])
        self.assertIn("pode haver cobrança", status["billing_note"])
        self.ledger.connect.assert_not_called()

    def test_direct_real_api_can_compute_cold_route_then_reuse_cache_without_grant(self):
        with self.assertLogs(guard.logger, level="WARNING") as logs:
            response = self.lookup()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["item"]["duracao_min"], 20)
        self.assertTrue(response.json()["item"]["fonte"].startswith("google_routes_api"))
        self.post.assert_called_once()
        self.matrix.assert_not_called()
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(json.loads(logs.records[0].getMessage())["execution_type"], "http")
        self.assertEqual(self.lookup().status_code, 200)
        self.post.assert_called_once()
        self.ledger.connect.assert_not_called()

    def test_cost_release_does_not_bypass_http_authentication(self):
        self.authenticate.side_effect = HTTPException(401, "Authentication required")
        self.assertEqual(self.lookup().status_code, 401)
        self.post.assert_not_called()
        self.matrix.assert_not_called()
        self.ledger.connect.assert_not_called()

    def test_all_three_real_provider_boundaries_log_before_transport_without_pii(self):
        records = []
        def logged_before_transport(_url, *_args, **_kwargs):
            self.assertTrue(records, "Audit must precede transport")
            return {"routes": [{"distanceMeters": 5000, "duration": "1200s"}]}
        self.post.side_effect = logged_before_transport
        with patch.object(guard.logger, "warning", side_effect=lambda _fmt, payload: records.append(json.loads(payload))):
            routes._consultar_google_routes_api_raw({"address": "private origin"}, {"address": "private destination"})
            routes._consultar_google_distance_matrix_raw("private origin", "private destination")
            result = geocoding_service.geocodificar_endereco_google("private address", "private-synthetic-key")
        self.assertEqual(result.latitude, -3.7)
        self.assertEqual([r["sku"] for r in records], ["routes_essentials", "distance_matrix_essentials", "geocoding"])
        self.assertTrue(all(r["estimated_cost_brl"] is None and r["financial_limit_enforced"] is False for r in records))
        serialized = json.dumps(records)
        self.assertNotIn("private", serialized)
        self.assertNotIn("http://", serialized)
        self.assertNotIn("https://", serialized)
        self.ledger.connect.assert_not_called()

    def test_automatic_worker_path_is_explicitly_logged_and_needs_no_ledger_policy(self):
        with self.assertLogs(guard.logger, level="WARNING") as logs:
            with guard.automatic_action("whatsapp_agenda", "private-synthetic-job"):
                routes._consultar_google_routes_api_raw({"address": "private origin"}, {"address": "private destination"})
        record = json.loads(logs.records[0].getMessage())
        self.assertEqual(record["execution_type"], "automatic")
        self.assertNotIn("private", json.dumps(record))
        self.post.assert_called_once()
        self.ledger.connect.assert_not_called()

    def test_unknown_sku_remains_denied_before_transport_or_ledger(self):
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
            guard.authorize_google_call("unknown-service")
        self.assertEqual(exc.exception.reason, "sku_not_authorized")
        self.ledger.connect.assert_not_called()
        self.post.assert_not_called()

    def test_existing_cache_only_execution_cannot_keep_emergency_release_after_revocation(self):
        execution = guard.Execution("synthetic-cache-only-action", operation_mode="cache_only")
        token = guard.bind_execution(execution)
        try:
            self.assertFalse(guard.cache_only_operation())
            with self.assertLogs(guard.logger, level="WARNING"):
                guard.authorize_google_call("routes_essentials")
            with patch.object(guard.settings, "GOOGLE_MAPS_COST_EMERGENCY_RELEASE", False):
                self.assertTrue(guard.cache_only_operation())
                with self.assertRaises(guard.GoogleMapsCostBlocked):
                    guard.authorize_google_call("routes_essentials")
        finally:
            guard.reset_execution(token)

    def test_new_emergency_execution_does_not_authorize_after_flag_is_removed(self):
        execution = guard.claim_execution(7, None, "POST", "/api/v1/agenda")
        self.assertEqual(execution.operation_mode, "temporary_open")
        self.ledger.connect.assert_not_called()
        token = guard.bind_execution(execution)
        try:
            with patch.object(guard.settings, "GOOGLE_MAPS_COST_EMERGENCY_RELEASE", False):
                with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                    guard.authorize_google_call("routes_essentials")
                self.assertEqual(exc.exception.reason, "ledger_unavailable")
            self.ledger.connect.reset_mock()
            guard.finish_execution(execution)
            self.assertTrue(execution.closed)
            self.ledger.connect.assert_not_called()
        finally:
            guard.reset_execution(token)

    def test_revoke_restores_persisted_cache_only_policy_without_changing_ledger(self):
        ledger = create_engine("sqlite://")
        self.addCleanup(ledger.dispose)
        for table in COST_TABLES:
            table.create(ledger)
        with patch.object(guard.database, "engine", ledger):
            with patch.object(guard.settings, "GOOGLE_MAPS_COST_EMERGENCY_RELEASE", False):
                cfg = guard.CostConfiguration.model_validate({"operation_mode": "cache_only", "enabled": True,
                    "limits": {p: {"calls": 0, "estimated_brl": 0} for p in ("action", "day", "month")}})
                original = guard.update_configuration(7, cfg, 0)
            with ledger.connect() as conn:
                before = (conn.execute(select(guard.CONFIG)).all(), conn.execute(select(guard.EVENTS)).all())
            execution = guard.claim_execution(7, None, "POST", "/api/v1/agenda")
            token = guard.bind_execution(execution)
            try:
                with self.assertLogs(guard.logger, level="WARNING"):
                    guard.authorize_google_call("routes_essentials")
                guard.finish_execution(execution)
            finally:
                guard.reset_execution(token)
            with ledger.connect() as conn:
                self.assertEqual(before, (conn.execute(select(guard.CONFIG)).all(), conn.execute(select(guard.EVENTS)).all()))
            with patch.object(guard.settings, "GOOGLE_MAPS_COST_EMERGENCY_RELEASE", False):
                restored = guard.get_status()
                self.assertEqual(restored["revision"], original["revision"])
                self.assertEqual(restored["config"], original["config"])
                self.assertTrue(guard.cache_only_operation())
                with self.assertRaises(guard.GoogleMapsCostBlocked) as exc:
                    guard.authorize_google_call("routes_essentials")
                self.assertEqual(exc.exception.reason, "cache_only")

    def test_first_departure_uses_google_route_during_release(self):
        destination = {"tipo": "clinica", "entity_id": 2, "latitude": -3.8, "longitude": -38.6,
                       "localizacao_confiavel": True, "nome": "Synthetic B"}
        base = {"address": "private synthetic address", "lat": -3.7, "lng": -38.5}
        with self.sessions() as db, self.assertLogs(guard.logger, level="WARNING"):
            duration, source = agenda._obter_deslocamento_primeira_saida(db, destino=destination, base_cfg=base, perfil="comercial")
        self.assertGreater(duration, 0)
        self.assertTrue(source.startswith("google_routes_api"), source)
        self.post.assert_called_once()
        self.ledger.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
