import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "echo-reference-safety-test-secret-1234567890")

from app.models.referencia_eco import ReferenciaEco
from app.services.ai_echo_context import (
    load_echo_reference_context, safe_measurement_context, safe_reference_context,
)
from app.services.echo_reference_resolver import load_echo_reference


class AIEchoReferenceSafetyTest(unittest.TestCase):
    LOW_WEIGHT_M_KEYS = {"DIVEd", "DIVES", "SIVd", "SIVs", "PLVEd", "PLVES"}

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        ReferenciaEco.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([
            ReferenciaEco(
                especie="Canina", peso_kg=10, lvid_d_min=20, lvid_d_max=40,
                fs_min=25, fs_max=45, vmax_ao_min=0, vmax_ao_max=2.2,
                vmax_pulm_min=0, vmax_pulm_max=2.2, mv_e_min=0.5, mv_e_max=1.09,
            ),
            ReferenciaEco(especie="Felina", peso_kg=4, la_ao_min=0.88, la_ao_max=1.5,
                          fs_min=28, fs_max=62),
        ])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_loader_sends_only_published_ranges_and_no_raw_or_candidate_catalog(self) -> None:
        context = load_echo_reference_context(self.db, species="Canina", weight_kg=10)
        ranges = context["ranges"]
        self.assertNotIn("DIVEd", ranges)
        self.assertNotIn("Vmax_aorta", ranges)
        self.assertNotIn("Vmax_pulmonar", ranges)
        self.assertNotIn("Onda_E", ranges)
        self.assertNotIn("TAPSE", ranges)
        self.assertEqual(ranges["DeltaD_FS"]["min"], 20.7)
        self.assertEqual(ranges["DeltaD_FS"]["doi"], "10.1111/jvim.15562")
        self.assertEqual(ranges["DeltaD_FS"]["statistic"], "reference_interval_95")
        serialized = json.dumps(context)
        self.assertNotIn("catalog_ranges", serialized)
        self.assertNotIn("candidate_min", serialized)
        self.assertNotIn("required_measurement_value", serialized)

    def test_adult_age_reaches_low_weight_loader_without_expanding_prompt_whitelist(self) -> None:
        measurements = {key: "5" for key in self.LOW_WEIGHT_M_KEYS}
        for species in ("Canina", "Felina", "Cão", "Dog", "Gato", "Cat"):
            for weight in (1.5, 2.25, 2.99):
                with self.subTest(species=species, weight=weight), patch(
                    "app.services.ai_echo_context.load_echo_reference", wraps=load_echo_reference,
                ) as resolver:
                    before = dict(measurements)
                    context = load_echo_reference_context(
                        self.db, species=species, weight_kg=weight, age="2a",
                        current_measurements=measurements,
                    )
                    self.assertEqual(resolver.call_args.kwargs["idade"], "2a")
                    self.assertTrue(self.LOW_WEIGHT_M_KEYS.issubset(context["ranges"]))
                    source_doi = ("10.3389/fvets.2022.918457" if context["species"] == "Canina"
                                  else "10.1111/jvim.14569")
                    for key in self.LOW_WEIGHT_M_KEYS:
                        self.assertEqual(context["ranges"][key]["doi"], source_doi)
                        self.assertIn("adult", context["ranges"][key]["population"])
                    # Resolved display intervals are not an authorization to
                    # expand the four-source clinical prompt contract.
                    safe = safe_reference_context(
                        context, current_measurements=measurements, species=species,
                    )
                    self.assertTrue(self.LOW_WEIGHT_M_KEYS.isdisjoint(safe["ranges"]))
                    safe_values = safe_measurement_context(
                        measurements, species=species, reference_context=context,
                    )
                    for key in self.LOW_WEIGHT_M_KEYS:
                        self.assertNotIn("reference", safe_values[key])
                    self.assertEqual(measurements, before)

    def test_low_weight_unknown_juvenile_extrapolated_and_2d_ranges_stay_out_of_prompt(self) -> None:
        for species in ("Canina", "Felina", "Dog", "Cat"):
            for age, weight, technique in (
                (None, 2.25, "modo_m"), ("idade incerta", 2.25, "modo_m"),
                ("7m", 2.25, "modo_m"), ("2a", 1.0, "modo_m"),
                ("2a", 2.25, "2d"),
            ):
                with self.subTest(species=species, age=age, weight=weight, technique=technique):
                    measurements = {key: "5" for key in self.LOW_WEIGHT_M_KEYS}
                    measurements["VE_tecnica_relatorio"] = technique
                    before = dict(measurements)
                    context = load_echo_reference_context(
                        self.db, species=species, weight_kg=weight, age=age,
                        current_measurements=measurements,
                    )
                    self.assertTrue(self.LOW_WEIGHT_M_KEYS.isdisjoint(context["ranges"]))
                    safe = safe_reference_context(
                        context, current_measurements=measurements, species=species,
                    )
                    self.assertTrue(self.LOW_WEIGHT_M_KEYS.isdisjoint(safe["ranges"]))
                    self.assertEqual(measurements, before)

    def test_age_aware_loader_preserves_the_four_published_prompt_sources(self) -> None:
        cases = (
            ("Canina", 10, {"DeltaD_FS": "40", "TAPSE": "12", "TAPSE_metodo": "modo_m_apical"},
             {"DeltaD_FS": "10.1111/jvim.15562", "TAPSE": "10.1016/j.jvc.2014.10.003"}),
            ("Felina", 4, {"DeltaD_FS": "40", "AE_Ao": "1.2",
                            "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial"},
             {"DeltaD_FS": "10.1111/jvim.14569", "AE_Ao": "10.1111/jvim.14569"}),
        )
        for species, weight, measurements, expected in cases:
            with self.subTest(species=species):
                context = load_echo_reference_context(
                    self.db, species=species, weight_kg=weight, age="2a",
                    current_measurements=measurements,
                )
                safe = safe_reference_context(
                    context, current_measurements=measurements, species=species,
                )
                self.assertEqual({key: value["doi"] for key, value in safe["ranges"].items()}, expected)

    def test_tapse_reference_requires_explicit_m_mode_apical_confirmation(self) -> None:
        for method in ("", "2d"):
            with self.subTest(method=method):
                context = load_echo_reference_context(
                    self.db, species="Canina", weight_kg=10,
                    current_measurements={"TAPSE": "12", "TAPSE_metodo": method},
                )
                self.assertNotIn("TAPSE", context["ranges"])
        measurements = {"TAPSE": "12", "TAPSE_metodo": "modo_m_apical"}
        context = load_echo_reference_context(
            self.db, species="Canina", weight_kg=10, current_measurements=measurements,
        )
        self.assertEqual(context["ranges"]["TAPSE"]["doi"], "10.1016/j.jvc.2014.10.003")
        self.assertEqual(context["ranges"]["TAPSE"]["min_weight_kg"], 3.0)
        self.assertEqual(context["ranges"]["TAPSE"]["max_weight_kg"], 45.0)
        self.assertIn("reference", safe_measurement_context(measurements, species="Canina", reference_context=context)["TAPSE"])

    def test_feline_ae_ao_candidate_never_enters_context_until_method_confirmed(self) -> None:
        for method in ("", "outro"):
            with self.subTest(method=method):
                context = load_echo_reference_context(
                    self.db, species="Felina", weight_kg=4,
                    current_measurements={"AE_Ao": "1.46", "AE_Ao_metodo": method},
                )
                self.assertNotIn("AE_Ao", context["ranges"])
        context = load_echo_reference_context(
            self.db, species="Felina", weight_kg=4,
            current_measurements={"AE_Ao": "1.46", "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial"},
        )
        self.assertEqual(context["ranges"]["AE_Ao"]["max"], 1.43)
        self.assertEqual(context["ranges"]["AE_Ao"]["statistic"], "prediction_interval_95")
        self.assertNotIn("clinical_threshold", context["ranges"]["AE_Ao"])

    def test_direct_context_cannot_attach_wrong_method_or_unsupported_bounds(self) -> None:
        ranges = {key: {"min": 0, "max": 2.2, "unit": "m/s"}
                  for key in ("Vmax_aorta", "Onda_E", "TAPSE", "AE_Ao", "DeltaD_FS")}
        measurements = {"Vmax_aorta": "1.26", "Onda_E": "0.8", "TAPSE": "12",
                        "TAPSE_metodo": "2d", "AE_Ao": "1.46", "DeltaD_FS": "40",
                        "VE_tecnica_relatorio": "2d"}
        context = safe_measurement_context(
            measurements, species="Felina", reference_context={"ranges": ranges},
        )
        for item in context.values():
            self.assertNotIn("reference", item)
        self.assertEqual(context["TAPSE"]["value"], "12")
        self.assertEqual(context["Vmax_aorta"]["value"], "1.26")

    def test_no_m_mode_range_for_selected_2d_and_no_range_outside_catalog_coverage(self) -> None:
        context = load_echo_reference_context(
            self.db, species="Canina", weight_kg=10,
            current_measurements={"VE_tecnica_relatorio": "2d", "DeltaD_FS_2D": "35"},
        )
        self.assertNotIn("DeltaD_FS", context["ranges"])
        context = load_echo_reference_context(self.db, species="Canina", weight_kg=20)
        self.assertEqual(context["ranges"], {})

    def test_confirmed_method_does_not_validate_a_stale_unsourced_range(self) -> None:
        measurements = {"TAPSE": "12", "TAPSE_metodo": "modo_m_apical"}
        stale_context = {"ranges": {"TAPSE": {"min": 0, "max": 99, "unit": "mm"}}}
        self.assertNotIn("reference", safe_measurement_context(
            measurements, species="Canina", reference_context=stale_context,
        )["TAPSE"])
        sourced_context = {"patient_weight_kg": 10, "ranges": {"TAPSE": {
            "min": 9.2, "max": 14.7, "unit": "mm", "source": "Visser et al. 2015",
            "doi": "10.1016/j.jvc.2014.10.003", "statistic": "prediction_interval_95",
        }}}
        self.assertIn("reference", safe_measurement_context(
            measurements, species="Canina", reference_context=sourced_context,
        )["TAPSE"])
        sourced_context["catalog_ranges"] = {"tapse": {"min": 0, "max": 99}}
        sourced_context["ranges"]["TAPSE"]["candidate_max"] = 99
        sanitized = safe_reference_context(
            sourced_context, current_measurements=measurements, species="Canina",
        )
        self.assertNotIn("catalog_ranges", sanitized)
        self.assertNotIn("candidate_max", sanitized["ranges"]["TAPSE"])
        self.assertEqual(safe_reference_context(
            stale_context, current_measurements=measurements, species="Canina",
        )["ranges"], {})

    def test_direct_published_context_requires_finite_weight_within_its_source_domain(self) -> None:
        cases = (
            ("Canina", "TAPSE", {"TAPSE_metodo": "modo_m_apical"}, 3.0, 45.0,
             "10.1016/j.jvc.2014.10.003", "prediction_interval_95", 9.2, 14.7),
            ("Canina", "DeltaD_FS", {}, 2.6, 67.8, "10.1111/jvim.15562", "reference_interval_95", 20.7, 51.9),
            ("Felina", "DeltaD_FS", {}, 1.5, 11.0, "10.1111/jvim.14569", "prediction_interval_95", 28, 62),
            ("Felina", "AE_Ao", {"AE_Ao_metodo": "2d_eixo_curto_diastole_inicial"},
             1.5, 11.0, "10.1111/jvim.14569", "prediction_interval_95", 0.88, 1.43),
        )
        for species, key, methods, min_weight, max_weight, doi, statistic, minimum, maximum in cases:
            measurements = {key: "12", **methods}
            reference = {"min": minimum, "max": maximum, "source": "Estudo publicado",
                         "doi": doi, "statistic": statistic, "min_weight_kg": min_weight,
                         "max_weight_kg": max_weight}
            for weight in (None, float("nan"), float("inf"), min_weight - 0.1, max_weight + 0.1, 100):
                with self.subTest(species=species, key=key, weight=weight):
                    context = {"patient_weight_kg": weight, "ranges": {key: reference}}
                    self.assertEqual(safe_reference_context(
                        context, current_measurements=measurements, species=species,
                    )["ranges"], {})
                    self.assertNotIn("reference", safe_measurement_context(
                        measurements, species=species, reference_context=context,
                    )[key])
            for weight in (min_weight, max_weight):
                with self.subTest(species=species, key=key, weight=weight):
                    context = {"patient_weight_kg": weight, "ranges": {key: reference}}
                    safe = safe_reference_context(context, current_measurements=measurements, species=species)
                    self.assertIn(key, safe["ranges"])
                    self.assertEqual(safe["ranges"][key]["min_weight_kg"], min_weight)
                    self.assertEqual(safe["ranges"][key]["max_weight_kg"], max_weight)


class AIEchoDiastolicReviewSafetyTest(unittest.TestCase):
    """Retained historical ratios are not clinical evidence after review loss."""

    MEASUREMENTS = {
        "Onda_E": "0.70", "Onda_A": "0.50", "TD": "90", "TRIV": "70",
        "e_doppler": "0.09", "a_doppler": "0.11", "E_A": "0.70",
        "E_TRIV": "0.55", "E_E_linha": "6.71", "doppler_tecidual_relacao": "0.58",
    }
    RATIOS = {"E_A", "E_TRIV", "E_E_linha", "doppler_tecidual_relacao"}

    def test_invalidated_review_excludes_only_dependent_indices_for_both_species(self) -> None:
        cases = (
            ("Diastolica_ondas", {"E_A", "E_TRIV", "E_E_linha"}, "doppler_tecidual_relacao"),
            ("TDI_ondas", {"doppler_tecidual_relacao", "E_E_linha"}, "E_A"),
        )
        for species in ("Canina", "Cão", "Dog", "Felina", "Gato", "Cat"):
            for wave_key, excluded, independent in cases:
                with self.subTest(species=species, domain=wave_key):
                    measurements = {**self.MEASUREMENTS, "Diastolica_ondas": "separadas",
                                    "TDI_ondas": "separadas", wave_key: "nao_confirmadas"}
                    before = dict(measurements)
                    safe = safe_measurement_context(measurements, species=species)
                    self.assertTrue(excluded.isdisjoint(safe), safe)
                    self.assertEqual(safe[independent]["value"], measurements[independent])
                    for key in ("Onda_E", "Onda_A", "TD", "TRIV", "e_doppler", "a_doppler"):
                        self.assertEqual(safe[key]["value"], measurements[key])
                    self.assertEqual(measurements, before)

    def test_explicit_canine_method_without_wave_confirmation_is_not_legacy(self) -> None:
        for methods in (
            {"Diastolica_metodo": "canino_nao_sedado_pw_apical", "TDI_metodo": "canino_pw_anel_septal_choi"},
            {"Diastolica_metodo": "outro", "TDI_metodo": "outro"},
        ):
            with self.subTest(methods=methods):
                safe = safe_measurement_context({**self.MEASUREMENTS, **methods}, species="Canina")
                self.assertTrue(self.RATIOS.isdisjoint(safe), safe)
                self.assertIn("TRIV", safe)
                self.assertIn("Onda_E", safe)
                self.assertIn("e_doppler", safe)

    def test_never_reviewed_canine_history_is_preserved_but_feline_unknown_is_guarded(self) -> None:
        for species in ("Canina", "Cão", "Dog"):
            with self.subTest(species=species):
                safe = safe_measurement_context(self.MEASUREMENTS, species=species)
                for key in self.RATIOS:
                    self.assertEqual(safe[key]["value"], self.MEASUREMENTS[key])
        for species in ("Felina", "Gato", "Cat"):
            with self.subTest(species=species):
                safe = safe_measurement_context(self.MEASUREMENTS, species=species)
                self.assertTrue(self.RATIOS.isdisjoint(safe), safe)
                self.assertIn("TRIV", safe)

    def test_explicit_reconfirmation_releases_stored_values_without_recalculation(self) -> None:
        for species in ("Canina", "Felina"):
            with self.subTest(species=species):
                measurements = {**self.MEASUREMENTS, "Diastolica_ondas": "separadas", "TDI_ondas": "separadas"}
                safe = safe_measurement_context(measurements, species=species)
                for key in self.RATIOS:
                    self.assertEqual(safe[key]["value"], self.MEASUREMENTS[key])

    def test_species_from_reference_context_gets_the_same_review_guard(self) -> None:
        safe = safe_measurement_context(
            {**self.MEASUREMENTS, "Diastolica_ondas": "nao_confirmadas", "TDI_ondas": "nao_confirmadas"},
            reference_context={"species": "Cat", "ranges": {}},
        )
        self.assertTrue(self.RATIOS.isdisjoint(safe), safe)
        self.assertIn("TRIV", safe)

    def test_confirmed_fusion_keeps_existing_peak_exclusion_independent(self) -> None:
        for species in ("Canina", "Felina"):
            with self.subTest(species=species):
                measurements = {**self.MEASUREMENTS, "Diastolica_ondas": "fundidas", "TDI_ondas": "separadas"}
                safe = safe_measurement_context(measurements, species=species)
                self.assertTrue({"Onda_E", "Onda_A", "E_A", "TD", "E_TRIV", "E_E_linha"}.isdisjoint(safe))
                self.assertIn("TRIV", safe)
                self.assertIn("e_doppler", safe)
                self.assertIn("doppler_tecidual_relacao", safe)


if __name__ == "__main__":
    unittest.main()
