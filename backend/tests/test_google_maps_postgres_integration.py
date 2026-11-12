"""Real PostgreSQL Agenda + Maps ledger integration, with zero external I/O.

Only the HTTP transport, identity fixture and notifications are stubbed. The
middleware, grant, reservation, route computation, cache writes and Agenda
transaction are real. Each case gets a disposable schema in localhost's
maps_cost_test; an arbitrary DATABASE_URL is never accepted for mutations.
"""
import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "google-maps-postgres-integration-test-secret-123456")

from app.api.v1.endpoints import agenda, google_maps_cost_control as control_api
from app.core.security import get_current_user
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.configuracao import Configuracao
from app.models.google_maps_cost_control import COST_TABLES
from app.models.google_maps_usage_metrica import GoogleMapsUsageMetrica
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.services import geocoding_service, logistica_service
from app.services import google_maps_cost_control as guard
from app.services import google_maps_cost_middleware as middleware


@unittest.skipUnless(os.environ.get("MAPS_COST_TEST_POSTGRES_URL"), "Requires disposable localhost/maps_cost_test PostgreSQL")
class GoogleMapsPostgresIntegrationTest(unittest.TestCase):
    def setUp(self):
        url = os.environ["MAPS_COST_TEST_POSTGRES_URL"]
        parsed = make_url(url)
        if parsed.get_backend_name() != "postgresql" or parsed.host not in {"localhost", "127.0.0.1", "::1"} or parsed.database != "maps_cost_test":
            raise AssertionError("Only disposable localhost PostgreSQL maps_cost_test is permitted")
        self.schema = "maps_integration_" + uuid.uuid4().hex
        self.admin = create_engine(url)
        with self.admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(url, connect_args={"options": f"-csearch_path={self.schema}", "client_encoding": "UTF8"}, pool_size=5)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.addCleanup(self._drop_schema)
        for table in COST_TABLES:
            table.create(self.engine)
        for model in (Agendamento, Clinica, ClinicaDeslocamento, Configuracao, GoogleMapsUsageMetrica, Paciente, Servico, Tutor):
            model.__table__.create(self.engine)
        with self.sessions() as db:
            db.add(Configuracao(
                agenda_semanal=json.dumps({str(day): {"ativo": True, "inicio": "08:00", "fim": "18:00"} for day in range(1, 8)}),
                agenda_feriados="[]", agenda_excecoes="[]",
                agenda_rota_regras=json.dumps({"route_policy": {"reject_clear_inefficiency": False}}),
            ))
            clinics = [Clinica(nome=f"Synthetic clinic {i}", ativo=True, latitude=-3.7, longitude=-38.5, place_id=f"synthetic-{i}") for i in range(3)]
            tutor = Tutor(nome="Synthetic tutor", ativo=1)
            service = Servico(nome="Synthetic service", duracao_minutos=30, ativo=True)
            db.add_all([*clinics, tutor, service])
            db.flush()
            patient = Paciente(nome="Synthetic patient", tutor_id=tutor.id, ativo=1)
            db.add(patient)
            db.flush()
            appointments = []
            for clinic, hour in zip(clinics, (9, 11, 14)):
                start = datetime(2099, 5, 25, hour, tzinfo=agenda.LOCAL_TZ)
                appointments.append(Agendamento(clinica_id=clinic.id, tutor_id=tutor.id, paciente_id=patient.id,
                    servico_id=service.id, inicio=start, fim=start + timedelta(minutes=30),
                    data="2099-05-25", hora=f"{hour:02}:00", status="Agendado"))
            db.add_all(appointments)
            db.commit()
            self.appointment_id = appointments[1].id
            self.original_start = appointments[1].inicio

        self.app = FastAPI()
        self.app.include_router(agenda.router, prefix="/api/v1/agenda")
        self.app.include_router(control_api.router, prefix="/api/v1/google-maps-control")
        self.app.add_middleware(middleware.GoogleMapsCostMiddleware)
        def request_db():
            with self.sessions() as db:
                yield db
        self.app.dependency_overrides[agenda.get_db] = request_db
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, nome="Synthetic admin", tem_papel=lambda _: True)
        for patcher in (
            patch.object(guard.database, "engine", self.engine),
            patch.object(guard.settings, "SECRET_KEY", "google-maps-postgres-integration-test-secret-123456"),
            patch.object(middleware, "_authenticate", return_value=7),
            patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "synthetic-key"),
            patch.object(logistica_service.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", True),
            patch.object(logistica_service.settings, "LOGISTICA_GOOGLE_TRAFFIC_AWARE", False),
            patch.object(agenda, "registrar_auditoria"),
            patch.object(agenda, "_notificar_agenda_update"),
            patch.object(logistica_service, "urlopen", side_effect=AssertionError("Real network is forbidden")),
            patch.object(logistica_service, "_http_get_json", side_effect=AssertionError("Unexpected fallback transport")),
            patch.object(geocoding_service, "urlopen", side_effect=AssertionError("Real geocoding is forbidden")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _drop_schema(self):
        self.engine.dispose()
        try:
            with self.admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        finally:
            self.admin.dispose()

    def _configure(self, action_calls):
        config = guard.CostConfiguration.model_validate({
            "enabled": True,
            "limits": {"action": {"calls": action_calls, "estimated_brl": 1},
                       "day": {"calls": 10, "estimated_brl": 10},
                       "month": {"calls": 20, "estimated_brl": 20}},
            "prices_usd": {sku: "0.01" for sku in guard.SKUS},
            "fx_brl_per_usd_upper": 6, "price_multiplier": 1,
            "pricing_valid_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "opening_usage": {"day": {"calls": 0, "estimated_brl": 0}, "month": {"calls": 0, "estimated_brl": 0}},
            "opening_usage_as_of": guard._periods(guard._now())[0], "opening_usage_basis": "verified_telemetry",
        })
        guard.update_configuration(7, config, 0)

    def _execute_update(self):
        observations = []
        def synthetic_http(*_args, **_kwargs):
            # At transport time the ledger must ALREADY be durable, whereas a
            # third DB connection must still see the original business state.
            with self.sessions() as observer:
                observations.append({
                    "start": observer.get(Agendamento, self.appointment_id).inicio,
                    "cache_rows": observer.query(ClinicaDeslocamento).count(),
                    "reserved_calls": guard.get_status()["consumption"]["day"]["calls"],
                })
            return {"routes": [{"distanceMeters": 1000, "duration": "600s"}]}

        path = f"/api/v1/agenda/{self.appointment_id}"
        payload = {"inicio": "2099-05-25T11:30:00-03:00", "fim": "2099-05-25T12:00:00-03:00"}
        with patch.object(logistica_service, "_http_post_json", side_effect=synthetic_http) as transport, TestClient(self.app) as client:
            quote = client.post("/api/v1/google-maps-control/preview", json={"method": "PUT", "path": path, "body": payload})
            self.assertEqual(quote.status_code, 200, quote.text)
            self.assertFalse(quote.json()["blocked"])
            self.assertEqual(transport.call_count, 0)
            confirmed = client.post("/api/v1/google-maps-control/confirm", json={"quote_id": quote.json()["quote_id"]})
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            response = client.put(path, json=payload, headers={"X-Google-Maps-Action": confirmed.json()["token"]})
            sent = transport.call_count
        return response, sent, observations

    def test_two_real_route_legs_commit_business_and_cache_with_separate_ledger(self):
        self._configure(action_calls=2)
        response, sent, observations = self._execute_update()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(sent, 2)
        self.assertEqual([item["reserved_calls"] for item in observations], [1, 2])
        self.assertTrue(all(item["start"] == self.original_start and item["cache_rows"] == 0 for item in observations))
        with self.sessions() as fresh:
            self.assertEqual(fresh.get(Agendamento, self.appointment_id).inicio, datetime.fromisoformat("2099-05-25T11:30:00-03:00"))
            self.assertEqual(fresh.query(ClinicaDeslocamento).count(), 4)
        self.engine.dispose()  # A new connection must retain committed usage.
        self.assertEqual(guard.get_status()["consumption"]["day"], {"calls": 2, "estimated_brl": 0.12})

    def test_second_leg_denied_rolls_back_business_but_keeps_first_paid_reservation(self):
        self._configure(action_calls=1)
        response, sent, observations = self._execute_update()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["reason"], "action_limit")
        self.assertEqual(sent, 1)
        self.assertEqual(observations, [{"start": self.original_start, "cache_rows": 0, "reserved_calls": 1}])
        with self.sessions() as fresh:
            self.assertEqual(fresh.get(Agendamento, self.appointment_id).inicio, self.original_start)
            self.assertEqual(fresh.query(ClinicaDeslocamento).count(), 0)
            self.assertEqual(fresh.query(GoogleMapsUsageMetrica).count(), 0)
        self.engine.dispose()
        status = guard.get_status()
        self.assertEqual(status["consumption"]["day"], {"calls": 1, "estimated_brl": 0.06})
        self.assertTrue(any(event["kind"] == "blocked" and event["reason"] == "action_limit" for event in status["history"]))

    def _cache_only_update(self, *, missing_second_leg=False):
        guard.update_configuration(7, guard.CostConfiguration.model_validate({
            "operation_mode": "cache_only", "enabled": True,
            "limits": {period: {"calls": 0, "estimated_brl": 0} for period in ("action", "day", "month")},
        }), 0)
        with self.sessions() as db:
            ids = [clinic.id for clinic in db.query(Clinica).order_by(Clinica.id).all()]
            pairs = [(ids[0], ids[1])] if missing_second_leg else [(ids[0], ids[1]), (ids[1], ids[2])]
            for origin, destination in pairs:
                for profile in ("comercial", "plantao"):
                    db.add(ClinicaDeslocamento(origem_clinica_id=origin, destino_clinica_id=destination,
                        perfil=profile, distancia_km=1, duracao_min=10,
                        fonte="google_routes_api", updated_at=datetime.now(timezone.utc)))
            db.commit()
        path = f"/api/v1/agenda/{self.appointment_id}"
        payload = {"inicio": "2099-05-25T11:30:00-03:00", "fim": "2099-05-25T12:00:00-03:00"}
        with patch.object(logistica_service, "_http_post_json", side_effect=AssertionError("Cache-only must never send a route")) as transport, TestClient(self.app) as client:
            preview = client.post("/api/v1/google-maps-control/preview", json={"method": "PUT", "path": path, "body": payload})
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertFalse(preview.json()["required"])
            self.assertIsNone(preview.json()["quote_id"])
            response = client.put(path, json=payload)  # No paid consent token.
            transport.assert_not_called()
        return response

    def test_cache_only_two_real_legs_commit_without_new_calls_or_financial_baseline(self):
        response = self._cache_only_update()
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.appointment_id).inicio, datetime.fromisoformat("2099-05-25T11:30:00-03:00"))
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 4)
        status = guard.get_status()
        self.assertIsNone(status["opening_usage"])
        self.assertEqual(status["consumption"]["day"], {"calls": 0, "estimated_brl": 0})

    def test_cache_only_missing_second_leg_rolls_back_business_without_any_google_call(self):
        response = self._cache_only_update(missing_second_leg=True)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["reason"], "cache_only")
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.appointment_id).inicio, self.original_start)
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 2)
            self.assertEqual(db.query(GoogleMapsUsageMetrica).count(), 0)
        self.assertEqual(guard.get_status()["consumption"]["day"], {"calls": 0, "estimated_brl": 0})


if __name__ == "__main__":
    unittest.main()
