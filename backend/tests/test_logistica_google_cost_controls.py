import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "logistica-google-cost-controls-test-secret-key-1234567890")

from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.google_maps_usage_metrica import GoogleMapsUsageMetrica
from app.services import logistica_service
from app.services import google_maps_cost_control as cost_guard
from app.models.google_maps_cost_control import COST_TABLES


class LogisticaGoogleCostControlsTest(unittest.TestCase):
    def setUp(self):
        # Legacy route unit cases have no active cache-only policy. Keep their
        # policy lookup isolated from the developer database; transports retain
        # the explicit mocks used in each individual computation test.
        ledger = create_engine("sqlite://")
        for table in COST_TABLES:
            table.create(ledger)
        self.addCleanup(ledger.dispose)
        policy = patch.object(cost_guard.database, "engine", ledger)
        policy.start()
        self.addCleanup(policy.stop)

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "logistica-google-cost-controls.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            ClinicaDeslocamento.__table__,
            GoogleMapsUsageMetrica.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_estimar_deslocamento_pula_google_quando_lookup_ao_vivo_desligado(self) -> None:
        origem = Clinica(id=1, nome="Origem", latitude=-3.7200, longitude=-38.5200)
        destino = Clinica(id=2, nome="Destino", latitude=-3.8100, longitude=-38.6100)
        telemetry = []

        with (
            patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "fake-key"),
            patch.object(logistica_service, "_consultar_google_routes_api_raw") as mocked_routes,
            patch.object(logistica_service, "_consultar_google_distance_matrix_raw") as mocked_dm,
        ):
            _km, duracao_min, fonte = logistica_service.estimar_deslocamento(
                origem,
                destino,
                perfil="comercial",
                permitir_google_lookup=False,
                telemetry_events=telemetry,
            )

        mocked_routes.assert_not_called()
        mocked_dm.assert_not_called()
        self.assertGreater(duracao_min, 0)
        self.assertTrue(fonte.startswith("heuristica_"))
        self.assertTrue(
            any(
                event.get("operation") == "google_lookup_skipped" and event.get("status") == "skipped"
                for event in telemetry
            )
        )

    def test_routes_usa_routing_traffic_unaware_por_padrao(self) -> None:
        telemetry = []
        captured_bodies = []

        def _fake_post(_url, body, headers=None, timeout=8.0):
            captured_bodies.append(body)
            return {
                "routes": [
                    {
                        "distanceMeters": 10000,
                        "duration": "1200s",
                    }
                ]
            }

        with (
            patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "fake-key"),
            patch.object(logistica_service.settings, "LOGISTICA_GOOGLE_TRAFFIC_AWARE", False),
            patch.object(logistica_service, "authorize_google_call"),
            patch.object(logistica_service, "_http_post_json", side_effect=_fake_post),
        ):
            out = logistica_service._consultar_google_routes_api_raw(
                {"address": "A"},
                {"address": "B"},
                telemetry_events=telemetry,
            )

        self.assertIsNotNone(out)
        self.assertEqual(captured_bodies[0].get("routingPreference"), "TRAFFIC_UNAWARE")
        self.assertEqual(out.get("provider"), "routes_api_basic")

    def test_distance_matrix_sem_parametros_de_trafego_quando_flag_desligada(self) -> None:
        telemetry = []
        captured_urls = []

        def _fake_get(url, timeout=8.0):
            captured_urls.append(url)
            return {
                "status": "OK",
                "rows": [
                    {
                        "elements": [
                            {
                                "status": "OK",
                                "distance": {"value": 1500},
                                "duration": {"value": 240},
                            }
                        ]
                    }
                ],
            }

        with (
            patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "fake-key"),
            patch.object(logistica_service.settings, "LOGISTICA_GOOGLE_TRAFFIC_AWARE", False),
            patch.object(logistica_service, "authorize_google_call"),
            patch.object(logistica_service, "_http_get_json", side_effect=_fake_get),
        ):
            out = logistica_service._consultar_google_distance_matrix_raw(
                "-3.72,-38.52",
                "-3.81,-38.61",
                telemetry_events=telemetry,
            )

        self.assertIsNotNone(out)
        self.assertEqual(out.get("provider"), "distance_matrix_basic")
        query = parse_qs(urlparse(captured_urls[0]).query)
        self.assertNotIn("departure_time", query)
        self.assertNotIn("traffic_model", query)

    def test_obter_duracao_entidades_operacionais_respeita_gate_live_lookup_desligado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            origem = SimpleNamespace(
                id=10,
                nome="Clinica Base",
                latitude=-3.7200,
                longitude=-38.5200,
                cidade="Fortaleza",
                estado="CE",
                endereco="Rua A",
                numero="100",
                bairro="Centro",
                cep="60000000",
                place_id="place-clinica-10",
                geocode_at=datetime(2026, 1, 1, 9, 0, 0),
            )
            destino = SimpleNamespace(
                id=-33,
                nome="Domicilio Tutor 33",
                latitude=-3.8100,
                longitude=-38.6100,
                cidade="Fortaleza",
                estado="CE",
                endereco="Rua B",
                numero="200",
                bairro="Benfica",
                cep="60000001",
                place_id="place-tutor-33",
                geocode_at=datetime(2026, 1, 1, 9, 0, 0),
            )

            with (
                patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "fake-key"),
                patch.object(logistica_service.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", False),
                patch.object(logistica_service, "_consultar_google_routes_api_raw") as mocked_routes,
                patch.object(logistica_service, "_consultar_google_distance_matrix_raw") as mocked_dm,
            ):
                duracao_min, fonte = logistica_service.obter_duracao_deslocamento_entidades(
                    db,
                    origem=origem,
                    destino=destino,
                    perfil="comercial",
                )

            mocked_routes.assert_not_called()
            mocked_dm.assert_not_called()
            self.assertGreater(duracao_min, 0)
            self.assertTrue(fonte.startswith("heuristica_"))

            row = (
                db.query(ClinicaDeslocamento)
                .filter(
                    ClinicaDeslocamento.origem_clinica_id == 10,
                    ClinicaDeslocamento.destino_clinica_id == -33,
                    ClinicaDeslocamento.perfil == "comercial",
                )
                .first()
            )
            self.assertIsNotNone(row)
            self.assertTrue(str(row.fonte or "").startswith("heuristica_"))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_obter_duracao_entidades_operacionais_reutiliza_cache_persistido_sem_novo_google(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            origem = SimpleNamespace(
                id=10,
                nome="Clinica Base",
                latitude=-3.7200,
                longitude=-38.5200,
                cidade="Fortaleza",
                estado="CE",
                endereco="Rua A",
                numero="100",
                bairro="Centro",
                cep="60000000",
                place_id="place-clinica-10",
                geocode_at=datetime(2026, 1, 1, 9, 0, 0),
            )
            destino = SimpleNamespace(
                id=-44,
                nome="Domicilio Tutor 44",
                latitude=-3.8100,
                longitude=-38.6100,
                cidade="Fortaleza",
                estado="CE",
                endereco="Rua B",
                numero="200",
                bairro="Benfica",
                cep="60000001",
                place_id="place-tutor-44",
                geocode_at=datetime(2026, 1, 1, 9, 0, 0),
            )
            google_result = {
                "provider": "routes_api_basic",
                "distance_km": 12.4,
                "duracao_base_min": 21,
                "duracao_traffic_min": None,
            }

            with (
                patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "fake-key"),
                patch.object(logistica_service.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", True),
                patch.object(logistica_service, "_consultar_google_routes_api_raw", return_value=google_result) as mocked_routes,
                patch.object(logistica_service, "_consultar_google_distance_matrix_raw") as mocked_dm,
            ):
                first = logistica_service.obter_duracao_deslocamento_entidades(
                    db,
                    origem=origem,
                    destino=destino,
                    perfil="comercial",
                )
                second = logistica_service.obter_duracao_deslocamento_entidades(
                    db,
                    origem=origem,
                    destino=destino,
                    perfil="comercial",
                )

            self.assertEqual(first, (21, "google_routes_api"))
            self.assertEqual(second, (21, "google_routes_api"))
            self.assertEqual(mocked_routes.call_count, 1)
            mocked_dm.assert_not_called()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
