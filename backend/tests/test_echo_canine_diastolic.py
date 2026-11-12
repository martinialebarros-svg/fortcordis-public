import json
import os
import re
import sys
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "echo-canine-diastolic-test-secret-1234567890")

from pypdf import PdfReader
from app.api.v1.endpoints.laudos import _montar_descricao_ecocardiograma
from app.schemas.ai_echo import EchoStructureRequest
from app.services.ai_echo_context import safe_measurement_context
from app.utils.ecocardiograma_medidas import extrair_medidas_ecocardiograma_da_descricao
from app.utils.echo_canine_diastolic import (
    CHOI_METHOD, PEREIRA_METHOD, PW_METHOD, WESS_LATERAL_METHOD,
    WESS_SEPTAL_METHOD, canine_diastolic_references,
)
from app.utils.echo_diastolic import diastolic_notes, diastolic_references
from app.utils.echo_feline_diastolic import feline_diastolic_references
from app.utils.echo_reference_methods import ECHO_REFERENCE_METHOD_VALUES
from app.utils.pdf_laudo import gerar_pdf_laudo_eco

PARITY = json.loads((Path(__file__).parent / "fixtures/echo_canine_diastolic_parity.json").read_text())
MEASUREMENTS = PARITY["measurements"]
PROTOCOL = {"Diastolica_metodo": PEREIRA_METHOD, "Diastolica_ondas": "separadas",
            "TDI_metodo": CHOI_METHOD, "TDI_ondas": "separadas"}
LEGACY_KEYS = {
    "Onda_E": "MV_E", "Onda_A": "MV_A", "E_A": "MV_E_A", "TD": "MV_DT",
    "TRIV": "IVRT", "E_TRIV": "MV_E_TRIV", "e_doppler": "TDI_e",
    "a_doppler": "TDI_a", "E_E_linha": "EEp",
}


def legacy_measurements(measurements):
    return {LEGACY_KEYS.get(key, key): value for key, value in measurements.items()}


def report(measurements, species="Canina", catalog=None):
    return {"paciente": {"nome": "TESTE TECNICO DIASTOLICA", "especie": species,
                         "data_exame": "2026-10-25", "idade": "4 anos"},
            "medidas": measurements, "referencia_eco": catalog,
            "conclusao": "TESTE SINTETICO. Sem finalidade clinica.",
            "qualitativa": {"funcao": "Texto sintetico preservado."}, "clinica": "Clinica teste"}


def pdf_text(payload):
    return re.sub(r"\s+", " ", "\n".join(page.extract_text() for page in PdfReader(BytesIO(gerar_pdf_laudo_eco(payload))).pages))


def contract(reference):
    published = reference["kind"] in {"descriptive", "reference_interval"}
    result = {"kind": reference["kind"], "statistic": reference["statistic"],
              "doi": reference["doi"] if published else "",
              "numeric_text": reference["text"].removeprefix("Média ± DP: ").removeprefix("IR95%: ") if published else ""}
    if reference["kind"] == "reference_interval":
        result.update(min=reference["min"], max=reference["max"])
    return result


class CanineDiastolicEvidenceTest(unittest.TestCase):
    def test_legacy_measurement_aliases_match_canonical_evidence_and_notes(self):
        canonical = {**MEASUREMENTS, **PROTOCOL}
        legacy = legacy_measurements(canonical)
        before = deepcopy(legacy)
        self.assertEqual(canine_diastolic_references(legacy, "Dog"),
                         canine_diastolic_references(canonical, "Dog"))
        self.assertEqual(diastolic_notes(legacy, "Dog"), diastolic_notes(canonical, "Dog"))
        self.assertEqual(legacy, before)

    def test_legacy_aliases_never_reconfirm_methods_or_independent_wave_groups(self):
        for override in (
            {"Diastolica_metodo": "outro", "TDI_metodo": "outro"},
            {"Diastolica_ondas": "nao_confirmadas"},
            {"TDI_ondas": "nao_confirmadas"},
            {"Diastolica_ondas": "fundidas"},
            {"TDI_ondas": "fundidas"},
            {"Diastolica_ondas": "fundidas", "TDI_ondas": "fundidas"},
        ):
            with self.subTest(override=override):
                canonical = {**MEASUREMENTS, **PROTOCOL, **override}
                legacy = legacy_measurements(canonical)
                before = deepcopy(legacy)
                self.assertEqual(canine_diastolic_references(legacy, "Canina"),
                                 canine_diastolic_references(canonical, "Canina"))
                self.assertEqual(diastolic_notes(legacy, "Canina"), diastolic_notes(canonical, "Canina"))
                self.assertEqual(legacy, before)

    def test_explicit_canonical_values_win_legacy_aliases_in_both_resolvers(self):
        for species, protocol in (
            ("Canina", PROTOCOL),
            ("Felina", {"Diastolica_metodo": "felino_adulto_nao_sedado_pw_apical_clique_aortico",
                        "Diastolica_ondas": "separadas", "TDI_metodo": "felino_pw_anel_lateral",
                        "TDI_ondas": "separadas"}),
        ):
            for canonical, alias in LEGACY_KEYS.items():
                for value in ("0.87", "0", 0, "", None):
                    for canonical_first in (True, False):
                        with self.subTest(species=species, key=canonical, value=value, canonical_first=canonical_first):
                            pairs = [(canonical, value), (alias, "0.61")]
                            measurements = {**dict(pairs if canonical_first else reversed(pairs)), **protocol}
                            before = deepcopy(measurements)
                            self.assertEqual(diastolic_references(measurements, species),
                                             diastolic_references({canonical: value, **protocol}, species))
                            self.assertEqual(measurements, before)

    def test_legacy_aliases_do_not_derive_missing_ratios_or_methods(self):
        measurements = {"MV_E": ".70", "MV_A": ".50", "IVRT": "70",
                        "TDI_e": ".09", "TDI_a": ".11"}
        for species in ("Canina", "Felina"):
            with self.subTest(species=species):
                references = diastolic_references(measurements, species)
                self.assertEqual(set(references), {"Onda_E", "Onda_A", "TRIV", "e_doppler", "a_doppler"})
                self.assertTrue(all(ref["kind"] == "unconfirmed" for ref in references.values()))
                self.assertNotIn("Diastolica_metodo", measurements)
                self.assertNotIn("TDI_metodo", measurements)

    def test_shared_ui_pdf_contract_has_only_one_published_individual_interval(self):
        for case in PARITY["cases"]:
            with self.subTest(case=case["id"]):
                measurements = {**MEASUREMENTS, **case["protocol"]}
                before = deepcopy(measurements)
                actual = canine_diastolic_references(measurements, case["species"])
                self.assertEqual({key: contract(ref) for key, ref in actual.items()},
                                 {key: PARITY["evidence"][evidence] for key, evidence in case["expected"].items()})
                for key, ref in actual.items():
                    if ref["kind"] == "reference_interval":
                        self.assertEqual(key, "Onda_E")
                        self.assertEqual((ref["min"], ref["max"]), (0.51, 1.10))
                    else:
                        self.assertNotIn("min", ref)
                        self.assertNotIn("max", ref)
                self.assertEqual(measurements, before)

    def test_species_dispatcher_preserves_feline_evidence_and_aliases(self):
        measurements = {**MEASUREMENTS, **PROTOCOL}
        for species in ("Canina", "Canino", "Cão", "Cachorro", "Dog", "Dogs"):
            self.assertEqual(diastolic_references(measurements, species), canine_diastolic_references(measurements, "Canina"))
        feline = {**MEASUREMENTS, "Diastolica_metodo": "felino_adulto_nao_sedado_pw_apical_fim_fluxo", "Diastolica_ondas": "separadas"}
        for species in ("Felina", "Gato", "Cat"):
            self.assertEqual(diastolic_references(feline, species), feline_diastolic_references(feline, species))
        self.assertEqual(diastolic_references(measurements, "Equina"), {})
        self.assertEqual(diastolic_notes(measurements, "Equina"), [])

    def test_cw_generic_equipment_feline_methods_and_unconfirmed_waves_never_unlock_pw_interval(self):
        for method in (None, "outro", "cw_apical", "modo_m", "felino_adulto_nao_sedado_pw_apical_fim_fluxo"):
            for waves in (None, "separadas"):
                with self.subTest(method=method, waves=waves):
                    ref = canine_diastolic_references({"Onda_E": ".70", "Diastolica_metodo": method, "Diastolica_ondas": waves}, "Canina")["Onda_E"]
                    self.assertEqual(ref["kind"], "unconfirmed")
                    self.assertNotIn("min", ref)
        self.assertEqual(canine_diastolic_references({"Onda_E": ".70", "Diastolica_metodo": PW_METHOD}, "Canina")["Onda_E"]["kind"], "unconfirmed")

    def test_pw_confirmation_names_the_primary_technique_population_and_observed_hr_domain(self):
        ref = canine_diastolic_references({"Onda_E": ".70", "Diastolica_metodo": PW_METHOD, "Diastolica_ondas": "separadas"}, "Canina")["Onda_E"]
        for context in ("120", "19 raças", "pulsado", "pontas mitrais", "55-171", "não sedados", "cardioativa"):
            self.assertIn(context, ref["note"])
        self.assertNotIn("0,57", ref["text"])

    def test_tdi_never_interchanges_site_or_adds_wess_ratios(self):
        for method, expected in ((WESS_SEPTAL_METHOD, "0,0741"), (WESS_LATERAL_METHOD, "0,1041")):
            refs = canine_diastolic_references({**MEASUREMENTS, **PROTOCOL, "TDI_metodo": method}, "Canina")
            self.assertIn(expected, refs["e_doppler"]["text"])
            self.assertIn("5 mm", refs["e_doppler"]["note"])
            for key in ("doppler_tecidual_relacao", "E_E_linha"):
                self.assertEqual(refs[key]["kind"], "unconfirmed")
        refs = canine_diastolic_references({**MEASUREMENTS, **PROTOCOL, "Diastolica_metodo": "outro"}, "Canina")
        self.assertEqual(refs["e_doppler"]["kind"], "descriptive")
        self.assertEqual(refs["E_E_linha"]["kind"], "unconfirmed")

    def test_invalid_numeric_values_do_not_acquire_evidence(self):
        for value in (True, False, "nan", "inf", "-1", "0", "", None):
            self.assertEqual(canine_diastolic_references({"Onda_E": value, **PROTOCOL}, "Canina"), {})

    def test_confirmed_canine_fusion_excludes_invalid_peaks_from_ai_without_losing_independent_inputs(self):
        measurements = {**MEASUREMENTS, **PROTOCOL, "Diastolica_ondas": "fundidas"}
        before = deepcopy(measurements)
        safe = safe_measurement_context(measurements, species="Dog")
        for key in ("Onda_E", "Onda_A", "E_A", "TD", "E_E_linha", "E_TRIV"):
            self.assertNotIn(key, safe)
        for key in ("TRIV", "e_doppler", "a_doppler", "doppler_tecidual_relacao"):
            self.assertIn(key, safe)
        self.assertEqual(measurements, before)

    def test_all_new_method_enums_survive_serialization_and_request_validation(self):
        for field, methods in (("Diastolica_metodo", (PW_METHOD, PEREIRA_METHOD)),
                               ("TDI_metodo", (CHOI_METHOD, WESS_SEPTAL_METHOD, WESS_LATERAL_METHOD))):
            for method in methods:
                with self.subTest(method=method):
                    self.assertIn(method, ECHO_REFERENCE_METHOD_VALUES[field])
                    measurements = {**MEASUREMENTS, **PROTOCOL, field: method}
                    description = _montar_descricao_ecocardiograma(measurements, {})
                    self.assertEqual(extrair_medidas_ecocardiograma_da_descricao(description)[field], method)
                    request = EchoStructureRequest.model_validate({"edited_transcript": "Exame sintetico.", "current_measurements": measurements})
                    self.assertEqual(request.current_measurements[field], method)

    def test_retracted_wave_review_roundtrips_distinctly_from_absent_legacy_metadata(self):
        for field in ("Diastolica_ondas", "TDI_ondas"):
            with self.subTest(field=field):
                measurements = {**MEASUREMENTS, **PROTOCOL, field: "nao_confirmadas"}
                before = deepcopy(measurements)
                saved = _montar_descricao_ecocardiograma(measurements, {})
                restored = extrair_medidas_ecocardiograma_da_descricao(saved)
                self.assertEqual(restored, measurements)
                self.assertEqual(restored[field], "nao_confirmadas")
                request = EchoStructureRequest.model_validate({"edited_transcript": "Exame sintetico.", "current_measurements": restored})
                self.assertEqual(request.current_measurements[field], "nao_confirmadas")
                without_review = {key: value for key, value in measurements.items() if key != field}
                legacy_restored = extrair_medidas_ecocardiograma_da_descricao(_montar_descricao_ecocardiograma(without_review, {}))
                self.assertNotIn(field, legacy_restored)
                self.assertEqual(measurements, before)

    def test_retracted_wave_review_never_unlocks_intervals_or_descriptive_wave_comparisons(self):
        for species, methods in (
            ("Canina", {"Diastolica_metodo": PEREIRA_METHOD, "TDI_metodo": CHOI_METHOD}),
            ("Felina", {"Diastolica_metodo": "felino_adulto_nao_sedado_pw_apical_fim_fluxo", "TDI_metodo": "felino_pw_anel_lateral"}),
        ):
            for field, dependent in (
                ("Diastolica_ondas", ("Onda_E", "Onda_A", "E_A", "TD", "E_E_linha")),
                ("TDI_ondas", ("e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha")),
            ):
                with self.subTest(species=species, field=field):
                    measurements = {**MEASUREMENTS, **PROTOCOL, **methods, field: "nao_confirmadas"}
                    before = deepcopy(measurements)
                    refs = diastolic_references(measurements, species)
                    for key in dependent:
                        self.assertEqual(refs[key]["kind"], "unconfirmed")
                        self.assertNotIn("min", refs[key])
                        self.assertNotIn("max", refs[key])
                    self.assertEqual(refs["TRIV"]["kind"], "descriptive")
                    self.assertEqual(measurements, before)

    def test_fusion_keeps_independent_triv_and_tdi_and_retains_originals(self):
        measurements = {**MEASUREMENTS, **PROTOCOL, "Diastolica_ondas": "fundidas"}
        before = deepcopy(measurements)
        refs = canine_diastolic_references(measurements, "Canina")
        for key in ("Onda_E", "Onda_A", "E_A", "TD", "E_E_linha", "E_TRIV"):
            self.assertEqual(refs[key]["kind"], "uninterpretable")
        for key in ("TRIV", "e_doppler", "a_doppler", "doppler_tecidual_relacao"):
            self.assertEqual(refs[key]["kind"], "descriptive")
        self.assertEqual(measurements, before)
        cleared = canine_diastolic_references({"Diastolica_ondas": "fundidas", "TDI_ondas": "fundidas"}, "Canina")
        self.assertEqual(len(cleared), 9)
        self.assertTrue(all(ref["kind"] == "uninterpretable" for ref in cleared.values()))


class CanineDiastolicPdfTest(unittest.TestCase):
    def test_legacy_alias_pdf_matches_canonical_values_notes_and_bibliography(self):
        canonical = {**MEASUREMENTS, **PROTOCOL}
        payload = report(legacy_measurements(canonical))
        before = deepcopy(payload)
        text = pdf_text(payload)
        self.assertEqual(text, pdf_text(report(canonical)))
        for expected in ("0.47 m/s", "0.67 m/s", "108.00 ms", "85.00 ms",
                         "0.07 m/s", "0.12 m/s", "6.71", "0.55",
                         "10.1111/jsap.13472", "10.1590/S0100-736X2009000400003",
                         "10.4142/jvs.2013.14.1.85"):
            self.assertIn(expected, text)
        self.assertEqual(payload, before)

    def test_legacy_alias_pdf_preserves_fusion_and_reconfirmation_guards(self):
        for override in ({"Diastolica_ondas": "fundidas"}, {"TDI_ondas": "fundidas"},
                         {"Diastolica_ondas": "nao_confirmadas", "TDI_ondas": "nao_confirmadas"}):
            with self.subTest(override=override):
                canonical = {**MEASUREMENTS, **PROTOCOL, **override}
                payload = report(legacy_measurements(canonical))
                before = deepcopy(payload)
                self.assertEqual(pdf_text(payload), pdf_text(report(canonical)))
                self.assertEqual(payload, before)

    def test_confirmed_evidence_prints_without_catalog_weight_and_after_qualitative(self):
        payload = report({**MEASUREMENTS, **PROTOCOL})
        before = deepcopy(payload)
        text = pdf_text(payload)
        for value in ("IR95%: 0,51-1,10", "0,487 ± 0,062", "1,533 ± 0,198", "88,7 ± 9,2", "80 ± 9", "0,0658 ± 0,0181", "10,94 ± 3,27"):
            self.assertIn(value, text)
        self.assertLess(text.index("ANÁLISE QUALITATIVA"), text.index("REFERÊNCIAS BIBLIOGRÁFICAS"))
        for doi in ("10.1111/jsap.13472", "10.1590/S0100-736X2009000400003", "10.4142/jvs.2013.14.1.85"):
            self.assertIn(doi, text)
        self.assertNotIn("≤12", text)
        self.assertNotIn("≤2,5", text)
        self.assertNotIn("0.50 - 1.09", text)
        self.assertNotIn("Faixas de referência indisponíveis para este paciente", text)
        self.assertEqual(payload, before)

    def test_unknown_method_does_not_reinstate_legacy_catalog_or_feline_sources(self):
        catalog = {"especie": "Canina", "peso_kg": 5, "mv_e_min": .50, "mv_e_max": 1.09,
                   "mv_ea_min": 1, "mv_ea_max": 2, "tdi_e_min": 5, "tdi_e_max": 15}
        text = pdf_text(report({**MEASUREMENTS, "Diastolica_metodo": "outro", "TDI_metodo": "outro"}, catalog=catalog))
        for unsupported in ("0.50 - 1.09", "1.00 - 2.00", "0.05 - 0.15", "IR95%", "Média ± DP", "10.1111/jsap.13472", "10.1186/s12917"):
            self.assertNotIn(unsupported, text)
        self.assertIn("0.47 m/s", text)
        self.assertIn("6.71", text)

    def test_all_four_fusion_states_mask_only_dependent_values_and_never_mutate_history(self):
        transmitral = {"Onda_E", "Onda_A", "E_A", "TD", "E_TRIV", "E_E_linha"}
        tissue = {"e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"}
        formatted = {"Onda_E": "0.47 m/s", "Onda_A": "0.67 m/s", "E_A": "0.70", "TD": "108.00 ms", "TRIV": "85.00 ms", "E_TRIV": "0.55", "e_doppler": "0.07 m/s", "a_doppler": "0.12 m/s", "doppler_tecidual_relacao": "0.58", "E_E_linha": "6.71"}
        for waves in ("separadas", "fundidas"):
            for tdi_waves in ("separadas", "fundidas"):
                with self.subTest(waves=waves, tdi=tdi_waves):
                    payload = report({**MEASUREMENTS, **PROTOCOL, "Diastolica_ondas": waves, "TDI_ondas": tdi_waves})
                    before = deepcopy(payload)
                    text = pdf_text(payload).split("ANÁLISE QUANTITATIVA", 1)[1].split("ANÁLISE QUALITATIVA", 1)[0]
                    masked = (transmitral if waves == "fundidas" else set()) | (tissue if tdi_waves == "fundidas" else set())
                    self.assertEqual(text.count("Não mensurável"), len(masked))
                    for key, value in formatted.items():
                        if key in masked:
                            self.assertNotIn(value, text)
                        else:
                            self.assertIn(value, text)
                    self.assertEqual(payload, before)

    def test_retracted_review_pdf_preserves_numbers_without_assuming_separated_or_fused_waves(self):
        measurements = {**MEASUREMENTS, **PROTOCOL,
                        "Diastolica_ondas": "nao_confirmadas", "TDI_ondas": "nao_confirmadas"}
        payload = report(measurements)
        before = deepcopy(payload)
        text = pdf_text(payload)
        for numeric in ("0.47 m/s", "0.67 m/s", "0.70", "108.00 ms", "85.00 ms", "0.07 m/s", "0.12 m/s", "0.58", "6.71"):
            self.assertIn(numeric, text)
        for invalid_evidence in ("IR95%", "0,487 ± 0,062", "0,0658 ± 0,0181", "10,94 ± 3,27", "Não mensurável", "Ondas E/A transmitrais fundidas"):
            self.assertNotIn(invalid_evidence, text)
        self.assertIn("80 ± 9", text)  # TRIV remains independent of peak separation.
        self.assertEqual(payload, before)

    def test_pending_reconfirmation_marks_only_dependent_pdf_indices_in_both_species(self):
        for species in ("Canina", "Cão", "Dog", "Felina", "Gato", "Cat"):
            for flow, tissue, marked, fused in (
                ("nao_confirmadas", "separadas", {"E_A", "E_TRIV", "E_E_linha"}, 0),
                ("separadas", "nao_confirmadas", {"doppler_tecidual_relacao", "E_E_linha"}, 0),
                ("nao_confirmadas", "nao_confirmadas", {"E_A", "E_TRIV", "E_E_linha", "doppler_tecidual_relacao"}, 0),
                ("nao_confirmadas", "fundidas", {"E_A", "E_TRIV"}, 4),
                ("fundidas", "nao_confirmadas", {"doppler_tecidual_relacao"}, 6),
            ):
                with self.subTest(species=species, flow=flow, tissue=tissue):
                    measurements = {**MEASUREMENTS, "Diastolica_ondas": flow, "TDI_ondas": tissue}
                    payload = report(measurements, species=species)
                    before = deepcopy(payload)
                    text = pdf_text(payload)
                    quantitative = text.split("ANÁLISE QUANTITATIVA", 1)[1].split("ANÁLISE QUALITATIVA", 1)[0]
                    self.assertEqual(quantitative.count("(valor a confirmar)"), len(marked))
                    self.assertEqual(quantitative.count("Não mensurável"), fused)
                    for key in marked:
                        self.assertIn(f"{MEASUREMENTS[key]} (valor a confirmar)", quantitative)
                    self.assertIn("85.00 ms", quantitative)  # TRIV is independent.
                    if flow != "fundidas":
                        self.assertIn("0.47 m/s", quantitative)
                        self.assertIn("0.67 m/s", quantitative)
                        self.assertIn("108.00 ms", quantitative)
                    if tissue != "fundidas":
                        self.assertIn("0.07 m/s", quantitative)
                        self.assertIn("0.12 m/s", quantitative)
                    notes = diastolic_notes(measurements, species)
                    self.assertEqual(sum(note.startswith("Ondas E/A: separação pendente") for note in notes), flow == "nao_confirmadas")
                    self.assertEqual(sum(note.startswith("Ondas e'/a': separação pendente") for note in notes), tissue == "nao_confirmadas")
                    self.assertIn("não interpretar esses índices até reconfirmar as ondas", quantitative)
                    self.assertEqual(payload, before)

    def test_explicit_reconfirmation_and_never_reviewed_history_have_no_pending_marker(self):
        for species in ("Canina", "Felina"):
            for review in ({}, {"Diastolica_ondas": "separadas", "TDI_ondas": "separadas"}):
                with self.subTest(species=species, review=review):
                    payload = report({**MEASUREMENTS, **review}, species=species)
                    before = deepcopy(payload)
                    text = pdf_text(payload)
                    self.assertNotIn("(valor a confirmar)", text)
                    self.assertNotIn("separação pendente de reconfirmação", text)
                    for numeric in ("0.70", "0.55", "6.71", "0.58"):
                        self.assertIn(numeric, text)
                    self.assertEqual(payload, before)

    def test_feline_septal_ratio_is_withheld_with_factual_pdf_source_note_and_other_data_preserved(self):
        measurements = {**MEASUREMENTS, "Diastolica_metodo": "felino_adulto_nao_sedado_pw_apical_fim_fluxo", "Diastolica_ondas": "separadas", "TDI_metodo": "felino_pw_anel_septal", "TDI_ondas": "separadas"}
        text = pdf_text(report(measurements, species="Felina"))
        self.assertNotIn("0,93 ± 0,20", text)
        self.assertIn("0,075 ± 0,026", text)
        self.assertIn("8,7 ± 1,7", text)
        self.assertNotIn("inconsistência aparente", text)
        self.assertNotIn("não foi adotada", text)
        self.assertIn("7 gatos jovens (1-3 anos); média ± DP por sítio", text)
        self.assertIn("0.58", text)
