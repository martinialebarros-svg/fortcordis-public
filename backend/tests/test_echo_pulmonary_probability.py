import json
import os
import sys
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "pulmonary-probability-test-secret-key-1234567890")

from pypdf import PdfReader
from app.utils.echo_pulmonary_probability import (
    HP_CONTEXT_KEYS, canine_ph_probability, evaluate_pulmonary_probability,
    make_pulmonary_review_stamp, has_valid_pulmonary_review,
)
from app.api.v1.endpoints.laudos import _montar_descricao_ecocardiograma
from app.utils.ecocardiograma_medidas import extrair_medidas_ecocardiograma_da_descricao
from app.utils.pdf_laudo import gerar_pdf_laudo_eco
from app.services.ai_echo_context import safe_measurement_context


def reviewed(**updates):
    measures = {
        "HP_ativa": "sim", "HP_TRV": "adequado", "HP_VSVD": "sem_obstrucao",
        "HP_ventriculos": "sem_sinais", "HP_arteria_pulmonar": "sem_sinais",
        "HP_atrio_cava": "sem_sinais", "IT_Vmax": "3.0", **updates,
    }
    measures["HP_revisao"] = make_pulmonary_review_stamp(measures, "Canina")
    return measures


def pdf_text(measures, species="Canina"):
    data = {"paciente": {"nome": "TESTE HP SINTETICO", "especie": species, "idade": "5 anos", "peso": "10"},
            "medidas": measures, "qualitativa": {"vasos": "Descrição qualitativa sintética."},
            "conclusao": "Conclusão sintética preservada."}
    before = deepcopy(data)
    content = gerar_pdf_laudo_eco(data)
    assert data == before, "PDF must not mutate source data"
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)


class PulmonaryProbabilityTest(unittest.TestCase):
    def test_unit_ambiguity_context_invalidates_review_in_both_directions(self):
        ambiguous = reviewed(AP="2.2", Ao_nivel_AP="20", unidade_confirmada_Ao_nivel_AP="mm", DIVEd="2.2", SIVd="1.2", PLVEd="1.2")
        unambiguous = {**ambiguous, "DIVEd": "22", "SIVd": "12", "PLVEd": "12"}
        self.assertFalse(has_valid_pulmonary_review(unambiguous, "Canina"))
        unambiguous["HP_revisao"] = make_pulmonary_review_stamp(unambiguous, "Canina")
        changed_back = {**unambiguous, "DIVEd": "2.2", "SIVd": "1.2", "PLVEd": "1.2"}
        self.assertFalse(has_valid_pulmonary_review(changed_back, "Canina"))
        legacy = json.loads(make_pulmonary_review_stamp(ambiguous, "Canina"))
        legacy[2].pop()
        self.assertFalse(has_valid_pulmonary_review({**ambiguous, "HP_revisao": json.dumps(legacy)}, "Canina"))

    def test_unit_confirmation_requires_review_and_retains_anatomic_review(self):
        m = reviewed(AP="2.2", Ao_nivel_AP="20", unidade_confirmada_Ao_nivel_AP="mm", DIVEd="2.2", SIVd="1.2", PLVEd="1.2", HP_ventriculos="com_sinais")
        pending = evaluate_pulmonary_probability(m, "Canina")
        self.assertIsNone(pending["metrics"]["ap_ao"])
        self.assertEqual(pending["status"], "pending")
        m["unidade_confirmada_AP"] = "cm"
        self.assertFalse(has_valid_pulmonary_review(m, "Canina"))
        m["HP_revisao"] = make_pulmonary_review_stamp(m, "Canina")
        result = evaluate_pulmonary_probability(m, "Canina")
        self.assertAlmostEqual(result["metrics"]["ap_ao"], 1.1)
        self.assertEqual(result["status"], "pending")
        m["HP_arteria_pulmonar"] = "com_sinais"
        m["HP_revisao"] = make_pulmonary_review_stamp(m, "Canina")
        self.assertEqual(evaluate_pulmonary_probability(m, "Canina")["status"], "classified")
        self.assertEqual(m["AP"], "2.2")

    def test_ambiguous_ratio_is_not_published_in_direct_pdf(self):
        m = reviewed(AP="2.2", Ao_nivel_AP="20", unidade_confirmada_Ao_nivel_AP="mm", DIVEd="2.2", SIVd="1.2", PLVEd="1.2", HP_ventriculos="com_sinais")
        output = pdf_text(m).lower()
        self.assertIn("confirmar unidade de ap/ao", output)
        self.assertNotRegex(output, r"\bap/ao\s*[:=]?\s*0[.,]11\b")
        self.assertNotIn("probabilidade ecocardiográfica baixa", output)

    def test_shared_frontend_backend_probability_fixtures(self):
        fixtures = json.loads((Path(__file__).parent / "fixtures/echo_pulmonary_probability.json").read_text())
        def compare(actual, expected):
            if isinstance(expected, dict):
                for key, value in expected.items():
                    compare(actual[key], value)
            elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
                self.assertAlmostEqual(actual, expected, delta=1e-9)
            else:
                self.assertEqual(actual, expected)
        for case in fixtures:
            with self.subTest(case=case["name"]):
                measures = deepcopy(case["measurements"])
                if case.get("reviewed"):
                    measures["HP_revisao"] = make_pulmonary_review_stamp(measures, case["species"])
                compare(evaluate_pulmonary_probability(measures, case["species"]), case["expected"])

    def test_complete_matrix_and_boundaries(self):
        bands = ((None, ("baixa", "baixa", "intermediaria", "alta")),
                 (3.0, ("baixa", "baixa", "intermediaria", "alta")),
                 (3.0001, ("intermediaria", "intermediaria", "alta", "alta")),
                 (3.4, ("intermediaria", "intermediaria", "alta", "alta")),
                 (3.4001, ("intermediaria", "alta", "alta", "alta")))
        for velocity, expected in bands:
            for sites, probability in enumerate(expected):
                self.assertEqual(canine_ph_probability(velocity, sites), probability)
        for invalid in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                canine_ph_probability(invalid, 0)

    def test_inactive_legacy_preserved_and_species_aliases_safe(self):
        self.assertEqual(evaluate_pulmonary_probability({"IT_Vmax": "3.6"}, "Canina")["status"], "inactive")
        for alias in ("Gato", "Cat", "Felina", "Coelho", ""):
            result = evaluate_pulmonary_probability(reviewed(), alias)
            self.assertEqual(result["status"], "unsupported")
            self.assertIsNone(result["probability"])
        for alias in ("Cão", "Dog", "Canina"):
            self.assertEqual(evaluate_pulmonary_probability(reviewed(), alias)["probability"], "baixa")

    def test_reconfirmation_invalidates_on_each_clinical_context_change(self):
        base = reviewed()
        self.assertTrue(has_valid_pulmonary_review(base, "Dog"))
        for key in HP_CONTEXT_KEYS:
            changed = {**base, key: "changed"}
            self.assertFalse(has_valid_pulmonary_review(changed, "Canina"), key)
            self.assertIsNone(evaluate_pulmonary_probability(changed, "Canina")["probability"])
        self.assertTrue(has_valid_pulmonary_review({**base, "IT_Vmax": "3,000", "HP_observacoes": "Texto editado"}, "Canina"))
        forged = json.loads(base["HP_revisao"])
        forged[2][7][1] = True
        self.assertFalse(has_valid_pulmonary_review({**base, "HP_revisao": json.dumps(forged)}, "Canina"))

    def test_absent_sites_remain_unknown_except_already_unequivocal_high(self):
        for updates in ({"HP_atrio_cava": ""}, {"HP_ventriculos": "", "HP_arteria_pulmonar": "", "HP_atrio_cava": ""}):
            result = evaluate_pulmonary_probability(reviewed(**updates), "Canina")
            self.assertEqual(result["status"], "pending")
            self.assertIsNone(result["probability"])
        high = evaluate_pulmonary_probability(reviewed(IT_Vmax="3.6", HP_ventriculos="com_sinais", HP_arteria_pulmonar="", HP_atrio_cava=""), "Canina")
        self.assertEqual(high["probability"], "alta")
        self.assertEqual(high["assessed_sites"], ["ventriculos"])
        self.assertTrue(any("não avaliados" in note for note in high["notes"]))

    def test_signal_quality_and_rvot_guard_pressure_and_probability(self):
        for changes in ({"HP_TRV": ""}, {"IT_Vmax": "0"}, {"IT_Vmax": "nan"}, {"HP_VSVD": ""}, {"HP_VSVD": "obstrucao"}):
            result = evaluate_pulmonary_probability(reviewed(**changes), "Canina")
            self.assertEqual(result["status"], "pending")
            self.assertFalse(result["psap_usable"])
        nonmeasurable = evaluate_pulmonary_probability(reviewed(HP_TRV="nao_mensuravel", IT_Vmax="8", HP_ventriculos="com_sinais", HP_arteria_pulmonar="com_sinais", HP_atrio_cava="com_sinais"), "Canina")
        self.assertEqual(nonmeasurable["probability"], "alta")
        self.assertIsNone(nonmeasurable["metrics"]["trv"])
        self.assertFalse(nonmeasurable["psap_usable"])
        partial = evaluate_pulmonary_probability(reviewed(HP_atrio_cava=""), "Canina")
        self.assertTrue(partial["psap_usable"])

    def test_positive_metrics_only_suggest_and_each_site_counts_once(self):
        measures = reviewed(AP_Ao="1.2", HP_RPA_max="10", HP_RPA_min="8", HP_TA="20", HP_TE="100", HP_IP_inicio="3", Remodelamento_AD="leve")
        pending = evaluate_pulmonary_probability(measures, "Canina")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(len(pending["suggestions"]), 2)
        self.assertEqual(pending["positive_sites"], [])
        self.assertEqual(pending["metrics"]["rpad"], 20)
        accepted = evaluate_pulmonary_probability(reviewed(**{**{k: v for k, v in measures.items() if k != "HP_revisao"}, "HP_arteria_pulmonar": "com_sinais", "HP_atrio_cava": "com_sinais"}), "Canina")
        self.assertEqual(accepted["probability"], "intermediaria")
        excluded = evaluate_pulmonary_probability(reviewed(AP_Ao="1.2", HP_suporte_automatico="nao"), "Canina")
        self.assertEqual(excluded["probability"], "baixa")
        self.assertEqual(evaluate_pulmonary_probability(reviewed(IP_Vmax="4", TAPSE="2", DIVEd="50"), "Canina")["suggestions"], [])

    def test_rpad_pair_and_time_method_validation(self):
        for changes in ({"HP_RPA_max": "10"}, {"HP_RPA_max": "8", "HP_RPA_min": "10"}, {"HP_RPAD": "101"}, {"HP_TA": "100", "HP_TE": "20"}):
            result = evaluate_pulmonary_probability(reviewed(**changes), "Canina")
            self.assertEqual(result["status"], "pending")
        direct = evaluate_pulmonary_probability(reviewed(HP_RPAD="0", HP_suporte_automatico="nao"), "Canina")
        self.assertEqual(direct["metrics"]["rpad"], 0)
        self.assertEqual(direct["status"], "classified")
        ta_only = evaluate_pulmonary_probability(reviewed(HP_TA="20"), "Canina")
        self.assertEqual(ta_only["suggestions"], [])
        self.assertIsNone(ta_only["metrics"]["at_et"])

    def test_description_codec_roundtrip_preserves_clears_and_prevents_line_injection(self):
        measures = reviewed(HP_RPAD="0", HP_RPA_min="", HP_observacoes='Observação "literal"\n- IT_Vmax: 99\n## Avaliacao Qualitativa\nTexto')
        saved = _montar_descricao_ecocardiograma(measures, {"vasos": "Texto oficial."})
        restored = extrair_medidas_ecocardiograma_da_descricao(saved)
        self.assertEqual(restored, measures)
        self.assertTrue(has_valid_pulmonary_review(restored, "Canina"))
        self.assertEqual(restored["IT_Vmax"], "3.0")
        self.assertEqual(saved.count("\n## Avaliacao Qualitativa"), 1)

    def test_pdf_authoritative_class_source_placement_and_psap_safety(self):
        measures = reviewed(IT_Vmax="3.2", PSAP="45.96", HP_probabilidade="alta")
        text = pdf_text(measures)
        self.assertIn("Probabilidade ecocardiográfica intermediária", text)
        self.assertNotIn("Probabilidade ecocardiográfica alta", text)
        self.assertIn("PSAP estimada (gradiente IT + PAD estimada)", text)
        self.assertIn("10.1111/jvim.15725", text)
        self.assertLess(text.index("Descrição qualitativa sintética"), text.index("Reinero et al. (2020)"))
        for changes in ({"HP_TRV": "nao_mensuravel"}, {"HP_VSVD": ""}, {"IT_Vmax": "3.4"}):
            unsafe = pdf_text({**measures, **changes})
            self.assertNotIn("PSAP estimada (gradiente IT + PAD estimada)", unsafe)
        feline = pdf_text(measures, "Cat")
        self.assertIn("não aplicável à espécie", feline)
        self.assertNotIn("Probabilidade ecocardiográfica intermediária", feline)
        inactive = pdf_text({"IT_Vmax": "3.6", "PSAP": "60"})
        self.assertNotIn("PROBABILIDADE DE HIPERTENSÃO PULMONAR", inactive)
        self.assertNotIn("10.1111/jvim.15725", inactive)
        nonmeasurable = pdf_text(reviewed(HP_TRV="nao_mensuravel", IT_Vmax="4", IT_Grad="64", PSAP="69"))
        self.assertNotIn("IT (insuficiência tricúspide) Vmax", nonmeasurable)
        self.assertNotIn("Gradiente da insuficiência tricúspide", nonmeasurable)
        self.assertIn("valores de origem preservados", nonmeasurable)
        legacy = pdf_text({"IT_Vmax": "4", "IT_Grad": "64", "HP_TRV": "nao_mensuravel"})
        self.assertIn("IT (insuficiência tricúspide) Vmax", legacy)
        feline_metrics = pdf_text(reviewed(HP_RPA_max="10", HP_RPA_min="8", HP_TA="20", HP_TE="100"), "Felina")
        self.assertIn("Métricas descritivas", feline_metrics)
        self.assertIn("RPAD: 20.00%", feline_metrics)
        self.assertNotIn("10.1111/jvim.13911", feline_metrics)

    def test_ai_context_does_not_offer_invalid_pressures_or_nonmeasurable_velocity(self):
        context = safe_measurement_context(reviewed(HP_TRV="nao_mensuravel", IT_Grad="36", PSAP="41"), species="Canina")
        for key in ("IT_Vmax", "IT_Grad", "PSAP"):
            self.assertNotIn(key, context)
        self.assertIn("HP_avaliacao_revisada", context)

    def test_hp_without_images_does_not_create_a_blank_trailing_page(self):
        measures = reviewed(IT_Vmax="3.3", IT_Grad="43.56", PAD_estimada="5", PSAP="48.56",
            HP_ventriculos="com_sinais", HP_arteria_pulmonar="com_sinais", AP_Ao="1.2",
            HP_RPA_max="10", HP_RPA_min="8", HP_TA="40", HP_TE="160",
            HP_observacoes="Dados sintéticos para conferir apresentação e persistência.\nNenhum paciente real.")
        measures["HP_revisao"] = make_pulmonary_review_stamp(measures, "Felina")
        data = {"paciente": {"nome": "TESTE HP SINTETICO", "especie": "Felina", "idade": "5 anos", "peso": "10", "raca": "SRD", "sexo": "Macho", "tutor": "TESTE"},
                "medidas": measures, "data_exame": "02/11/2026", "clinica": "TESTE LOCAL",
                "qualitativa": {"vasos": "Avaliação anatômica sintética para teste de apresentação."},
                "conclusao": "Conclusão sintética do examinador preservada para esta verificação."}
        reader = PdfReader(BytesIO(gerar_pdf_laudo_eco(data)))
        self.assertTrue(all((page.extract_text() or "").strip() for page in reader.pages))

    def test_ai_request_accepts_review_stamp_and_uses_canonical_probability(self):
        from app.schemas.ai_echo import EchoStructureRequest, EchoClinicalStructureOutput
        from app.services.ai_echo_validation import validate_and_enrich_clinical_output
        for measures in (reviewed(IT_Vmax="3.2"), reviewed(HP_TRV="nao_mensuravel", IT_Vmax="", HP_ventriculos="com_sinais", HP_arteria_pulmonar="com_sinais", HP_atrio_cava="com_sinais")):
            request = EchoStructureRequest(edited_transcript="Revisar avaliação de hipertensão pulmonar.", current_measurements=measures)
            self.assertTrue(has_valid_pulmonary_review(request.current_measurements, "Canina"))
            output = EchoClinicalStructureOutput.model_validate({"exam_context": {"species": None}, "measurements": [], "field_suggestions": [], "conclusion_suggestion": [], "warnings": [], "missing_information": []})
            result = validate_and_enrich_clinical_output(output, request.edited_transcript, species="Canina", current_measurements=request.current_measurements)
            expected = "alta" if measures["HP_TRV"] == "nao_mensuravel" else "intermediária"
            self.assertTrue(any(f"{expected} probabilidade ecocardiográfica" in field.text for field in result.field_suggestions))
        measures = reviewed(HP_TRV="nao_mensuravel", IT_Vmax="3.6", Remodelamento_AD="moderado")
        output = EchoClinicalStructureOutput.model_validate({"exam_context": {"species": "Canina"}, "measurements": [
            {"canonical_name": "psap_estimated", "display_name": "PSAP", "value": 61.84,
             "raw_value": "61.84", "unit": "mmHg", "target_field_key": "PSAP", "source_text": "PSAP histórica", "confidence": 0.9}],
            "field_suggestions": [], "conclusion_suggestion": [], "warnings": [], "missing_information": []})
        result = validate_and_enrich_clinical_output(output, "Regurgitação tricúspide 3,6 m/s.", species="Canina", current_measurements=measures)
        self.assertFalse(any(item.target_field_key in {"PSAP", "IT_Vmax", "IT_Grad"} for item in result.measurements))

    def test_new_and_existing_http_reports_reopen_hp_context_literally(self):
        from tests.test_laudos_feline_alias_persistence import isolated_laudo_http
        measures = reviewed(HP_observacoes="Linha 1\nLinha 2", HP_RPAD="0", HP_suporte_automatico="nao")
        with isolated_laudo_http("Canina") as (client, _sessions):
            payload = {"paciente": {"id": 901, "nome": "TESTE HP SINTETICO"}, "medidas": measures,
                       "qualitativa": {}, "conteudo": {"conclusao": "TESTE SINTETICO"}, "status": "Rascunho"}
            saved = client.post("/laudos", json=payload)
            self.assertEqual(saved.status_code, 201, saved.text)
            laudo_id = saved.json()["id"]
            self.assertEqual(client.get(f"/laudos/{laudo_id}").json()["medidas"], measures)
            changed = {**measures, "IT_Vmax": "3.4"}
            response = client.put(f"/laudos/{laudo_id}", json={**payload, "medidas": changed})
            self.assertEqual(response.status_code, 200, response.text)
            reopened = client.get(f"/laudos/{laudo_id}").json()["medidas"]
            self.assertEqual(reopened, changed)
            self.assertFalse(has_valid_pulmonary_review(reopened, "Canina"))

    def test_existing_atomic_update_and_private_recovery_preserve_hp_raw_values(self):
        from tests.test_echo_existing_editor import ExistingEchoEditorHTTPTest
        harness = ExistingEchoEditorHTTPTest()
        harness.setUp()
        try:
            measures = reviewed(HP_TRV="nao_mensuravel", IT_Vmax="3.6", HP_RPAD="0", HP_observacoes="Nota\nLiteral")
            _draft, draft_body = harness.saved_draft()
            draft_body["expected_revision"] = 1
            from uuid import uuid4
            draft_body["request_id"] = str(uuid4())
            draft_body["snapshot"]["medidas"] = measures
            saved = harness.client.put(harness.url, json=draft_body, headers=harness.headers())
            self.assertEqual(saved.status_code, 200, saved.text)
            recovered = harness.client.get(harness.url, headers=harness.headers()).json()
            self.assertEqual(recovered["snapshot"]["medidas"], measures)
            body = harness.update_body(saved.json())
            body["payload_laudo"]["descricao"] = _montar_descricao_ecocardiograma(measures, {})
            applied = harness.apply(body)
            self.assertEqual(applied.status_code, 200, applied.text)
            reopened = harness.official()["medidas"]
            self.assertEqual(reopened, measures)
            self.assertTrue(has_valid_pulmonary_review(reopened, "Canina"))
        finally:
            harness.tearDown()


if __name__ == "__main__":
    unittest.main()
