"""Zero-network proofs for the actual Google providers and stable-route TTL."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "google-boundary-synthetic-test-secret-key-123456")

from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.google_maps_usage_metrica import GoogleMapsUsageMetrica
from app.services import geocoding_service, logistica_service
from app.services import google_maps_cost_control as cost_guard
from app.models.google_maps_cost_control import COST_TABLES


class GoogleMapsProviderBoundaryTest(unittest.TestCase):
    def setUp(self):
        ledger = create_engine("sqlite://")
        for table in COST_TABLES:
            table.create(ledger)
        self.addCleanup(ledger.dispose)
        policy = patch.object(cost_guard.database, "engine", ledger)
        policy.start()
        self.addCleanup(policy.stop)

    def test_all_providers_reserve_before_any_outbound_io(self):
        # This exception represents an unavailable ledger. No generic provider
        # fallback may catch it, perform I/O or convert it into a local route.
        for service, operation, args in (
            (logistica_service, "_consultar_google_routes_api_raw", ({"address": "synthetic A"}, {"address": "synthetic B"})),
            (logistica_service, "_consultar_google_distance_matrix_raw", ("synthetic A", "synthetic B")),
            (geocoding_service, "geocodificar_endereco_google", ("synthetic address", "synthetic-key")),
        ):
            with (
                self.subTest(operation=operation),
                patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "synthetic-key"),
                patch.object(service, "authorize_google_call", side_effect=RuntimeError("ledger unavailable")),
                patch.object(service, "urlopen") as network,
            ):
                with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
                    getattr(service, operation)(*args)
                network.assert_not_called()

    def test_blocked_routes_does_not_try_distance_matrix_or_heuristic(self):
        origin = SimpleNamespace(id=1, place_id="synthetic-a", latitude=0, longitude=1)
        destination = SimpleNamespace(id=2, place_id="synthetic-b", latitude=0, longitude=2)
        with (
            patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "synthetic-key"),
            patch.object(logistica_service, "authorize_google_call", side_effect=RuntimeError("budget unavailable")),
            patch.object(logistica_service, "_consultar_google_distance_matrix_raw") as fallback,
            patch.object(logistica_service, "urlopen") as network,
        ):
            with self.assertRaisesRegex(RuntimeError, "budget unavailable"):
                logistica_service.estimar_deslocamento(origin, destination)
            fallback.assert_not_called()
            network.assert_not_called()

    def test_geocoding_errors_never_include_secret_url_or_address(self):
        with (
            patch.object(geocoding_service, "authorize_google_call"),
            patch.object(geocoding_service, "_http_get_json", side_effect=RuntimeError("https://example.invalid?key=PRIVATE&address=PRIVATE")),
        ):
            with self.assertRaises(geocoding_service.GeocodingError) as error:
                geocoding_service.geocodificar_endereco_google("synthetic address", "synthetic-key")
            self.assertNotIn("PRIVATE", str(error.exception))

    def test_identical_success_refreshes_persisted_ttl_and_next_read_is_free(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + str(Path(directory) / "routes.db"))
            for model in (ClinicaDeslocamento, GoogleMapsUsageMetrica):
                model.__table__.create(engine)
            factory = sessionmaker(bind=engine)
            expired = datetime.utcnow() - timedelta(days=31)
            origin = SimpleNamespace(id=1, place_id="synthetic-a", latitude=0, longitude=1, geocode_at=None)
            destination = SimpleNamespace(id=-2, place_id="synthetic-b", latitude=0, longitude=2, geocode_at=None)
            with factory() as db:
                for profile in ("comercial", "plantao"):
                    db.add(ClinicaDeslocamento(origem_clinica_id=1, destino_clinica_id=-2,
                        perfil=profile, distancia_km=10, duracao_min=20,
                        fonte="google_routes_api_traffic" if profile == "comercial" else "google_routes_api", updated_at=expired))
                db.commit()
            with (
                patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "synthetic-key"),
                patch.object(logistica_service.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", True),
                patch.object(logistica_service.settings, "GOOGLE_ROUTES_CACHE_MAX_AGE_DAYS", 30),
                patch.object(logistica_service.settings, "GOOGLE_ROUTES_CACHE_EXPIRE_BY_AGE", True),
                patch.object(logistica_service.settings, "LOGISTICA_GOOGLE_TRAFFIC_AWARE", False),
                patch.object(logistica_service, "authorize_google_call") as reserve,
                patch.object(logistica_service, "_http_post_json", return_value={"routes": [{"distanceMeters": 10000, "duration": "1200s"}]}) as network,
            ):
                for _ in range(2):
                    # Independent sessions prove this is persistent cache reuse.
                    with factory() as db:
                        result = logistica_service.obter_duracao_deslocamento_entidades(db, origem=origin, destino=destination)
                        self.assertEqual(result, (20, "google_routes_api_traffic"))
                        rows = db.query(ClinicaDeslocamento).all()
                        self.assertTrue(all(row.updated_at > expired for row in rows))
                self.assertEqual(network.call_count, 1)
                self.assertEqual(reserve.call_count, 1)
            engine.dispose()

    def test_manual_route_is_not_replaced_or_renewed(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + str(Path(directory) / "manual.db"))
            ClinicaDeslocamento.__table__.create(engine)
            with sessionmaker(bind=engine)() as db:
                old = datetime.utcnow() - timedelta(days=90)
                db.add(ClinicaDeslocamento(origem_clinica_id=1, destino_clinica_id=2,
                    perfil="comercial", distancia_km=1, duracao_min=10,
                    fonte="manual", manual_override=True, updated_at=old))
                db.commit()
                row, changed, skipped = logistica_service.upsert_deslocamento(db,
                    origem_clinica_id=1, destino_clinica_id=2, perfil="comercial",
                    distancia_km=20, duracao_min=30, fonte="google_routes_api")
                self.assertEqual((changed, skipped, row.fonte, row.updated_at), (False, True, "manual", old))
            engine.dispose()
