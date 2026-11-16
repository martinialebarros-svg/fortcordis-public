import io
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from reportlab.pdfgen import canvas

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "eco-study-extraction-test-secret-key-1234567890")

from app.services.eco_study_extraction_service import (  # noqa: E402
    ECO_STUDY_EXTRACTOR_VERSION,
    GE_VIVID_IQ_PROFILE,
    MAX_ECO_STUDY_IMPORT_SIZE,
    _keep_most_reliable_candidates,
    _looks_like_ge_vivid_iq_screen_text,
    consolidate_measurement_candidates,
    extract_measurements_from_text,
    parse_ge_logiq_e_header_text,
    parse_patient_age_weight,
    parse_ge_vivid_iq_report_text,
    parse_eco_study_import_content,
    validate_eco_study_filename,
    validate_eco_study_size,
)


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 80), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf_bytes(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer)
    y = 800
    for line in lines:
        document.drawString(60, y, line)
        y -= 22
    document.save()
    return buffer.getvalue()


class EcoStudyExtractionServiceTest(unittest.TestCase):
    def test_pulmonary_support_import_requires_explicit_label_and_units(self) -> None:
        candidates = extract_measurements_from_text(
            "RPAD 25 %\nPV AT 0.04 s\nTempo de ejeção pulmonar 160 ms",
            source="pdf:text",
        )
        measures, _, conflicts = consolidate_measurement_candidates(candidates)
        self.assertEqual(measures, {"HP_RPAD": 25, "HP_TA": 40, "HP_TE": 160})
        self.assertEqual(conflicts, 0)
        self.assertTrue(all(item["texto_origem"] and item["rotulo_origem"] for item in candidates))
        self.assertFalse(any(key in measures for key in ("HP_ativa", "HP_TRV", "HP_revisao", "HP_arteria_pulmonar")))

    def test_generic_times_or_unqualified_rpad_do_not_acquire_pulmonary_context(self) -> None:
        candidates = extract_measurements_from_text(
            "TA 45 ms\nET 150 ms\nAorta AT 40 ms\nRPAD 25\nPV AT 40\nPV ET 160 mm",
            source="pdf:text",
        )
        self.assertFalse(any(item["campo"].startswith("HP_") for item in candidates))

    def test_support_import_zero_and_conflict_are_not_silently_discarded_or_averaged(self) -> None:
        measures, candidates, conflicts = consolidate_measurement_candidates(
            extract_measurements_from_text("RPAD 0 %\nPV AT 40 ms\nPV AT 60 ms", source="pdf:text")
        )
        self.assertEqual(measures, {"HP_RPAD": 0})
        self.assertEqual(conflicts, 1)
        self.assertEqual(sum(item["status"] == "conflito" for item in candidates), 2)

    def test_four_outflow_sites_keep_values_labels_and_imported_precision(self) -> None:
        expected = {
            "Vmax_VSVE": ("Vmáx VSVE", 1.010123),
            "Grad_VSVE": ("maxPG VSVE", 4.110123),
            "Vmax_aorta": ("Aorta Vmax", 1.123456),
            "Grad_aorta": ("Aorta maxPG", 5.123456),
            "Vmax_VSVD": ("RVOT Vmax P", 0.801234),
            "Grad_VSVD": ("RVOT maxPG", 2.571234),
            "Vmax_pulmonar": ("Pulmonic Vmax", 0.923456),
            "Grad_pulmonar": ("Pulmonic maxPG", 3.412345),
        }
        text = "\n".join(
            f"{label} {value} {'m/s' if field.startswith('Vmax') else 'mmHg'}"
            for field, (label, value) in expected.items()
        )

        candidates = extract_measurements_from_text(text, source="pdf:text")
        measurements, consolidated, conflicts = consolidate_measurement_candidates(candidates)

        self.assertEqual(measurements, {field: value for field, (_, value) in expected.items()})
        self.assertEqual(conflicts, 0)
        self.assertEqual(len(consolidated), 8)
        for candidate in consolidated:
            label, value = expected[candidate["campo"]]
            self.assertEqual(candidate["rotulo_origem"], label)
            self.assertEqual(candidate["valor_original"], value)

    def test_only_rvot_evidence_does_not_create_pulmonary_or_left_outflow_measurements(self) -> None:
        for label in ("RVOT", "VSVD", "via de saída do ventrículo direito"):
            with self.subTest(label=label):
                candidates = extract_measurements_from_text(
                    f"Vmax {label} 0,80 m/s\nGrad. max {label} 2,57 mmHg",
                    source="ocr:test",
                )
                measurements, _, conflicts = consolidate_measurement_candidates(candidates)
                self.assertEqual(measurements, {"Vmax_VSVD": 0.8, "Grad_VSVD": 2.57})
                self.assertEqual(conflicts, 0)

    def test_ambiguous_combined_outflow_label_does_not_select_one_site(self) -> None:
        for label in (
            "RVOT/Pulmonic Vmax", "VSVD/Pulmonar Vmax", "LVOT/Aorta Vmax",
            "VSVD (Pulmonar) Vmax", "RVOT ou Pulmonic Vmax",
        ):
            with self.subTest(label=label):
                candidates = extract_measurements_from_text(
                    f"{label} 0.80 m/s\nLVIDd 30 mm", source="pdf:text",
                )
                measurements, _, conflicts = consolidate_measurement_candidates(candidates)
                self.assertEqual(measurements, {"DIVEd": 30})
                self.assertEqual(conflicts, 0)

    def test_synonymous_outflow_labels_are_not_treated_as_different_sites(self) -> None:
        candidates = extract_measurements_from_text(
            "VSVD/RVOT Vmax 0.80 m/s\nVSVE/LVOT maxPG 4.11 mmHg",
            source="pdf:text",
        )
        measurements, consolidated, conflicts = consolidate_measurement_candidates(candidates)
        self.assertEqual(measurements, {"Vmax_VSVD": 0.8, "Grad_VSVE": 4.11})
        self.assertEqual(conflicts, 0)
        self.assertEqual(
            {item["rotulo_origem"] for item in consolidated},
            {"VSVD/RVOT Vmax", "VSVE/LVOT maxPG"},
        )

    def test_pdf_outflow_import_preserves_gradients_and_persists_provenance(self) -> None:
        content = _pdf_bytes([
            "Peso: 7 kg", "Idade: 3 anos",
            "Vmax VSVE 1.01 m/s", "maxPG VSVE 4.11 mmHg",
            "Vmax Aorta 1.123456 m/s", "Aorta PG 5.123456 mmHg",
            "Vmax VSVD 0.80 m/s", "maxPG VSVD 2.57 mmHg",
            "Vmax pulmonar 0.90 m/s", "Gradiente pulmonar 3.26 mmHg",
        ])

        payload = parse_eco_study_import_content("vias-saida.pdf", content)
        measurements = payload["medidas"]

        self.assertEqual(measurements["Grad_VSVE"], 4.11)
        self.assertEqual(measurements["Grad_VSVD"], 2.57)
        self.assertEqual(measurements["Vmax_aorta"], 1.123456)
        self.assertEqual(measurements["Grad_aorta"], 5.123456)
        self.assertEqual(payload["meta_importacao_estudo"]["medidas_sugeridas"], 8)
        for field in (
            "Vmax_VSVE", "Grad_VSVE", "Vmax_aorta", "Grad_aorta",
            "Vmax_VSVD", "Grad_VSVD", "Vmax_pulmonar", "Grad_pulmonar",
        ):
            self.assertEqual(measurements[f"{field}_origem"], "importado")
            self.assertTrue(measurements[f"{field}_rotulo_origem"])

    def test_pdf_velocity_without_gradient_leaves_gradient_absent(self) -> None:
        content = _pdf_bytes([
            "Peso: 7 kg", "Idade: 3 anos", "LVOT Vmax 1.01 m/s",
        ])

        measurements = parse_eco_study_import_content("somente-vsve.pdf", content)["medidas"]

        self.assertEqual(measurements["Vmax_VSVE"], 1.01)
        self.assertEqual(measurements["Vmax_VSVE_rotulo_origem"], "LVOT Vmax")
        self.assertEqual(set(measurements), {
            "Vmax_VSVE", "Vmax_VSVE_origem", "Vmax_VSVE_rotulo_origem",
        })

    def test_conflicting_imported_gradient_is_unresolved_instead_of_absent(self) -> None:
        content = _pdf_bytes([
            "Peso: 7 kg", "Idade: 3 anos", "Vmax VSVE 1.01 m/s",
            "maxPG VSVE 4.11 mmHg", "LVOT maxPG 9.25 mmHg",
        ])

        payload = parse_eco_study_import_content("conflito-gradiente.pdf", content)
        measurements = payload["medidas"]

        self.assertEqual(measurements["Vmax_VSVE"], 1.01)
        self.assertEqual(measurements["Grad_VSVE"], "Conflito de medidas no exame de origem")
        self.assertEqual(measurements["Grad_VSVE_origem"], "importado")
        self.assertEqual(measurements["Grad_VSVE_rotulo_origem"], "maxPG VSVE | LVOT maxPG")
        self.assertEqual(payload["meta_importacao_estudo"]["conflitos"], 1)
        self.assertEqual(payload["meta_importacao_estudo"]["medidas_sugeridas"], 1)
        conflicting = [item for item in payload["medidas_extraidas"] if item["campo"] == "Grad_VSVE"]
        self.assertEqual({item["status"] for item in conflicting}, {"conflito"})
        self.assertEqual({item["valor"] for item in conflicting}, {4.11, 9.25})

    def test_aortic_doppler_label_does_not_create_an_anatomical_measurement(self) -> None:
        candidates = extract_measurements_from_text(
            "Vmax Aorta 1.01 m/s\nGradiente Aorta 4.11 mmHg\nAorta 20 mm",
            source="pdf:text",
        )
        measurements, consolidated, conflicts = consolidate_measurement_candidates(candidates)
        self.assertEqual(measurements, {"Vmax_aorta": 1.01, "Grad_aorta": 4.11, "Aorta": 20})
        self.assertEqual(len(consolidated), 3)
        self.assertEqual(conflicts, 0)

    def test_rendered_outflow_labels_can_be_imported_without_changing_site(self) -> None:
        candidates = extract_measurements_from_text(
            "Vmax via de saída do VE 1.01 m/s\n"
            "Gradiente via de saída do VE 4.11 mmHg\n"
            "Vmax via de saída do VD 0.80 m/s\n"
            "Gradiente via de saída do VD 2.57 mmHg\n"
            "Fluxo aórtico Vmax 1.1 m/s\n"
            "Fluxo pulmonar PG 3.26 mmHg",
            source="pdf:text",
        )

        measurements, _, conflicts = consolidate_measurement_candidates(candidates)

        self.assertEqual(measurements, {
            "Vmax_VSVE": 1.01, "Grad_VSVE": 4.11,
            "Vmax_VSVD": 0.8, "Grad_VSVD": 2.57,
            "Vmax_aorta": 1.1, "Grad_pulmonar": 3.26,
        })
        self.assertEqual(conflicts, 0)

    def test_feline_atrial_and_lvot_labels_keep_distinct_sources(self) -> None:
        candidates = extract_measurements_from_text(
            "LADmax 18 mm\nLADmin 13.5 mm\nLA FS 25 %\n"
            "LAA Vmax 0.18 m/s\nLVOT Vmax 2.5 m/s\n"
            "Aorta Vmax 0.69 m/s\nmaxPG VSVE 25 mmHg",
            source="pdf:text", confidence=0.99,
        )
        measurements, _, conflicts = consolidate_measurement_candidates(candidates)
        self.assertEqual(measurements["AE_diametro_max"], 18)
        self.assertEqual(measurements["AE_diametro_min"], 13.5)
        self.assertEqual(measurements["Fracao_encurtamento_AE"], 25)
        self.assertEqual(measurements["Fluxo_auricular"], 0.18)
        self.assertEqual(measurements["Vmax_VSVE"], 2.5)
        self.assertEqual(measurements["Vmax_aorta"], 0.69)
        self.assertEqual(measurements["Grad_VSVE"], 25)
        self.assertNotIn("Grad_aorta", measurements)
        self.assertEqual(conflicts, 0)

    def test_extracts_and_normalizes_common_measurements(self) -> None:
        candidates = extract_measurements_from_text(
            """
            LVIDd 3.24 cm
            LVIDs: 2.10 cm
            IVSd 0.71 cm
            LVPWd 0.69 cm
            EF Teich 62 %
            FS 35 %
            LA/Ao 1.62
            MV E Vel 0.85 m/s
            MV A Vel 0.61 m/s
            IVRT 72 ms
            TR Vmax 3.25 m/s
            """,
            source="test",
            confidence=0.99,
        )
        measurements, consolidated, conflicts = consolidate_measurement_candidates(candidates)

        self.assertEqual(measurements["DIVEd"], 32.4)
        self.assertEqual(measurements["DIVES"], 21)
        self.assertEqual(measurements["SIVd"], 7.1)
        self.assertEqual(measurements["PLVEd"], 6.9)
        self.assertEqual(measurements["FE_Teicholz"], 62)
        self.assertEqual(measurements["DeltaD_FS"], 35)
        self.assertEqual(measurements["AE_Ao"], 1.62)
        self.assertEqual(measurements["Onda_E"], 0.85)
        self.assertEqual(measurements["Onda_A"], 0.61)
        self.assertEqual(measurements["TRIV"], 72)
        self.assertEqual(measurements["IT_Vmax"], 3.25)
        self.assertNotIn("e_doppler", measurements)
        self.assertNotIn("a_doppler", measurements)
        self.assertEqual(conflicts, 0)
        self.assertTrue(all(item["texto_origem"] for item in consolidated))

    def test_conflicting_values_are_not_suggested(self) -> None:
        candidates = extract_measurements_from_text("LVIDd 30 mm\nLVIDd 36 mm")
        measurements, consolidated, conflicts = consolidate_measurement_candidates(candidates)

        self.assertNotIn("DIVEd", measurements)
        self.assertEqual(conflicts, 1)
        self.assertEqual({item["status"] for item in consolidated}, {"conflito"})

    def test_keeps_m_mode_and_2d_lv_measurements_as_distinct_series(self) -> None:
        candidates = extract_measurements_from_text(
            """
            2D
            SIVd 12.59 mm
            DIVEd 45.82 mm
            PPVEd 11.04 mm
            SIVs 13.67 mm
            DIVEs 32.10 mm
            PPVEs 10.82 mm
            VDF(Teich) 96 ml
            VSF(Teich) 41 ml
            FE(Teich) 57 %
            Delta D 30 %
            M-Mode
            SIVd 10.56 mm
            DIVEd 46.39 mm
            PPVEd 9.44 mm
            SIVs 12.22 mm
            DIVEs 29.72 mm
            PPVEs 14.44 mm
            VDF(Teich) 99 ml
            VSF(Teich) 34 ml
            FE(Teich) 66 %
            Delta D 36 %
            Doppler
            e' 8 cm/s
            """,
            source="pdf:text",
            confidence=0.99,
        )
        measurements, consolidated, conflicts = consolidate_measurement_candidates(candidates)

        self.assertEqual(measurements["DIVEd"], 46.39)
        self.assertEqual(measurements["DIVEd_2D"], 45.82)
        self.assertEqual(measurements["VDF"], 99)
        self.assertEqual(measurements["VDF_2D"], 96)
        self.assertEqual(measurements["VSF"], 34)
        self.assertEqual(measurements["VSF_2D"], 41)
        self.assertEqual(measurements["FE_Teicholz"], 66)
        self.assertEqual(measurements["FE_Teicholz_2D"], 57)
        self.assertEqual(measurements["DeltaD_FS"], 36)
        self.assertEqual(measurements["DeltaD_FS_2D"], 30)
        self.assertEqual(measurements["e_doppler"], 0.08)
        self.assertEqual(conflicts, 0)
        techniques = {
            item.get("tecnica")
            for item in consolidated
            if item["campo"] in {"DIVEd", "DIVEd_2D", "VDF", "VDF_2D"}
        }
        self.assertEqual(techniques, {"modo_m", "2d"})

    def test_extracts_e_over_triv_without_reading_it_as_second_triv_measurement(self) -> None:
        candidates = extract_measurements_from_text(
            "TRIV 40.00 ms\nE/triv 14.92",
            source="ocr:test",
        )

        measurements, consolidated, conflicts = consolidate_measurement_candidates(candidates)

        self.assertEqual(measurements["TRIV"], 40)
        self.assertEqual(measurements["E_TRIV"], 14.92)
        self.assertEqual(conflicts, 0)
        self.assertEqual(len([item for item in consolidated if item["campo"] == "TRIV"]), 1)

    def test_accepts_curly_apostrophe_in_tissue_doppler_ratio(self) -> None:
        candidates = extract_measurements_from_text("E/E’ 8.47", source="ocr:test")

        measurements, _, conflicts = consolidate_measurement_candidates(candidates)

        self.assertEqual(measurements["E_E_linha"], 8.47)
        self.assertEqual(conflicts, 0)

    def test_prefers_complete_two_decimal_e_over_e_reading(self) -> None:
        truncated = extract_measurements_from_text(
            "E/E’ 8.2",
            source="ocr:high-contrast",
            confidence=0.93,
        )
        complete = extract_measurements_from_text(
            "E/E 8.23",
            source="ocr:binary",
            confidence=0.78,
        )

        selected = _keep_most_reliable_candidates(truncated + complete)
        measurements, _, conflicts = consolidate_measurement_candidates(selected)

        self.assertEqual(measurements["E_E_linha"], 8.23)
        self.assertEqual(conflicts, 0)

    def test_parses_ge_logiq_e_header_without_clinical_inference(self) -> None:
        payload = parse_ge_logiq_e_header_text(
            """
            VET WORLD
            BOLINHA, Tutor Sintetico 7
            19/07/24 12:57:15
            Idade 3Y
            CAO_P
            """
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["paciente"]["nome"], "Bolinha")
        self.assertEqual(payload["paciente"]["tutor"], "Tutor Sintetico 7")
        self.assertEqual(payload["paciente"]["idade"], "3 anos")
        self.assertEqual(payload["paciente"]["especie"], "Canina")
        self.assertEqual(payload["paciente"]["data_exame"], "2024-07-19")
        self.assertEqual(payload["perfil"], "ge_logiq_e")
        self.assertEqual(payload["fabricante"], "GE")
        self.assertEqual(payload["modelo_equipamento"], "LOGIQ e")

    def test_extracts_explicit_age_and_weight_from_report_text(self) -> None:
        demographics = parse_patient_age_weight("Paciente: Belinha\nIdade: 8 anos\nPeso corporal: 7,35 kg")

        self.assertEqual(demographics, {"idade": "8 anos", "peso": "7.35"})

    def test_calculates_age_in_years_from_birthdate(self) -> None:
        demographics = parse_patient_age_weight(
            "Birthdate: 15/06/2018\nStudy Date: 14/07/2026\nAge: 99 years\nWeight: 7.35 kg"
        )

        self.assertEqual(demographics, {"idade": "8 anos", "peso": "7.35", "data_nascimento": "2018-06-15"})

    def test_calculates_age_in_months_when_younger_than_one_year(self) -> None:
        demographics = parse_patient_age_weight(
            "Birthdate: 20/08/2025\nStudy Date: 11/07/2026"
        )

        self.assertEqual(demographics, {"idade": "10 meses", "peso": "", "data_nascimento": "2025-08-20"})

    def test_calculates_singular_month_from_birthdate(self) -> None:
        demographics = parse_patient_age_weight(
            "Birthdate: 15/05/2026\nExam Date: 15/06/2026"
        )

        self.assertEqual(demographics, {"idade": "1 mês", "peso": "", "data_nascimento": "2026-05-15"})

    def test_accepts_iso_and_unambiguous_month_first_birthdates(self) -> None:
        for birthdate in ("2025-08-20", "08/20/2025"):
            with self.subTest(birthdate=birthdate):
                demographics = parse_patient_age_weight(
                    f"Birthdate: {birthdate}",
                    reference_date=date(2026, 7, 11),
                )
                self.assertEqual(demographics["idade"], "10 meses")

    def test_parses_pdf_text_layer_patient_age_and_weight(self) -> None:
        content = _pdf_bytes(
            [
                "Paciente: Belinha",
                "Birthdate: 20/08/2025  Date 11/07/2026",
                "Peso: 7,35 kg",
                "LVIDd 3.24 cm",
                "LA/Ao 1.62",
            ]
        )

        payload = parse_eco_study_import_content("belinha.pdf", content)

        self.assertEqual(payload["paciente"]["idade"], "10 meses")
        self.assertEqual(payload["paciente"]["peso"], "7.35")
        self.assertEqual(payload["paciente"]["data_exame"], "2026-07-11")

    def test_parses_ge_vivid_iq_aliases_and_report_profile(self) -> None:
        candidates = extract_measurements_from_text(
            """
            D.Raiz Ao 20.55 mm
            D. AE 29.22 mm
            E/A VM 1.25
            T.Des. VM 129 ms
            maxPG VSVE 4.12 mmHg
            maxPG VSVD 2.24 mmHg
            Vmax RM 3.98 m/s
            Vmáx RT 3.53 m/s
            DIVdN 1.817
            """,
            source="ocr:vivid_iq:test",
            confidence=0.99,
        )
        measurements, _, conflicts = consolidate_measurement_candidates(candidates)

        self.assertEqual(measurements["Aorta"], 20.55)
        self.assertEqual(measurements["Atrio_esquerdo"], 29.22)
        self.assertEqual(measurements["E_A"], 1.25)
        self.assertEqual(measurements["TD"], 129)
        self.assertEqual(measurements["Grad_VSVE"], 4.12)
        self.assertNotIn("Grad_aorta", measurements)
        self.assertEqual(measurements["Grad_VSVD"], 2.24)
        self.assertNotIn("Grad_pulmonar", measurements)
        self.assertEqual(measurements["IM_Vmax"], 3.98)
        self.assertEqual(measurements["IT_Vmax"], 3.53)
        self.assertEqual(measurements["DIVEd_normalizado"], 1.817)
        self.assertEqual(conflicts, 0)

        report = parse_ge_vivid_iq_report_text(
            "Cardiac report: Complete\nGE Healthcare Hospital\n"
            "D.Raiz Ao 20.55 mm\nmaxPG VSVE 4.12 mmHg"
        )
        self.assertIsNotNone(report)
        self.assertEqual(report["perfil"], GE_VIVID_IQ_PROFILE)
        self.assertEqual(report["fabricante"], "GE")
        self.assertEqual(report["modelo_equipamento"], "Vivid IQ")
        self.assertEqual(report["paciente"]["nome"], "")

    def test_recognizes_ge_vivid_iq_screen_without_patient_inference(self) -> None:
        self.assertTrue(_looks_like_ge_vivid_iq_screen_text("Reproduzir novamente"))
        self.assertTrue(
            _looks_like_ge_vivid_iq_screen_text(
                "PPVEs 11.26 mm\nDIVEs 27.29 mm\nSIVs 13.46 mm"
            )
        )
        self.assertFalse(_looks_like_ge_vivid_iq_screen_text("TAPSE 23.33 mm"))

    def test_validates_extension_and_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "imagem ou PDF"):
            validate_eco_study_filename("estudo.xml")
        with self.assertRaisesRegex(ValueError, "30MB"):
            validate_eco_study_size(b"x" * (MAX_ECO_STUDY_IMPORT_SIZE + 1))

    @patch("app.services.eco_study_extraction_service._extract_text_with_tesseract")
    def test_parses_image_with_ocr_evidence(self, ocr_mock) -> None:
        ocr_mock.return_value = "LVIDd 3.24 cm\nEF Teich 62 %"

        payload = parse_eco_study_import_content("captura.png", _png_bytes())

        self.assertEqual(payload["medidas"]["DIVEd"], 32.4)
        self.assertEqual(payload["medidas"]["FE_Teicholz"], 62)
        self.assertEqual(payload["meta_importacao_estudo"]["formato"], "png")

    def test_parses_pdf_text_layer_without_ocr(self) -> None:
        content = _pdf_bytes(["LVIDd 3.24 cm", "LA/Ao 1.62", "Vmáx RT 3.53 m/s"])

        payload = parse_eco_study_import_content("estudo.pdf", content)

        self.assertEqual(payload["medidas"]["DIVEd"], 32.4)
        self.assertEqual(payload["medidas"]["AE_Ao"], 1.62)
        self.assertEqual(payload["medidas"]["IT_Vmax"], 3.53)
        self.assertEqual(
            payload["meta_importacao_estudo"]["versao_extrator"],
            ECO_STUDY_EXTRACTOR_VERSION,
        )
        self.assertEqual(payload["meta_importacao_estudo"]["paginas"], 1)
        self.assertTrue(
            all(item["origem"] == "pdf:text" for item in payload["medidas_extraidas"])
        )

    def test_pdf_reports_both_lv_techniques_for_explicit_user_choice(self) -> None:
        content = _pdf_bytes(
            [
                "2D",
                "LVIDd 32 mm",
                "VDF(Teich) 96 ml",
                "FE(Teich) 57 %",
                "M-Mode",
                "LVIDd 30 mm",
                "VDF(Teich) 99 ml",
                "FE(Teich) 66 %",
            ]
        )

        payload = parse_eco_study_import_content("duas-tecnicas.pdf", content)

        self.assertEqual(payload["medidas"]["DIVEd"], 30)
        self.assertEqual(payload["medidas"]["DIVEd_2D"], 32)
        self.assertEqual(payload["medidas"]["VDF"], 99)
        self.assertEqual(payload["medidas"]["VDF_2D"], 96)
        self.assertEqual(payload["medidas"]["FE_Teicholz"], 66)
        self.assertEqual(payload["medidas"]["FE_Teicholz_2D"], 57)
        self.assertEqual(payload["meta_importacao_estudo"]["conflitos"], 0)
        self.assertEqual(
            payload["meta_importacao_estudo"]["tecnicas_ve_detectadas"],
            ["2d", "modo_m"],
        )

    def test_pdf_with_only_2d_selects_2d_for_report(self) -> None:
        content = _pdf_bytes(
            [
                "2D",
                "LVIDd 32 mm",
                "VDF(Teich) 96 ml",
                "FE(Teich) 57 %",
                "Doppler",
                "e' 0.08 m/s",
            ]
        )

        payload = parse_eco_study_import_content("somente-2d.pdf", content)

        self.assertEqual(payload["medidas"]["DIVEd_2D"], 32)
        self.assertEqual(payload["medidas"]["VDF_2D"], 96)
        self.assertEqual(payload["medidas"]["FE_Teicholz_2D"], 57)
        self.assertEqual(payload["medidas"]["VE_tecnica_relatorio"], "2d")
        self.assertEqual(
            payload["meta_importacao_estudo"]["tecnicas_ve_detectadas"],
            ["2d"],
        )

    def test_identifies_ge_vivid_iq_pdf_text_report(self) -> None:
        content = _pdf_bytes(
            [
                "Cardiac report: Complete",
                "GE Healthcare Hospital",
                "D.Raiz Ao 20.55 mm",
                "D. AE 29.22 mm",
                "maxPG VSVE 4.12 mmHg",
            ]
        )

        payload = parse_eco_study_import_content("vivid-report.pdf", content)

        self.assertEqual(payload["medidas"]["Aorta"], 20.55)
        self.assertEqual(payload["medidas"]["Atrio_esquerdo"], 29.22)
        self.assertEqual(payload["medidas"]["Grad_VSVE"], 4.12)
        self.assertEqual(payload["meta_importacao_estudo"]["perfil"], GE_VIVID_IQ_PROFILE)


if __name__ == "__main__":
    unittest.main()
