import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "logistica-google-cost-report-test-secret-key-1234567890")

from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.google_maps_usage_metrica import GoogleMapsUsageMetrica
from app.services.logistica_service import resumir_google_maps_metricas
from app.services import logistica_service


class LogisticaGoogleCostReportTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Clinica.__table__.create(engine)
        ClinicaDeslocamento.__table__.create(engine)
        GoogleMapsUsageMetrica.__table__.create(engine)
        Session = sessionmaker(bind=engine)
        self.db = Session()

        self.db.add_all(
            [
                Clinica(id=1, nome="Alpha", ativo=True, latitude=-3.72, longitude=-38.52),
                Clinica(id=2, nome="Beta", ativo=True, latitude=-3.81, longitude=-38.61),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_resumo_google_maps_inclui_estimativa_custos_e_quotas(self) -> None:
        now = datetime.utcnow()
        self.db.add_all(
            [
                GoogleMapsUsageMetrica(
                    service="routes",
                    operation="compute_routes",
                    provider="routes_api_basic",
                    status="ok",
                    created_at=now - timedelta(days=1),
                ),
                GoogleMapsUsageMetrica(
                    service="routes",
                    operation="compute_routes",
                    provider="routes_api_basic",
                    status="ok",
                    created_at=now - timedelta(days=1),
                ),
                GoogleMapsUsageMetrica(
                    service="routes",
                    operation="compute_routes",
                    provider="routes_api_traffic",
                    status="ok",
                    created_at=now - timedelta(days=2),
                ),
                GoogleMapsUsageMetrica(
                    service="routes",
                    operation="distance_matrix",
                    provider="distance_matrix_basic",
                    status="empty",
                    created_at=now - timedelta(days=2),
                ),
                GoogleMapsUsageMetrica(
                    service="routes",
                    operation="distance_matrix",
                    provider="distance_matrix_traffic",
                    status="error",
                    created_at=now - timedelta(days=3),
                ),
                GoogleMapsUsageMetrica(
                    service="routes",
                    operation="google_lookup_skipped",
                    provider="local_policy",
                    status="skipped",
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
        self.db.commit()

        pricing_teste = {
            "routes_compute_routes_essentials": {
                "label": "Routes: Compute Routes Essentials",
                "free_cap": 0,
                "tiers": [(None, 1000.0)],
            },
            "routes_compute_routes_pro": {
                "label": "Routes: Compute Routes Pro",
                "free_cap": 0,
                "tiers": [(None, 2000.0)],
            },
            "distance_matrix_legacy_basic": {
                "label": "Distance Matrix (Legacy)",
                "free_cap": 0,
                "tiers": [(None, 3000.0)],
            },
            "distance_matrix_legacy_advanced": {
                "label": "Distance Matrix Advanced (Legacy)",
                "free_cap": 0,
                "tiers": [(None, 4000.0)],
            },
        }

        with patch.object(logistica_service, "GOOGLE_MAPS_SKU_PRICING", pricing_teste):
            out = resumir_google_maps_metricas(self.db, dias=30, incluir_inativas=False)

        self.assertIn("cost_and_quotas", out)
        cost_and_quotas = out["cost_and_quotas"]
        conservador = cost_and_quotas["estimated_costs"]["conservador"]
        teto_pratico = cost_and_quotas["estimated_costs"]["teto_pratico"]

        # Conservador conta somente status ok: 2x basic routes + 1x routes pro = 4 USD no modelo de teste.
        self.assertEqual(conservador["estimated_total_cost_window_usd"], 4.0)
        # Teto pratico inclui ok + empty + error: +1x dm basic +1x dm advanced = 11 USD.
        self.assertEqual(teto_pratico["estimated_total_cost_window_usd"], 11.0)

        quotas = cost_and_quotas["quota_recommendations"]
        self.assertGreaterEqual(quotas["routes_api"]["daily_quota_recommended_requests"], 200)
        self.assertEqual(quotas["routes_api"]["qpm_hard_limit_google"], 3000)
        self.assertEqual(quotas["distance_matrix_legacy"]["epm_hard_limit_google"], 60000)


if __name__ == "__main__":
    unittest.main()
