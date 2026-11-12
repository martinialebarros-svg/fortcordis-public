"""Low-weight fallback must not manufacture reference intervals or alter catalogs."""
import math
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.services.echo_reference_resolver import resolve_echo_reference, select_echo_reference


class LowWeightReferenceTest(unittest.TestCase):
    def test_below_first_catalog_row_uses_toy_model_for_six_m_mode_dimensions(self):
        row = {"id": 7, "especie": "Canina", "peso_kg": 3, "patient_age": "5 anos", "lvid_d_min": 17, "lvid_d_max": 25}
        original = deepcopy(row)
        result = select_echo_reference([row], peso_kg=2.5)
        self.assertAlmostEqual(result["lvid_d_min"], round(10 * 1.02 * 2.5 ** .332, 2))
        self.assertAlmostEqual(result["lvid_d_max"], round(10 * 1.57 * 2.5 ** .332, 2))
        for prefix in ("lvid_d", "lvid_s", "ivs_d", "ivs_s", "lvpw_d", "lvpw_s"):
            self.assertGreater(result[f"{prefix}_min"], 0)
            meta = result["range_metadata"][prefix]
            self.assertEqual(meta["doi"], "10.3389/fvets.2022.918457")
            self.assertEqual(meta["model_weight_kg"], 2.5)
        self.assertEqual(result["catalog_ranges"]["lvid_d"], {"min": 17, "max": 25})
        self.assertEqual(row, original)
        self.assertEqual(resolve_echo_reference(result), result)

    def test_below_tabulated_domain_only_neutral_estimates_are_available(self):
        for species in ("Canina", "Felina"):
            result = resolve_echo_reference({"especie": species, "peso_kg": 3}, peso_kg=1)
            self.assertIsNone(result["lvid_d_min"])
            self.assertIsNone(result["lvid_d_max"])
            meta = result["range_metadata"]["lvid_d"]
            self.assertEqual(meta["status"], "estimated")
            self.assertGreater(meta["estimate_min"], 0)
            self.assertGreater(meta["estimate_max"], meta["estimate_min"])
            self.assertEqual(resolve_echo_reference(result), result)
            for prefix in ("tapse", "la_ao", "ef", "vmax_ao", "vmax_pulm"):
                self.assertIsNone(result[f"{prefix}_min"])

    def test_valid_custom_row_is_not_replaced_by_a_model(self):
        row = {"especie": "Canina", "peso_kg": 2.5, "lvid_d_min": 16, "lvid_d_max": 24}
        result = select_echo_reference([row], peso_kg=2.5)
        self.assertEqual((result["lvid_d_min"], result["lvid_d_max"]), (16, 24))
        self.assertEqual(result["range_metadata"]["lvid_d"]["status"], "catalog")

    def test_weight_changes_never_reuse_model_or_estimate_from_previous_weight(self):
        raw = {"especie": "Canina", "peso_kg": 3, "patient_age": "5 anos", "lvid_d_min": 17, "lvid_d_max": 25}
        first = resolve_echo_reference(raw, peso_kg=2, catalog_weight_min=3, catalog_weight_max=3)
        second = resolve_echo_reference(first, peso_kg=2.5)
        self.assertNotEqual(first["lvid_d_min"], second["lvid_d_min"])
        self.assertEqual(second["range_metadata"]["lvid_d"]["model_weight_kg"], 2.5)
        restored = resolve_echo_reference(second, peso_kg=3)
        self.assertEqual((restored["lvid_d_min"], restored["lvid_d_max"]), (17, 25))
        self.assertNotIn("model_weight_kg", restored["range_metadata"]["lvid_d"])

    def test_invalid_weight_unknown_species_and_3kg_boundary_do_not_trigger_fallback(self):
        for weight in (0, -1, math.nan, math.inf, "invalid", ""):
            result = resolve_echo_reference({"especie": "Canina", "peso_kg": 3}, peso_kg=weight)
            self.assertIsNone(result["lvid_d_min"])
            self.assertNotEqual(result["range_metadata"]["lvid_d"]["status"], "estimated")
        for species in ("Equina", "gato-selvagem", "dogfish"):
            result = resolve_echo_reference({"especie": species, "peso_kg": 3}, peso_kg=2)
            self.assertIsNone(result["lvid_d_min"])
        self.assertIsNone(resolve_echo_reference({"especie": "Canina", "peso_kg": 3}, peso_kg=3)["lvid_d_min"])

    def test_feline_tabulated_2kg_and_intermediate_weight_are_traceable(self):
        raw = {"especie": "Gato", "peso_kg": 3, "patient_age": "5 anos"}
        exact = resolve_echo_reference(raw, peso_kg=2)
        self.assertEqual((exact["lvid_d_min"], exact["lvid_d_max"]), (10.2, 16))
        self.assertEqual(exact["range_metadata"]["lvid_d"]["doi"], "10.1111/jvim.14569")
        middle = resolve_echo_reference(raw, peso_kg=1.75)
        self.assertEqual((middle["lvid_d_min"], middle["lvid_d_max"]), (9.85, 15.5))
        self.assertEqual(middle["range_metadata"]["lvid_d"]["calculation"], "interpolated")
        self.assertIn("interpola", middle["range_metadata"]["lvid_d"]["reason"].lower())
        half = resolve_echo_reference(raw, peso_kg=1.5625)
        self.assertEqual(half["lvid_d_max"], 15.13)

    def test_age_guard_is_conservative_and_never_applies_adult_model_to_known_juvenile(self):
        from app.utils.echo_low_weight_reference import low_weight_age_context
        for age in ("7m", "6 meses", "80 dias", "10 weeks", "filhote", "juvenil", "0,5 ano"):
            self.assertEqual(low_weight_age_context(age), "juvenile", age)
            result = resolve_echo_reference({"especie": "Canina", "peso_kg": 3}, peso_kg=2, idade=age)
            meta = result["range_metadata"]["lvid_d"]
            self.assertEqual(meta["status"], "unavailable")
            self.assertNotIn("estimate_min", meta)
            self.assertIsNone(result["lvid_d_min"])
        for age in ("1 ano", "2 anos e 3 meses", "18m", "adulto"):
            self.assertEqual(low_weight_age_context(age), "adult", age)
        for age in (None, "", "desconhecida", "1", "não adulto", "aproximadamente 5 anos"):
            self.assertEqual(low_weight_age_context(age), "unknown", age)
        unknown = resolve_echo_reference({"especie": "Felina", "peso_kg": 3}, peso_kg=2)
        self.assertIsNone(unknown["lvid_d_min"])
        self.assertEqual(unknown["range_metadata"]["lvid_d"]["estimate_context"], "age_unconfirmed")

    def test_empty_catalog_has_ephemeral_fallback_only_for_supported_species_and_low_weight(self):
        for species in ("Dog", "Gato"):
            result = select_echo_reference([], peso_kg=2.5, species=species, idade="5 anos")
            self.assertEqual(result["id"], 0)
            self.assertGreater(result["lvid_d_min"], 0)
            self.assertEqual(result["catalog_ranges"]["lvid_d"], {"min": None, "max": None})
        self.assertIsNone(select_echo_reference([], peso_kg=2.5, species="Equina", idade="5 anos"))
        self.assertIsNone(select_echo_reference([], peso_kg=3, species="Canina", idade="5 anos"))

    def test_m_mode_model_is_not_reused_as_2d_reference(self):
        raw = {"especie": "Canina", "peso_kg": 3}
        result = resolve_echo_reference(raw, peso_kg=2.7, idade="4 anos", medidas={"VE_tecnica_relatorio": "2d"})
        meta = result["range_metadata"]["lvid_d"]
        self.assertEqual(meta["status"], "unavailable")
        self.assertIsNone(result["lvid_d_min"])
        self.assertNotIn("estimate_min", meta)
        self.assertIn("2D", meta["reason"])
        self.assertEqual(resolve_echo_reference(result), result)
        restored = resolve_echo_reference(result, medidas={"VE_tecnica_relatorio": "modo_m"})
        self.assertGreater(restored["lvid_d_min"], 0)


if __name__ == "__main__":
    unittest.main()
