import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "referencia-eco-defaults-test-secret-key-1234567890")

from app.utils.referencia_eco_defaults import aplicar_defaults_publicados_caninos
from app.utils.referencia_eco_defaults import normalizar_especie_referencia, obter_tapse_canino_por_peso
from app.api.v1.endpoints.referencias_eco import buscar_referencia_por_peso
from app.models.referencia_eco import ReferenciaEco
from app.services.ai_echo_context import load_echo_reference_context


class ReferenciaEcoDefaultsTest(unittest.TestCase):
    def test_canine_m_mode_fs_uses_visser_only_for_matching_default_and_weight(self) -> None:
        result = aplicar_defaults_publicados_caninos({
            "especie": "Canina", "peso_kg": 10, "fs_min": 25, "fs_max": 45,
            "ef_min": 50, "ef_max": 85,
        })
        self.assertEqual((result["fs_min"], result["fs_max"]), (20.7, 51.9))
        self.assertIn("Visser", result["fs_source"])
        self.assertIsNone(result["ef_min"])
        self.assertIsNone(result["ef_max"])
        repeated = aplicar_defaults_publicados_caninos(result)
        self.assertEqual((repeated["fs_min"], repeated["fs_max"]), (20.7, 51.9))
        for weight, minimum, maximum in ((2.5, 25, 45), (68, 25, 45), (10, 30, 50)):
            with self.subTest(weight=weight, minimum=minimum):
                unsafe = aplicar_defaults_publicados_caninos({
                    "especie": "Canina", "peso_kg": weight,
                    "fs_min": minimum, "fs_max": maximum,
                })
                self.assertIsNone(unsafe["fs_min"])
                self.assertIsNone(unsafe["fs_max"])

    def test_feline_fs_preserves_only_haggstrom_table_values(self) -> None:
        for weight, upper in ((1.5, 62), (9.5, 63), (10.5, 63)):
            with self.subTest(weight=weight):
                result = aplicar_defaults_publicados_caninos({
                    "especie": "Felina", "peso_kg": weight,
                    "fs_min": 28, "fs_max": upper,
                    "ef_min": 72, "ef_max": 85,
                })
                self.assertEqual((result["fs_min"], result["fs_max"]), (28, upper))
                self.assertIn("Häggström", result["fs_source"])
                self.assertIsNone(result["ef_min"])
        unsupported = aplicar_defaults_publicados_caninos({
            "especie": "Felina", "peso_kg": 5,
            "fs_min": 40, "fs_max": 62,
        })
        self.assertIsNone(unsupported["fs_min"])

    def test_ai_context_does_not_attach_m_mode_or_ef_range_to_2d(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ReferenciaEco.__table__.create(engine)
        db = sessionmaker(bind=engine)()
        try:
            db.add(ReferenciaEco(
                especie="Canina", peso_kg=10,
                fs_min=25, fs_max=45, ef_min=50, ef_max=85,
                lvid_d_min=20, lvid_d_max=40,
            ))
            db.commit()
            ranges = load_echo_reference_context(db, species="Canina", weight_kg=10)["ranges"]
            self.assertEqual(ranges["DeltaD_FS"]["min"], 20.7)
            self.assertNotIn("FE_Teicholz", ranges)
            self.assertNotIn("FE_Teicholz_2D", ranges)
            self.assertNotIn("DeltaD_FS_2D", ranges)
            self.assertNotIn("DIVEd_2D", ranges)
        finally:
            db.close()
            engine.dispose()

    def test_aliases_explicitos_nao_transformam_outras_especies_em_felinos_ou_caninos(self) -> None:
        for especie, esperada in (
            ("Felina", "Felina"), ("Gato", "Felina"), ("Cat", "Felina"),
            ("Caninos", "Canina"), ("Cão", "Canina"), ("Dogs", "Canina"),
            ("Cattle", "Cattle"), ("Bobcat", "Bobcat"), ("Canguru", "Canguru"),
        ):
            with self.subTest(especie=especie):
                self.assertEqual(normalizar_especie_referencia(especie), esperada)

    def test_busca_de_referencia_nao_aplica_faixa_felina_a_cattle(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ReferenciaEco.__table__.create(engine)
        db = sessionmaker(bind=engine)()
        try:
            db.add_all([
                ReferenciaEco(especie="Felina", peso_kg=5.0),
                ReferenciaEco(especie="Canina", peso_kg=5.0),
            ])
            db.commit()
            with self.assertRaises(HTTPException) as erro:
                buscar_referencia_por_peso("Cattle", 5.0, db, SimpleNamespace())
            self.assertEqual(erro.exception.status_code, 404)
            self.assertEqual(
                buscar_referencia_por_peso("Gato", 5.0, db, SimpleNamespace())["especie"],
                "Felina",
            )
            self.assertEqual(
                buscar_referencia_por_peso("Cão", 5.0, db, SimpleNamespace())["especie"],
                "Canina",
            )
        finally:
            db.close()
            engine.dispose()

    def test_obter_tapse_canino_por_peso_usa_peso_publicado_mais_proximo(self) -> None:
        self.assertEqual(obter_tapse_canino_por_peso(6.3), (8.5, 13.6))
        self.assertEqual(obter_tapse_canino_por_peso(13.3), (10.0, 16.0))

    def test_aplicar_defaults_caninos_nao_inventa_faixa_mapse(self) -> None:
        referencia = aplicar_defaults_publicados_caninos(
            {
                "especie": "Canina",
                "peso_kg": 6.0,
                "tapse_min": None,
                "tapse_max": None,
                "mapse_min": None,
                "mapse_max": None,
            },
            peso_kg=6.3,
            medidas={"TAPSE_metodo": "modo_m_apical"},
        )

        self.assertEqual(referencia["tapse_min"], 8.5)
        self.assertEqual(referencia["tapse_max"], 13.6)
        self.assertEqual(referencia["tapse_source"], "Visser et al. 2015")
        self.assertIsNone(referencia["mapse_min"])
        self.assertIsNone(referencia["mapse_max"])

    def test_tapse_fora_da_tabela_nao_reutiliza_extremo(self) -> None:
        for peso in (2.0, 50.0):
            with self.subTest(peso=peso):
                referencia = aplicar_defaults_publicados_caninos({
                    "especie": "Canina", "peso_kg": peso,
                    "tapse_min": None, "tapse_max": None,
                })
                self.assertIsNone(referencia["tapse_min"])
                self.assertIsNone(referencia["tapse_max"])

        referencia_45_kg = aplicar_defaults_publicados_caninos({
            "especie": "Canina", "peso_kg": 45.0,
            "tapse_min": None, "tapse_max": None,
        }, medidas={"TAPSE_metodo": "modo_m_apical"})
        self.assertEqual((referencia_45_kg["tapse_min"], referencia_45_kg["tapse_max"]), (14.8, 23.7))

    def test_aplicar_defaults_publicados_caninos_preserva_valores_existentes(self) -> None:
        referencia = aplicar_defaults_publicados_caninos(
            {
                "especie": "Canina",
                "peso_kg": 20.0,
                "tapse_min": 1.0,
                "tapse_max": 2.0,
                "mapse_min": 3.0,
                "mapse_max": 4.0,
            },
            peso_kg=20.0,
        )

        self.assertIsNone(referencia["tapse_min"])
        self.assertIsNone(referencia["tapse_max"])
        self.assertEqual(referencia["catalog_ranges"]["tapse"], {"min": 1.0, "max": 2.0})
        self.assertEqual(referencia["mapse_min"], 3.0)
        self.assertEqual(referencia["mapse_max"], 4.0)


if __name__ == "__main__":
    unittest.main()
