"""Published pediatric RIs and neutral resolver/PDF boundaries; synthetic data."""
import json
import math
import os
import re
import sys
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "pediatric-echo-synthetic-tests-1234567890")

from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.referencia_eco import ReferenciaEco
from app.schemas.ai_echo import EchoStructureRequest
from app.services.ai_echo_context import load_echo_reference_context
from app.services.echo_reference_resolver import RANGE_PREFIXES, resolve_echo_reference, select_echo_reference
from app.utils.ecocardiograma_medidas import extrair_medidas_ecocardiograma_da_descricao
from app.utils.echo_feline_pediatric_reference import PEDIATRIC_DOI, feline_pediatric_reference, is_feline_pediatric_context, pediatric_age_weeks
from app.utils.pdf_laudo import aplicar_referencia_eco, gerar_pdf_laudo_eco

METHODS = {"Pediatria_protocolo": "gunther_harrington_2021_sem_sedacao", "VE_tecnica_relatorio": "modo_m",
           "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial"}
# Independent transcription of Supplement 1's comparison limits, in cm.
SOURCE_CM = {"DIVEd": (.86, 1.53), "DIVES": (.28, .84), "SIVd": (.21, .45),
             "SIVs": (.37, .72), "PLVEd": (.20, .45), "PLVES": (.38, .74),
             "DIVEd_2D": (.83, 1.40), "DIVES_2D": (.34, .88), "SIVd_2D": (.23, .44),
             "SIVs_2D": (.33, .71), "PLVEd_2D": (.20, .45), "PLVES_2D": (.34, .65),
             "Aorta": (.47, .78), "Atrio_esquerdo": (.63, 1.06)}


def resolved(age="3 meses", weight=1.3, methods=None):
    raw = {"especie": "Felina", "peso_kg": 4, "fs_source": "stale", "la_ao_source": "stale"}
    for prefix in RANGE_PREFIXES:
        raw.update({f"{prefix}_min": 1, f"{prefix}_max": 90})
    return resolve_echo_reference(raw, peso_kg=weight, idade=age, medidas=METHODS if methods is None else methods)


def report(methods=None, age="3 meses", weight=1.3):
    measurements = {"DIVEd": "12", "DIVES": "6", "SIVd": "3", "SIVs": "5", "PLVEd": "3", "PLVES": "5",
                    "DeltaD_FS": "50", "Aorta": "6", "Atrio_esquerdo": "8", "AE_Ao": "1.33",
                    "Vmax_aorta": "1", "Vmax_pulmonar": "0.9", "Ao_nivel_AP": "7", "AP": "6",
                    "Vmax_aorta_origem": "informado", "Vmax_pulmonar_origem": "informado"}
    measurements.update(METHODS if methods is None else methods)
    return {"paciente": {"nome": "QA PEDIATRIA SINTETICA", "tutor": "QA", "especie": "Felina",
                         "peso": str(weight), "idade": age, "sexo": "Fêmea", "raca": "SRD", "data_exame": "2026-11-25"},
            "medidas": measurements, "conclusao": "TESTE SINTETICO. Sem finalidade clínica.", "clinica": "QA"}


def render(payload):
    original = deepcopy(payload)
    content = gerar_pdf_laudo_eco(payload)
    assert original == payload
    pages = PdfReader(BytesIO(content)).pages
    return content, re.sub(r"\s+", " ", " ".join(page.extract_text() for page in pages))


class FelinePediatricReferenceTest(unittest.TestCase):
    def test_source_values_units_methods_and_statistics(self):
        m = resolved()["pediatric_reference"]["ranges"]
        two_d = resolved(methods={**METHODS, "VE_tecnica_relatorio": "2d", "VE_vista_2D": "eixo_longo"})["pediatric_reference"]["ranges"]
        self.assertEqual(len(m), 18)
        for key, (lower_cm, upper_cm) in SOURCE_CM.items():
            reference = two_d[key] if key.endswith("_2D") else m[key]
            self.assertAlmostEqual(reference["lower"], lower_cm * 10, places=8, msg=key)
            self.assertAlmostEqual(reference["upper"], upper_cm * 10, places=8, msg=key)
            self.assertEqual(reference["unit"], "mm")
            self.assertEqual(reference["status"], "descriptive")
            self.assertEqual(reference["statistic"], "published_cohort_reference_interval")
        for key, bounds in {"DeltaD_FS": (36.6, 68.6), "AE_Ao": (1.12, 1.63),
                            "Vmax_aorta": (.72, 1.39), "Vmax_pulmonar": (.53, 1.35)}.items():
            self.assertEqual((m[key]["lower"], m[key]["upper"]), bounds)
        self.assertEqual(m["DIVEd"]["text"], "8,60–15,30 mm (coorte pediátrica)")
        self.assertNotIn("Ao_nivel_AP", m)
        self.assertNotIn("DeltaD_FS_2D", m)

    def test_exact_age_boundaries_vague_and_untrusted_text(self):
        for age, weeks in (("42 dias", 6), ("6 semanas", 6), ("16w", 16), ("112d", 16),
                           ("3 meses", 3 * 30.4375 / 7), ("0,25 ano", .25 * 365.25 / 7),
                           ("2 meses e 1 semana", (2 * 30.4375 + 7) / 7),
                           ("3 meses (estimada)", 3 * 30.4375 / 7)):
            self.assertAlmostEqual(pediatric_age_weeks(age), weeks)
            self.assertEqual(resolved(age)["pediatric_reference"]["ranges"]["DIVEd"]["status"], "descriptive")
        for age in ("41dias", "113dias", "5semanas", "17semanas", "7meses", "filhote", "0–11 meses (estimada pelo ano)"):
            self.assertTrue(all(r["lower"] is None for r in resolved(age)["pediatric_reference"]["ranges"].values()))
        for age in (None, "", "3", "filhote", "2026", "-3meses", "3–4 meses", "aproximadamente 3m", "1m1m",
                    "1 mes e 1 month", "0–11 meses (estimada pelo ano)", "1–2 semanas", "−3 meses", "1—2 semanas"):
            self.assertIsNone(pediatric_age_weeks(age), age)
        for age in ("1–2 semanas", "−3 meses", "1—2 semanas"):
            self.assertTrue(all(r["lower"] is None for r in resolved(age)["pediatric_reference"]["ranges"].values()))

    def test_missing_protocol_and_specific_methods_never_create_ranges(self):
        for methods in ({}, {**METHODS, "Pediatria_protocolo": "outro"}):
            refs = resolved(methods=methods)["pediatric_reference"]["ranges"]
            self.assertTrue(all(r["status"] == "requires_method" and r["lower"] is None and not r["text"] for r in refs.values()))
        for methods in ({**METHODS, "VE_tecnica_relatorio": ""}, {**METHODS, "VE_tecnica_relatorio": "2d", "VE_vista_2D": "eixo_curto"}):
            refs = resolved(methods=methods)["pediatric_reference"]["ranges"]
            self.assertIsNone(refs["DIVEd"]["lower"])
            self.assertIsNone(refs["DIVEd_2D"]["lower"])
            self.assertEqual(refs["Vmax_aorta"]["status"], "descriptive")
        for method in ("", "outro", "2d_eixo_curto_diastole_inicial_sueco"):
            refs = resolved(methods={**METHODS, "AE_Ao_metodo": method})["pediatric_reference"]["ranges"]
            self.assertTrue(all(refs[k]["lower"] is None for k in ("Aorta", "Atrio_esquerdo", "AE_Ao")))

    def test_weight_is_required_but_no_observed_weight_domain_is_invented(self):
        for weight in (0, -1, None, math.nan, math.inf, "invalid", True):
            refs = feline_pediatric_reference("3meses", weight, METHODS)["ranges"]
            self.assertTrue(all(r["status"] == "unavailable" and r["lower"] is None for r in refs.values()))
        for weight in (.2, 1.3, 3, 4):
            r = select_echo_reference([], species="Felina", peso_kg=weight, idade="3meses", medidas=METHODS)
            self.assertEqual(r["pediatric_reference"]["ranges"]["DIVEd"]["lower"], 8.6)
            self.assertEqual(r["id"], 0)

    def test_complete_catalog_blocked_and_current_context_recomputed(self):
        result = resolved(weight=4)
        for prefix in RANGE_PREFIXES:
            self.assertIsNone(result[f"{prefix}_min"])
            self.assertIsNone(result[f"{prefix}_max"])
            self.assertEqual(result["catalog_ranges"][prefix], {"min": 1, "max": 90})
            self.assertNotEqual(result["range_metadata"][prefix]["status"], "published")
        self.assertNotIn("fs_source", result)
        self.assertNotIn("la_ao_source", result)
        self.assertEqual(resolve_echo_reference(result), result)
        no_method = resolve_echo_reference(result, medidas={})
        self.assertIsNone(no_method["pediatric_reference"]["ranges"]["DIVEd"]["lower"])
        for age in ("2anos", "", "idade desconhecida"):
            self.assertNotIn("pediatric_reference", resolve_echo_reference(result, idade=age))
        dog = resolve_echo_reference({**result, "especie": "Canina"}, idade="3meses")
        self.assertNotIn("pediatric_reference", dog)

    def test_age_ranges_guard_possible_juveniles_without_creating_a_precise_age(self):
        for age in ("1–2 meses", "1—2 meses", "1-2 meses", "6–18 months", "0,5–2 anos"):
            self.assertTrue(is_feline_pediatric_context("Felina", age), age)
            for result in (resolved(age, weight=4), select_echo_reference([], species="Felina", peso_kg=4, idade=age, medidas=METHODS)):
                self.assertIsNone(result["pediatric_reference"]["patient_age_weeks"])
                self.assertTrue(all(r["lower"] is None for r in result["pediatric_reference"]["ranges"].values()))
                self.assertTrue(all(result[f"{prefix}_min"] is None for prefix in RANGE_PREFIXES))
                self.assertEqual(resolve_echo_reference(result), result)
            _, text = render(report(age=age, weight=4))
            self.assertNotIn(PEDIATRIC_DOI, text)
            self.assertNotIn("Häggström", text)
        for age in ("1–2 anos", "12–18 meses", "2anos"):
            self.assertFalse(is_feline_pediatric_context("Felina", age), age)
            self.assertNotIn("pediatric_reference", resolved(age, weight=4))
        self.assertFalse(is_feline_pediatric_context("Canina", "1–2 meses"))

    def test_explicit_null_age_clears_cached_context_but_omission_preserves_it(self):
        original = resolved()
        self.assertEqual(resolve_echo_reference(original), original)
        cleared = resolve_echo_reference(original, idade=None)
        self.assertIsNone(cleared["patient_age"])
        self.assertNotIn("pediatric_reference", cleared)
        self.assertEqual(resolve_echo_reference(cleared), cleared)
        payload = report(age=None)
        payload["referencia_eco"] = original
        _, text = render(payload)
        self.assertNotIn(PEDIATRIC_DOI, text)

    def test_method_survives_request_validation_and_description_round_trip(self):
        request = EchoStructureRequest.model_validate({"edited_transcript": "Exame sintético.", "current_measurements": METHODS})
        self.assertEqual(request.current_measurements["Pediatria_protocolo"], METHODS["Pediatria_protocolo"])
        description = "## Medidas Ecocardiográficas\n" + "\n".join(f"- {k}: {v}" for k, v in METHODS.items())
        restored = extrair_medidas_ecocardiograma_da_descricao(description)
        self.assertEqual(restored, METHODS)
        invalid = description.replace(METHODS["Pediatria_protocolo"], "inventado")
        self.assertNotIn("Pediatria_protocolo", extrair_medidas_ecocardiograma_da_descricao(invalid))

    def test_ai_context_does_not_promote_cohort_intervals_to_classification(self):
        engine = create_engine("sqlite:///:memory:")
        ReferenciaEco.__table__.create(engine)
        with sessionmaker(bind=engine)() as db:
            context = load_echo_reference_context(db, species="Felina", weight_kg=1.3, age="3meses", current_measurements=METHODS)
            self.assertEqual(context["ranges"], {})
            self.assertNotIn(PEDIATRIC_DOI, json.dumps(context))
        engine.dispose()


class FelinePediatricPdfTest(unittest.TestCase):
    def test_pdf_is_neutral_specific_to_method_and_cites_only_displayed_source(self):
        payload = report()
        _, text = render(payload)
        self.assertIn("8,60–15,30 mm*", text)
        self.assertIn("36,60–68,60 %*", text)
        self.assertIn("0,72–1,39 m/s*", text)
        self.assertIn(PEDIATRIC_DOI, text)
        self.assertIn("não ajustados ao peso", text)
        self.assertIn("sem classificação automática", text)
        self.assertNotIn("Häggström", text)
        self.assertNotIn("Domanjko", text)
        self.assertRegex(text, r"Ao \(Aorta - nível AP\) 7\.00 mm --")
        params = aplicar_referencia_eco([{"chave": "DIVEd"}, {"chave": "AE_Ao"}, {"chave": "Ao_nivel_AP"}], resolved())
        self.assertTrue(all(p["ref_min"] is None and p["ref_max"] is None for p in params))
        self.assertNotIn("ref_text", params[-1])
        _, unconfirmed = render(report(methods={"VE_tecnica_relatorio": "modo_m"}))
        self.assertNotIn(PEDIATRIC_DOI, unconfirmed)
        self.assertNotIn("8,60–15,30", unconfirmed)
        for age in ("5semanas", "17semanas", "filhote", "2anos"):
            _, unavailable = render(report(age=age))
            self.assertNotIn(PEDIATRIC_DOI, unavailable)

    def test_2d_pdf_and_ambiguous_units(self):
        payload = report(methods={**METHODS, "VE_tecnica_relatorio": "2d", "VE_vista_2D": "eixo_longo"})
        payload["medidas"].update({f"{key}_2D": value for key, value in list(payload["medidas"].items()) if key in SOURCE_CM})
        _, text = render(payload)
        self.assertIn("8,30–14,00 mm*", text)
        self.assertNotIn("8,60–15,30", text)
        self.assertIn(PEDIATRIC_DOI, text)
        only_ambiguous = report()
        only_ambiguous["medidas"] = {**METHODS, "DIVEd": "1.2", "DIVES": "0.6", "SIVd": "0.3"}
        _, ambiguous = render(only_ambiguous)
        self.assertIn("unidade a confirmar", ambiguous)
        self.assertNotIn(PEDIATRIC_DOI, ambiguous)


if __name__ == "__main__":
    unittest.main()
