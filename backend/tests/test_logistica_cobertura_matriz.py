import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "logistica-cobertura-test-secret-key-1234567890")

from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.services.logistica_service import resumir_cobertura_matriz_deslocamentos


class LogisticaCoberturaMatrizTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Clinica.__table__.create(engine)
        ClinicaDeslocamento.__table__.create(engine)
        Session = sessionmaker(bind=engine)
        self.db = Session()

        self.db.add_all(
            [
                Clinica(id=1, nome="Alpha", ativo=True, latitude=-3.72, longitude=-38.52, place_id=None),
                Clinica(id=2, nome="Beta", ativo=True, latitude=-3.81, longitude=-38.61, place_id="ChIJx"),
                Clinica(id=3, nome="Inativa", ativo=False, latitude=None, longitude=None),
            ]
        )
        self.db.commit()

        self.db.add_all(
            [
                ClinicaDeslocamento(
                    origem_clinica_id=1,
                    destino_clinica_id=2,
                    perfil="comercial",
                    distancia_km=Decimal("4.50"),
                    duracao_min=12,
                    fonte="google_routes_api_traffic",
                    manual_override=False,
                ),
                ClinicaDeslocamento(
                    origem_clinica_id=1,
                    destino_clinica_id=2,
                    perfil="plantao",
                    distancia_km=Decimal("4.50"),
                    duracao_min=11,
                    fonte="google_routes_api",
                    manual_override=False,
                ),
                ClinicaDeslocamento(
                    origem_clinica_id=2,
                    destino_clinica_id=1,
                    perfil="comercial",
                    distancia_km=Decimal("10.00"),
                    duracao_min=20,
                    fonte="heuristica_regional",
                    manual_override=False,
                ),
                ClinicaDeslocamento(
                    origem_clinica_id=1,
                    destino_clinica_id=1,
                    perfil="comercial",
                    distancia_km=Decimal("0"),
                    duracao_min=0,
                    fonte="manual",
                    manual_override=True,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_resumo_escopo_ativas_agrega_buckets(self) -> None:
        out = resumir_cobertura_matriz_deslocamentos(self.db, incluir_inativas=False)
        self.assertEqual(out["escopo"]["total_clinicas"], 2)
        buckets = out["matriz"]["por_bucket"]
        self.assertEqual(buckets.get("google_api"), 2)
        self.assertEqual(buckets.get("heuristica_local"), 1)
        self.assertEqual(buckets.get("manual_ou_override"), 1)
        self.assertEqual(out["matriz"]["linhas_no_escopo"], 4)
        self.assertEqual(out["matriz"]["celulas_teoricas"], 8)
        self.assertEqual(out["matriz"]["celulas_sem_linha_estimadas"], 4)
        self.assertEqual(out["clinicas_localizacao"]["com_latitude_longitude"], 2)
        self.assertEqual(out["clinicas_localizacao"]["com_place_id"], 1)
        self.assertIsNotNone(out["contexto"].get("linhas_fora_escopo_clinicas_ativas"))

    def test_incluir_inativas_inclui_terceira_clinica_no_escopo(self) -> None:
        out = resumir_cobertura_matriz_deslocamentos(self.db, incluir_inativas=True)
        self.assertEqual(out["escopo"]["total_clinicas"], 3)
        self.assertIsNone(out["contexto"].get("linhas_fora_escopo_clinicas_ativas"))


if __name__ == "__main__":
    unittest.main()
