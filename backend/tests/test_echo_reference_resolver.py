"""Clinical comparison policy and non-destructive CSV ingestion regressions."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from pydantic import ValidationError
from fastapi import HTTPException

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "echo-reference-policy-test-secret-key-1234567890")

from app.api.v1.endpoints.referencias_eco import (
    _importar_csv_from_content, buscar_referencia_por_peso, listar_referencias,
    ReferenciaEcoCreate, ReferenciaEcoUpdate, atualizar_referencia,
)
from app.models.referencia_eco import ReferenciaEco
from app.services.echo_reference_resolver import (
    POLICY_VERSION, resolve_echo_reference, select_echo_reference,
)


class EchoReferenceResolverTest(unittest.TestCase):
    def test_reimported_cornell_25kg_typo_never_becomes_comparable_again(self):
        raw = {"especie": "Canina", "peso_kg": 25, "lvid_d_min": 33, "lvid_d_max": 42}
        result = resolve_echo_reference(raw)
        self.assertIsNone(result["lvid_d_max"])
        self.assertEqual(result["catalog_ranges"]["lvid_d"], {"min": 33, "max": 42})
        self.assertEqual(result["range_metadata"]["lvid_d"]["status"], "blocked")
        self.assertIn("33–48", result["range_metadata"]["lvid_d"]["reason"])
        for low, high in ((33, 48), (34, 42)):
            custom = resolve_echo_reference({**raw, "lvid_d_min": low, "lvid_d_max": high})
            self.assertEqual((custom["lvid_d_min"], custom["lvid_d_max"]), (low, high))

    def test_method_candidates_are_not_ranges_until_exam_confirmation(self):
        raw = {"especie": "Canina", "peso_kg": 15, "tapse_min": None, "tapse_max": None}
        unknown = resolve_echo_reference(raw)
        self.assertIsNone(unknown["tapse_min"])
        meta = unknown["range_metadata"]["tapse"]
        self.assertEqual(meta["status"], "requires_method")
        self.assertEqual((meta["candidate_min"], meta["candidate_max"]), (10.7, 17.1))
        self.assertEqual(meta["required_measurement_key"], "TAPSE_metodo")
        for method in ("2d", "outro", "nao_informado"):
            self.assertIsNone(resolve_echo_reference(raw, medidas={"TAPSE_metodo": method})["tapse_min"])
        confirmed = resolve_echo_reference(raw, medidas={"TAPSE_metodo": "modo_m_apical"})
        self.assertEqual((confirmed["tapse_min"], confirmed["tapse_max"]), (10.7, 17.1))
        self.assertEqual(confirmed["range_metadata"]["tapse"]["status"], "published")
        self.assertEqual(resolve_echo_reference(confirmed), confirmed)
        # Explicitly removing the exam confirmation removes the safe bounds.
        self.assertIsNone(resolve_echo_reference(confirmed, medidas={})["tapse_min"])

    def test_feline_ao_ratio_separates_prediction_interval_and_clinical_threshold(self):
        for weight, lower, upper in ((1.5, .85, 1.4), (4, .88, 1.43), (10.5, .94, 1.49), (11, .94, 1.5)):
            raw = {"especie": "Felina", "peso_kg": weight, "la_ao_min": lower, "la_ao_max": 1.5}
            unknown = resolve_echo_reference(raw)
            self.assertIsNone(unknown["la_ao_min"])
            self.assertEqual(unknown["range_metadata"]["la_ao"]["status"], "requires_method")
            confirmed = resolve_echo_reference(raw, medidas={"AE_Ao_metodo": "2d_eixo_curto_diastole_inicial"})
            self.assertEqual((confirmed["la_ao_min"], confirmed["la_ao_max"]), (lower, upper))
            self.assertEqual(confirmed["catalog_ranges"]["la_ao"], {"min": lower, "max": 1.5})
            threshold = confirmed["range_metadata"]["la_ao"]["clinical_threshold"]
            self.assertEqual((threshold["operator"], threshold["value"]), ("<", 1.5))
            self.assertEqual(resolve_echo_reference(confirmed), confirmed)
        custom = resolve_echo_reference({"especie": "Felina", "peso_kg": 4, "la_ao_min": .9, "la_ao_max": 1.6},
                                        medidas={"AE_Ao_metodo": "2d_eixo_curto_diastole_inicial"})
        self.assertIsNone(custom["la_ao_max"])
        self.assertEqual(custom["range_metadata"]["la_ao"]["status"], "blocked")

    def test_risky_legacy_bounds_remain_raw_without_automatic_comparison(self):
        for velocity in ((0, 2.2), (.5, 1.5)):
            raw = {"especie": "Canina", "peso_kg": 15,
                   "vmax_ao_min": velocity[0], "vmax_ao_max": velocity[1],
                   "mv_e_min": .5, "mv_e_max": 1.09, "mv_a_min": .3, "mv_a_max": .8,
                   "mv_dt_min": 0, "mv_dt_max": 160, "ef_min": 50, "ef_max": 85,
                   "la_ao_min": .8, "la_ao_max": 1.6}
            result = resolve_echo_reference(raw)
            for prefix in ("vmax_ao", "vmax_pulm", "mv_e", "mv_a", "mv_dt", "ef", "la_ao"):
                self.assertIsNone(result[f"{prefix}_min"])
                self.assertEqual(result["range_metadata"][prefix]["status"], "blocked")
            self.assertEqual(result["catalog_ranges"]["vmax_ao"], {"min": velocity[0], "max": velocity[1]})
            self.assertEqual(resolve_echo_reference(result), result)

    def test_custom_catalog_intervals_do_not_gain_guessed_publications(self):
        raw = {"especie": "Canina", "peso_kg": 15, "mv_e_min": .7, "mv_e_max": 1.2,
               "mapse_min": 3, "mapse_max": 4, "lvid_d_min": 25, "lvid_d_max": 35,
               "tapse_min": 3, "tapse_max": 10}
        result = resolve_echo_reference(raw, medidas={"TAPSE_metodo": "modo_m_apical"})
        for prefix in ("mv_e", "mapse", "lvid_d"):
            self.assertEqual(result[f"{prefix}_min"], raw[f"{prefix}_min"])
            self.assertEqual(result["range_metadata"][prefix]["status"], "catalog")
            self.assertIsNone(result["range_metadata"][prefix]["doi"])
        self.assertIsNone(result["tapse_min"])
        for bounds in ((6.5, 7.5), (10.3, 11.3), (12.1, 18.1)):
            ci = resolve_echo_reference({"especie": "Canina", "peso_kg": 15,
                                         "mapse_min": bounds[0], "mapse_max": bounds[1]})
            self.assertIsNone(ci["mapse_min"])
            self.assertEqual(ci["range_metadata"]["mapse"]["statistic"], "confidence_interval_mean")

    def test_nearest_selector_limits_eligible_catalog_coverage_and_ties(self):
        rows = [{"especie": "Canina", "peso_kg": weight, "lvid_d_min": 20, "lvid_d_max": 40}
                for weight in (.9, 5, 15, 25)]
        for weight in (1, 3, 26, 100):
            result = select_echo_reference(rows, peso_kg=weight)
            self.assertIsNone(result["lvid_d_min"])
            self.assertEqual(result["catalog_ranges"]["lvid_d"], {"min": 20, "max": 40})
            self.assertEqual(resolve_echo_reference(result), result)
        middle = select_echo_reference(rows, peso_kg=10)
        self.assertEqual(middle["peso_kg"], 5)
        self.assertEqual((middle["catalog_weight_min"], middle["catalog_weight_max"]), (5, 25))
        self.assertEqual(middle["lvid_d_min"], 20)
        self.assertIsNone(select_echo_reference(rows, peso_kg=float("inf")))

    def test_invalid_requested_weight_and_zero_placeholder_never_create_ranges(self):
        raw = {"especie": "Canina", "peso_kg": 15, "lvid_d_min": 20, "lvid_d_max": 40,
               "mv_e_min": 0, "mv_e_max": 0}
        zero = resolve_echo_reference(raw)
        self.assertIsNone(zero["mv_e_min"])
        self.assertEqual(zero["range_metadata"]["mv_e"]["status"], "unavailable")
        self.assertEqual(zero["catalog_ranges"]["mv_e"], {"min": 0, "max": 0})
        for invalid in (float("nan"), float("inf"), 0, -1, "inválido"):
            result = resolve_echo_reference(raw, peso_kg=invalid)
            self.assertIsNone(result["lvid_d_min"])
            self.assertIsNone(result["patient_weight_kg"])
            self.assertEqual(resolve_echo_reference(result), result)


class ReferenceCsvSafetyTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        ReferenciaEco.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([ReferenciaEco(especie="Canina", peso_kg=15, lvid_d_min=26, lvid_d_max=36),
                         ReferenciaEco(especie="Felina", peso_kg=4, lvid_d_min=12, lvid_d_max=22)])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _assert_original_catalog(self):
        rows = self.db.query(ReferenciaEco).order_by(ReferenciaEco.especie).all()
        self.assertEqual([(r.especie, r.peso_kg, r.lvid_d_min, r.lvid_d_max) for r in rows],
                         [("Canina", 15, 26, 36), ("Felina", 4, 12, 22)])

    def test_invalid_csv_never_deletes_existing_species(self):
        for bad in ("0,20,30", "-1,20,30", "nan,20,30", "inf,20,30", "10,x,30",
                    "10,nan,30", "10,31,30", "10,20", "10,20,30,40", "10,20,30\n5,20,30"):
            # Valid first row must also survive when a later row fails.
            content = "Peso (kg),LVIDd_Min,LVIDd_Max\n5,20,30\n" + bad
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _importar_csv_from_content(content, "Canina", self.db)
                self._assert_original_catalog()
        for empty in ("", "Peso (kg),LVIDd_Min,LVIDd_Max\n", "LVIDd_Min,LVIDd_Max\n20,30"):
            with self.assertRaises(ValueError):
                _importar_csv_from_content(empty, "Canina", self.db)
            self._assert_original_catalog()

    def test_valid_csv_preserves_raw_numbers_and_other_species(self):
        count = _importar_csv_from_content("Peso (kg),LVIDd_Min,LVIDd_Max,EF_Min,EF_Max\n5,20,30,50,85\n", "Canina", self.db)
        self.assertEqual(count, 1)
        canine = self.db.query(ReferenciaEco).filter(ReferenciaEco.especie == "Canina").one()
        self.assertEqual((canine.ef_min, canine.ef_max), (50, 85))
        result = buscar_referencia_por_peso("Canina", 5, self.db, SimpleNamespace())
        self.assertIsNone(result["ef_min"])
        self.assertEqual(result["catalog_ranges"]["ef"], {"min": 50, "max": 85})
        self.assertEqual(result["policy_version"], POLICY_VERSION)
        self.assertEqual(self.db.query(ReferenciaEco).filter(ReferenciaEco.especie == "Felina").one().peso_kg, 4)

    def test_api_list_and_search_share_method_and_coverage_policy(self):
        listing = listar_referencias(db=self.db, current_user=SimpleNamespace())
        self.assertEqual(listing["policy_version"], POLICY_VERSION)
        unknown = buscar_referencia_por_peso("Canina", 15, self.db, SimpleNamespace())
        confirmed = buscar_referencia_por_peso("Canina", 15, self.db, SimpleNamespace(), TAPSE_metodo="modo_m_apical")
        self.assertIsNone(unknown["tapse_min"])
        self.assertEqual(confirmed["tapse_min"], 10.7)
        outside = buscar_referencia_por_peso("Canina", 30, self.db, SimpleNamespace())
        self.assertIsNone(outside["lvid_d_min"])

    def test_manual_edits_validate_finite_numbers_and_merged_interval(self):
        for values in ({"peso_kg": 0}, {"peso_kg": float("inf")},
                       {"lvid_d_min": float("nan")}, {"lvid_d_min": 30, "lvid_d_max": 20}):
            with self.assertRaises(ValidationError):
                ReferenciaEcoCreate.model_validate({"especie": "Canina", "peso_kg": 10, **values})
        canine = self.db.query(ReferenciaEco).filter(ReferenciaEco.especie == "Canina").one()
        with self.assertRaises(HTTPException) as error:
            atualizar_referencia(canine.id, ReferenciaEcoUpdate(lvid_d_min=40), self.db, SimpleNamespace())
        self.assertEqual(error.exception.status_code, 422)
        self._assert_original_catalog()
        updated = atualizar_referencia(canine.id, ReferenciaEcoUpdate(lvid_d_min=25), self.db, SimpleNamespace())
        self.assertEqual(updated["catalog_ranges"]["lvid_d"], {"min": 25, "max": 36})


if __name__ == "__main__":
    unittest.main()
