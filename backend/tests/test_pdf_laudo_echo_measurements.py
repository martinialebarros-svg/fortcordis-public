import os
import sys
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from PIL import Image as PILImage

from pypdf import PdfReader

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.utils.pdf_laudo import (  # noqa: E402
    create_pdf_styles, gerar_pdf_laudo_eco,
    normalizar_medidas_para_pdf, medidas_com_unidade_ambigua,
)
from app.utils.ecocardiograma_medidas import (  # noqa: E402
    extrair_medidas_ecocardiograma_da_descricao,
)
from app.utils.referencia_eco_defaults import aplicar_defaults_publicados_caninos  # noqa: E402


def _base_report(selected_technique: str) -> dict:
    return {
        "paciente": {
            "nome": "Paciente teste",
            "especie": "Canina",
            "raca": "SRD",
            "sexo": "Macho",
            "idade": "5 anos",
            "peso": "10",
            "tutor": "Tutor teste",
            "data_exame": "2026-07-26",
        },
        "medidas": {
            "DIVEd": "30",
            "DIVEd_2D": "32",
            "VDF": "99",
            "VDF_2D": "96",
            "VSF": "34",
            "VSF_2D": "41",
            "FE_Teicholz": "66",
            "FE_Teicholz_2D": "57",
            "DeltaD_FS": "36",
            "DeltaD_FS_2D": "30",
            "VE_tecnica_relatorio": selected_technique,
            "IT_Vmax": "3.6",
            "IT_Grad": "51.84",
            "PAD_estimada": "10",
            "PSAP": "61.84",
            "e_doppler": "0.08",
            "E_TRIV": "2.93",
            "E_E_linha": "14",
        },
        "qualitativa": {},
        "conclusao": "Laudo de teste.",
        "clinica": "Clínica teste",
    }


def _pdf_text(payload: dict) -> str:
    content = gerar_pdf_laudo_eco(payload)
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


class PdfLaudoEchoMeasurementsTest(unittest.TestCase):
    def test_diastolic_alias_normalization_preserves_explicit_canonical_values_and_input(self) -> None:
        aliases = {"MV_E": "Onda_E", "MV_A": "Onda_A", "MV_E_A": "E_A", "MV_DT": "TD",
                   "IVRT": "TRIV", "MV_E_TRIV": "E_TRIV", "TDI_e": "e_doppler",
                   "TDI_a": "a_doppler", "EEp": "E_E_linha"}
        for alias, canonical in aliases.items():
            for value in ("0.87", "0", 0, "", None):
                for canonical_first in (True, False):
                    with self.subTest(alias=alias, value=value, canonical_first=canonical_first):
                        pairs = [(canonical, value), (alias, "0.61")]
                        payload = dict(pairs if canonical_first else reversed(pairs))
                        payload.update({"Diastolica_ondas": "nao_confirmadas", "TDI_metodo": "outro"})
                        before = deepcopy(payload)
                        normalized = normalizar_medidas_para_pdf(payload)
                        self.assertEqual(normalized[canonical], value)
                        self.assertEqual(normalized[alias], "0.61")
                        self.assertEqual(normalized["Diastolica_ondas"], "nao_confirmadas")
                        self.assertEqual(normalized["TDI_metodo"], "outro")
                        self.assertEqual(payload, before)
            legacy_only = {alias: "0.61", "MV_e": "unknown alias remains untouched"}
            normalized = normalizar_medidas_para_pdf(legacy_only)
            self.assertEqual(normalized[canonical], "0.61")
            self.assertEqual(normalized[alias], "0.61")
            self.assertEqual(normalized["MV_e"], legacy_only["MV_e"])
            self.assertEqual(legacy_only, {alias: "0.61", "MV_e": "unknown alias remains untouched"})

    def test_primary_bibliography_follows_qualitative_analysis_in_smaller_type(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"]["peso"] = "15"
        payload["qualitativa"] = {"vasos": "Descrição qualitativa de teste."}
        payload["medidas"]["TAPSE"] = "12"
        payload["medidas"]["TAPSE_metodo"] = "modo_m_apical"
        payload["medidas"]["MAPSE"] = "8"
        payload["referencia_eco"] = aplicar_defaults_publicados_caninos({
            "especie": "Canina", "peso_kg": 15,
            "fs_min": 25, "fs_max": 45,
            "tapse_min": None, "tapse_max": None,
        })

        reader = PdfReader(BytesIO(gerar_pdf_laudo_eco(payload)))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertLess(text.index("ANÁLISE QUALITATIVA"), text.index("REFERÊNCIAS BIBLIOGRÁFICAS"))
        self.assertLess(text.index("Descrição qualitativa de teste"), text.index("Cornell et al. (2004)"))
        self.assertNotIn("Pariaut et al. (2012)", text)
        self.assertIn("Visser et al. (2015)", text)
        self.assertIn("Schober & Luis Fuentes (2001)", text)
        self.assertNotIn("Spalla et al.", text)
        self.assertNotIn("ECOS Vet", text)
        self.assertNotIn("Faixas selecionadas no cadastro", text)
        self.assertNotIn("O cadastro não identifica a publicação", text)
        self.assertLess(create_pdf_styles()["ReferenciaTexto"].fontSize, create_pdf_styles()["Normal"].fontSize)
        last_page = reader.pages[-1].extract_text() or ""
        self.assertIn("Descrição qualitativa de teste", last_page)
        self.assertIn("Médico Veterinário", last_page)
        self.assertIn("REFERÊNCIAS BIBLIOGRÁFICAS", last_page)

    def test_feline_bibliography_uses_feline_studies_only(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"]["especie"] = "Felina"
        payload["medidas"] = {"DIVEd": "15", "TAPSE": "9", "VE_tecnica_relatorio": "modo_m"}
        payload["referencia_eco"] = {"especie": "Felina", "peso_kg": 4}
        text = _pdf_text(payload)
        self.assertIn("Häggström et al. (2016)", text)
        self.assertIn("Spalla et al. (2017)", text)
        self.assertNotIn("Cornell et al.", text)
        self.assertNotIn("Pariaut et al.", text)

    def test_outflow_velocity_bibliography_follows_measured_valve_and_species(self) -> None:
        for species, own_study, other_study in (
            ("Canina", "Petrus et al. (2010)", "Domanjko Petric et al. (2012)"),
            ("Felina", "Domanjko Petric et al. (2012)", "Petrus et al. (2010)"),
        ):
            for measurement in ("Vmax_aorta", "Vmax_pulmonar"):
                with self.subTest(species=species, measurement=measurement):
                    payload = _base_report("modo_m")
                    payload["paciente"]["especie"] = species
                    payload["medidas"] = {measurement: "1.10"}
                    payload["referencia_eco"] = {"especie": species, "peso_kg": 10 if species == "Canina" else 4}
                    text = _pdf_text(payload)
                    bibliography = text.partition("REFERÊNCIAS BIBLIOGRÁFICAS")[2]

                    self.assertIn(own_study, bibliography)
                    self.assertNotIn(other_study, bibliography)
                    self.assertNotIn("Cornell et al.", bibliography)
                    self.assertNotIn("Häggström et al.", bibliography)

            with self.subTest(species=species, measurement="unmeasured"):
                payload = _base_report("modo_m")
                payload["paciente"]["especie"] = species
                payload["medidas"] = {"Vmax_VSVE": "1.10", "Grad_aorta": "4.84"}
                payload["referencia_eco"] = {"especie": species, "peso_kg": 10 if species == "Canina" else 4}
                text = _pdf_text(payload)
                self.assertNotIn("Petrus et al. (2010)", text)
                self.assertNotIn("Domanjko Petric et al. (2012)", text)

    def test_outflow_velocity_study_is_cited_without_a_selected_catalog_range(self) -> None:
        for species, study in (
            ("Canina", "Petrus et al. (2010)"),
            ("Felina", "Domanjko Petric et al. (2012)"),
        ):
            with self.subTest(species=species):
                payload = _base_report("modo_m")
                payload["paciente"]["especie"] = species
                payload["medidas"] = {"Vmax_aorta": "1.10"}
                payload.pop("referencia_eco", None)
                text = _pdf_text(payload)

                self.assertIn("Vmax aorta\n1.10 m/s\n--", text)
                self.assertIn(study, text)

    def test_outflow_velocity_studies_do_not_claim_the_legacy_catalog_range(self) -> None:
        for species, study, expected_values in (
            ("Canina", "Petrus et al. (2010)", ("1,26", "0,13", "0,95", "0,18")),
            ("Felina", "Domanjko Petric et al. (2012)", ("0,77", "1,40", "0,65", "1,21")),
        ):
            with self.subTest(species=species):
                payload = _base_report("modo_m")
                payload["paciente"]["especie"] = species
                payload["medidas"] = {"Vmax_aorta": "1.10", "Vmax_pulmonar": "0.90"}
                payload["referencia_eco"] = {
                    "especie": species,
                    "peso_kg": 10 if species == "Canina" else 4,
                    "vmax_ao_min": 0,
                    "vmax_ao_max": 2.2,
                    "vmax_pulm_min": 0,
                    "vmax_pulm_max": 2.2,
                }
                text = _pdf_text(payload)
                bibliography = text.partition("REFERÊNCIAS BIBLIOGRÁFICAS")[2]

                self.assertNotIn("0.00 - 2.20 m/s", text)
                self.assertIn(study, bibliography)
                self.assertNotIn("2.20", bibliography)
                self.assertNotIn("2,20", bibliography)
                for value in expected_values:
                    self.assertRegex(bibliography, value.replace(",", "[,.]"))
                if species == "Canina":
                    self.assertIn("30 cães", bibliography)
                    self.assertIn("DP", bibliography)
                else:
                    self.assertIn("53 gatos", bibliography)
                    self.assertIn("mínimos e máximos", bibliography)
                    self.assertIn("observados", bibliography)

    def test_feline_pdf_omits_canine_index_and_derives_atrial_and_lvot_markers(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"].update({"especie": "Felina", "peso": "2.3"})
        payload["medidas"] = {
            "DIVEd": "11.46", "DIVEd_normalizado": "0.90",
            "AE_diametro_max": "18", "AE_diametro_min": "13.5",
            "Fluxo_auricular": "0.18", "Vmax_aorta": "0.69", "Vmax_VSVE": "2.5",
            "VE_tecnica_relatorio": "modo_m",
        }
        payload["referencia_eco"] = {"especie": "Felina", "peso_kg": 2.3}
        text = _pdf_text(payload)
        self.assertNotIn("DIVEd normalizado (DIVEd [cm] / peso^0,294)", text)
        self.assertEqual(payload["medidas"]["DIVEd_normalizado"], "0.90")
        self.assertIn("AE - diâmetro máximo\n18.00 mm", text)
        self.assertIn("AE - diâmetro mínimo\n13.50 mm", text)
        self.assertIn("Fração de encurtamento do AE\n25.00 %\n--", text)
        self.assertIn("Velocidade máxima do apêndice atrial esquerdo\n0.18 m/s\n--", text)
        self.assertIn("Vmax via de saída do VE\n2.50 m/s\n--", text)
        self.assertIn("Gradiente via de saída do VE (calculado: 4 × V²)\n25.00 mmHg", text)
        self.assertIn("Vmax aorta\n0.69 m/s", text)
        self.assertIn("Fuentes et al. (2020)", text)
        self.assertIn("Schober et al. (2006)", text)
        self.assertNotIn("Cornell et al.", text)

    def test_feline_pdf_does_not_derive_atrial_fraction_from_inverted_diameters(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"]["especie"] = "Felina"
        payload["medidas"] = {"AE_diametro_max": "13.5", "AE_diametro_min": "18"}
        text = _pdf_text(payload)
        self.assertIn("AE - diâmetro máximo\n13.50 mm", text)
        self.assertIn("AE - diâmetro mínimo\n18.00 mm", text)
        self.assertNotIn("Fração de encurtamento do AE", text)

    def test_2d_unknown_catalog_range_adds_no_bibliography_or_catalog_note(self) -> None:
        payload = _base_report("2d")
        payload["medidas"] = {"DIVEd_2D": "32", "VE_tecnica_relatorio": "2d"}
        payload["referencia_eco"] = {"especie": "Canina", "peso_kg": 10, "lvid_d_min": 20, "lvid_d_max": 40}
        text = _pdf_text(payload)
        self.assertNotIn("Cornell et al.", text)
        self.assertNotIn("REFERÊNCIAS BIBLIOGRÁFICAS", text)
        self.assertNotIn("Faixas selecionadas no cadastro", text)
        self.assertNotIn("ECOS Vet", text)

    def test_confirmed_2d_view_adds_only_applicable_visser_ranges_and_citation(self) -> None:
        payload = _base_report("2d")
        payload["paciente"]["peso"] = "13.6"
        payload["medidas"] = {
            "VE_tecnica_relatorio": "2d", "VE_vista_2D": "eixo_curto",
            "DIVEd_2D": "33.53", "DIVES_2D": "22.87", "DeltaD_FS_2D": "31.8",
            "SIVd_2D": "8.36", "FE_Teicholz_2D": "61",
        }
        payload["referencia_eco"] = {"especie": "Canina", "peso_kg": 15, "lvid_d_min": 30, "lvid_d_max": 40}
        text = _pdf_text(payload)
        self.assertIn("26.01 - 36.73 mm", text)
        self.assertIn("15.58 - 25.87 mm", text)
        self.assertIn("21.90 - 49.30 %", text)
        self.assertIn("DIVEd normalizado 2D - Visser (DIVEd [cm] / peso^0,316)\n1.47\n1.14 - 1.61", text)
        self.assertIn("Visser et al. (2019)", text)
        self.assertNotIn("Cornell et al.", text)
        self.assertIn("SIVd 2D (Septo interventricular em diástole)\n8.36 mm\n--", text)
        self.assertIn("FE 2D (Teicholz)\n61.00 %\n--", text)

        payload["medidas"]["VE_vista_2D"] = ""
        payload["medidas"]["DIVEd_normalizado_2D"] = "1.56"
        without_view = _pdf_text(payload)
        self.assertNotIn("Visser et al. (2019)", without_view)
        self.assertNotIn("26.01 - 36.73 mm", without_view)
        self.assertNotIn("DIVEd normalizado 2D - Visser", without_view)

        payload["medidas"]["VE_vista_2D"] = "eixo_curto"
        payload["paciente"]["especie"] = "Felina"
        self.assertNotIn("DIVEd normalizado 2D - Visser", _pdf_text(payload))

    def test_2d_fs_requires_same_diameter_pair_and_study_weight(self) -> None:
        payload = _base_report("2d")
        payload["medidas"] = {
            "VE_tecnica_relatorio": "2d", "VE_vista_2D": "eixo_curto",
            "DIVEd_2D": "33.53", "DIVES_2D": "22.87", "DeltaD_FS_2D": "50",
        }
        payload["referencia_eco"] = {"especie": "Canina", "peso_kg": 10}
        text = _pdf_text(payload)
        self.assertNotIn("21.90 - 49.30 %", text)
        payload["paciente"]["peso"] = "80"
        text = _pdf_text(payload)
        self.assertNotIn("Visser et al. (2019)", text)

    def test_pdf_uses_sourced_fs_and_omits_teichholz_ef_interval(self) -> None:
        payload = _base_report("modo_m")
        payload["referencia_eco"] = aplicar_defaults_publicados_caninos({
            "especie": "Canina", "peso_kg": 10,
            "fs_min": 25, "fs_max": 45,
            "ef_min": 50, "ef_max": 85,
        })
        text = _pdf_text(payload)
        self.assertIn("20.70 - 51.90 %", text)
        self.assertNotIn("50.00 - 85.00 %", text)
        self.assertIn("Visser et al. (2019)", text)
        self.assertIn("10.1111/jvim.15562", text)
        self.assertNotIn("ECOS Vet", text)
        self.assertNotIn("FE Teichholz: intervalo de referência não validado", text)
        self.assertIn("66.00 %", text)

    def test_legacy_mixed_units_keep_already_mm_values_in_pdf(self) -> None:
        legacy = {
            "DIVEd": "3", "SIVd": "0.7", "PLVEd": "0.8",
            "DIVES": "1.5", "SIVs": "1", "PLVES": "1.3",
            "Aorta": "13.1", "TAPSE": "10", "MAPSE": "8",
            "VE_tecnica_relatorio": "modo_m",
        }
        normalized = normalizar_medidas_para_pdf(legacy)
        self.assertEqual(normalized["DIVEd"], "3")
        self.assertEqual(normalized["SIVd"], "0.7")
        self.assertIn("SIVd", medidas_com_unidade_ambigua(legacy))
        self.assertEqual(normalized["Aorta"], "13.1")
        self.assertEqual(normalized["TAPSE"], "10")
        self.assertEqual(normalized["MAPSE"], "8")
        self.assertEqual(normalizar_medidas_para_pdf({**legacy, "Aorta": "1.3"})["Aorta"], "1.3")

        payload = _base_report("modo_m")
        payload["medidas"] = legacy
        text = _pdf_text(payload)
        self.assertIn("TAPSE (excursão sistólica do plano anular tricúspide)\n10.00 mm", text)
        self.assertIn("MAPSE (excursão sistólica do plano anular mitral)\n8.00 mm", text)
        self.assertIn("Aorta\n13.10 mm", text)
        self.assertIn("SIVd (Septo interventricular em diástole)\n0.70 (unidade a\nconfirmar)", text)

    def test_ambiguous_septum_is_not_multiplied_or_compared_with_reference(self) -> None:
        measurements = {"DIVEd": "2.5", "DIVES": "1.5", "Atrio_esquerdo": "2.0", "SIVd": "3.0"}
        self.assertEqual(normalizar_medidas_para_pdf(measurements)["SIVd"], "3.0")
        self.assertIn("SIVd", medidas_com_unidade_ambigua(measurements))
        payload = _base_report("modo_m")
        payload["medidas"] = measurements
        text = _pdf_text(payload)
        self.assertIn("SIVd (Septo interventricular em diástole)\n3.00 (unidade a\nconfirmar)", text)
        self.assertNotIn("SIVd (Septo interventricular em diástole)\n30.00 mm", text)
        self.assertNotIn("DIVEd normalizado (DIVEd [cm] / peso^0,294)", text)

    def test_confirmed_units_are_converted_individually_without_changing_raw_values(self) -> None:
        measurements = {
            "DIVEd": "2.5", "DIVES": "1.5", "Atrio_esquerdo": "2.0", "SIVd": "3.0",
            "unidade_confirmada_DIVEd": "cm", "unidade_confirmada_SIVd": "mm",
        }
        self.assertEqual(measurements["DIVEd"], "2.5")
        self.assertEqual(normalizar_medidas_para_pdf(measurements)["DIVEd"], "25.0")
        self.assertEqual(normalizar_medidas_para_pdf(measurements)["SIVd"], "3.0")
        self.assertEqual(medidas_com_unidade_ambigua(measurements), {"DIVES", "Atrio_esquerdo"})

        payload = _base_report("modo_m")
        payload["medidas"] = measurements
        text = _pdf_text(payload)
        self.assertIn("DIVEd (Diâmetro interno do VE em diástole)\n25.00 mm", text)
        self.assertIn("SIVd (Septo interventricular em diástole)\n3.00 mm", text)
        self.assertIn("DIVEs (Diâmetro interno do VE em sístole)\n1.50 (unidade a\nconfirmar)", text)
        self.assertIn("DIVEd normalizado (DIVEd [cm] / peso^0,294)", text)

    def test_pdf_numbers_images_and_uses_only_recorded_captions(self) -> None:
        image_buffer = BytesIO()
        PILImage.new("RGB", (320, 240), "white").save(image_buffer, format="JPEG")
        content = image_buffer.getvalue()
        payload = _base_report("modo_m")
        payload["medidas"] = {"DIVEd": "30", "VE_tecnica_relatorio": "modo_m"}
        payload["imagens"] = [
            {"conteudo": content, "descricao": "Doppler da IT <3,6 m/s>"},
            {"conteudo": content, "descricao": ""},
            *[content for _ in range(4)],
        ]

        content_pdf = gerar_pdf_laudo_eco(payload)
        reader = PdfReader(BytesIO(content_pdf))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertIn("Imagem 1 - Doppler da IT <3,6 m/s>", text)
        self.assertIn("Imagem 2", text)
        self.assertIn("Imagem 6", text)
        self.assertEqual(text.count("Imagem 1"), 1)
        self.assertEqual(len(reader.pages), 2)
        image_page_text = reader.pages[1].extract_text() or ""
        self.assertIn("Paciente: Paciente teste", image_page_text)
        self.assertIn("Data do exame: 2026-07-26", image_page_text)

    def test_short_qualitative_stays_on_first_page(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {"DIVEd": "30", "VE_tecnica_relatorio": "modo_m"}
        payload["qualitativa"] = {"pericardio": "Sem derrame pericárdico."}
        reader = PdfReader(BytesIO(gerar_pdf_laudo_eco(payload)))

        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text() or ""
        self.assertIn("ANÁLISE QUALITATIVA", text)
        self.assertIn("Sem derrame pericárdico.", text)
        self.assertEqual(text.count("Médico Veterinário"), 1)

    def test_report_at_page_end_without_images_has_no_footer_only_page(self) -> None:
        # Frozen real layout boundary: the narrative/signature fit on one page,
        # but an unrelated trailing gap used to spill onto a second empty page.
        payload = {
            "paciente": {
                "nome": "QA LIMITE DE PAGINA", "especie": "Canina", "raca": "SRD",
                "sexo": "Macho", "idade": "4a", "peso": "10", "tutor": "QA TUTOR",
                "data_exame": "2026-11-04",
            },
            "medidas": {"DIVEd": "30", "VE_tecnica_relatorio": "modo_m"},
            "qualitativa": {
                "valvas": "Texto sintetico de avaliacao ecocardiografica, sem finalidade clinica. " * 31,
            },
            "conclusao": "EXAME INTEIRAMENTE SINTETICO PARA TESTE DE SOFTWARE.",
            "clinica": "CLINICA QA", "imagens": [],
        }
        bodies = []
        for preview in (False, True):
            with self.subTest(preview=preview):
                content = gerar_pdf_laudo_eco(
                    payload, nome_veterinario="QA", texto_rodape="RODAPE SINTETICO", preview=preview,
                )
                reader = PdfReader(BytesIO(content))
                self.assertEqual(len(reader.pages), 1)
                body = reader.pages[0].extract_text() or ""
                self.assertIn("Texto sintetico de avaliacao ecocardiografica", body)
                self.assertIn("Médico Veterinário", body)
                self.assertIn("RODAPE SINTETICO", body)
                self.assertNotIn("IMAGENS", body)
                self.assertEqual(body.count("PRÉVIA - NÃO EMITIDO"), int(preview))
                bodies.append(body.replace("PRÉVIA - NÃO EMITIDO\n", ""))
        self.assertEqual(bodies[0], bodies[1])

    def test_moderate_report_does_not_leave_signature_alone_on_a_page(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"].update({
            "nome": "PACIENTE DEMONSTRATIVO", "tutor": "Demonstração",
            "data_exame": "24/09/2026",
        })
        payload["clinica"] = "Clínica demonstrativa"
        payload["conclusao"] = (
            "EXEMPLO SINTÉTICO - SEM VALIDADE CLÍNICA. "
            "Este documento mostra apenas a estrutura e a leitura do PDF."
        )
        payload["medidas"] = {
            "DIVEd": "30", "SIVd": "6", "Aorta": "17", "Atrio_esquerdo": "19",
            "AE_Ao": "1.12", "Onda_E": "0.70", "Onda_A": "0.50", "E_A": "1.40",
            "VE_tecnica_relatorio": "modo_m",
        }
        payload["qualitativa"] = {
            "valvas": "Texto demonstrativo de avaliação qualitativa.\n- Segundo item preservado.",
            "pericardio": "Texto demonstrativo sem achado clínico real.",
        }

        no_images = PdfReader(BytesIO(gerar_pdf_laudo_eco(payload)))
        self.assertEqual(len(no_images.pages), 2)
        last_text = no_images.pages[-1].extract_text() or ""
        self.assertIn("Pericárdio", last_text)
        self.assertIn("Médico Veterinário", last_text)

        image_buffer = BytesIO()
        PILImage.new("RGB", (680, 440), "white").save(image_buffer, format="JPEG")
        payload["imagens"] = [image_buffer.getvalue() for _ in range(6)]
        with_images = PdfReader(BytesIO(gerar_pdf_laudo_eco(payload)))
        self.assertEqual(len(with_images.pages), 2)
        image_page_text = with_images.pages[-1].extract_text() or ""
        self.assertIn("Médico Veterinário", image_page_text)
        self.assertIn("Imagem 6", image_page_text)

    def test_long_report_keeps_signature_with_final_qualitative_group(self) -> None:
        payload = _base_report("modo_m")
        payload["conclusao"] = "\n".join(
            f"* Conclusão demonstrativa {i}: texto sintético para testar a paginação."
            for i in range(5)
        )
        payload["medidas"].update({
            "SIVd": "8", "PLVEd": "8", "DIVES": "13", "SIVs": "12",
            "PLVES": "14", "TAPSE": "10", "Aorta": "14", "Atrio_esquerdo": "20",
            "AE_Ao": "1.43", "Vmax_aorta": "1.09", "Grad_aorta": "4.73",
            "Vmax_pulmonar": "0.49", "Grad_pulmonar": "0.95",
            "Onda_E": "0.95", "Onda_A": "0.67", "E_A": "1.42",
            "TD": "136", "TRIV": "39", "E_TRIV": "2.44",
            "IM_Vmax": "5.66", "IM_Grad": "128.14", "IT_Vmax": "3.12",
            "IT_Grad": "38.94", "PAD_estimada": "5", "PSAP": "43.94",
        })
        payload["qualitativa"] = {
            "valvas": "\n".join(
                f"- Valva {i}: descrição demonstrativa com várias palavras para ocupar a página."
                for i in range(4)
            ),
            "camaras": "\n".join(
                f"- Câmara {i}: descrição demonstrativa com várias palavras para ocupar a página."
                for i in range(3)
            ),
            "ad_vd": "\n".join(
                f"- Câmara direita {i}: descrição demonstrativa para testar quebra de página."
                for i in range(2)
            ),
            "funcao": "\n".join(
                f"- Função {i}: descrição demonstrativa com várias palavras para ocupar a página."
                for i in range(8)
            ),
            "pericardio": "Descrição demonstrativa de pericárdio para testar paginação.",
            "vasos": "\n".join(
                f"- Marcador final {i} da análise qualitativa; deve acompanhar a assinatura."
                for i in range(3)
            ),
        }
        image_buffer = BytesIO()
        PILImage.new("RGB", (320, 240), "white").save(image_buffer, format="JPEG")
        signature_buffer = BytesIO()
        PILImage.new("RGB", (300, 100), "white").save(signature_buffer, format="PNG")
        payload["imagens"] = [image_buffer.getvalue() for _ in range(12)]

        reader = PdfReader(BytesIO(gerar_pdf_laudo_eco(
            payload,
            assinatura_bytes=signature_buffer.getvalue(),
            nome_veterinario="Dra. Exemplo",
        )))
        pages = [page.extract_text() or "" for page in reader.pages]
        signature_pages = [text for text in pages if "Dra. Exemplo" in text]
        self.assertEqual(len(signature_pages), 1)
        self.assertIn("Marcador final 2 da análise qualitativa", signature_pages[0])
        self.assertEqual(len(pages), 5)
        self.assertIn("Imagem 1", pages[3])
        self.assertIn("Imagem 12", pages[4])
        self.assertIn("Imagem 12", "\n".join(pages))

    def test_image_numbers_and_patient_identification_continue_across_pages(self) -> None:
        image_buffer = BytesIO()
        PILImage.new("RGB", (320, 240), "white").save(image_buffer, format="JPEG")
        payload = _base_report("modo_m")
        payload["medidas"] = {"DIVEd": "30", "VE_tecnica_relatorio": "modo_m"}
        payload["imagens"] = [image_buffer.getvalue() for _ in range(13)]
        reader = PdfReader(BytesIO(gerar_pdf_laudo_eco(payload)))

        self.assertEqual(len(reader.pages), 4)
        for page in reader.pages[1:]:
            text = page.extract_text() or ""
            self.assertIn("Paciente: Paciente teste", text)
            self.assertIn("Data do exame: 2026-07-26", text)
        self.assertIn("Imagem 13", reader.pages[-1].extract_text() or "")

    def test_image_grid_repeats_identification_when_long_captions_split_a_group(self) -> None:
        image_buffer = BytesIO()
        PILImage.new("RGB", (320, 240), "white").save(image_buffer, format="JPEG")
        payload = _base_report("modo_m")
        payload["medidas"] = {"DIVEd": "30", "VE_tecnica_relatorio": "modo_m"}
        payload["imagens"] = [
            {
                "conteudo": image_buffer.getvalue(),
                "descricao": "Doppler da valva " + "registro " * 30,
            }
            for _ in range(6)
        ]

        reader = PdfReader(BytesIO(gerar_pdf_laudo_eco(payload)))
        image_pages = [
            page.extract_text() or ""
            for page in reader.pages
            if "Imagem " in (page.extract_text() or "")
        ]

        self.assertEqual(len(image_pages), 2)
        self.assertIn("Imagem 1", image_pages[0])
        self.assertIn("Imagem 6", image_pages[1])
        for text in image_pages:
            self.assertIn("IMAGENS", text)
            self.assertIn("Paciente: Paciente teste", text)
            self.assertIn("Data do exame: 2026-07-26", text)


    def test_pdf_omits_unmeasured_rows_and_unavailable_reference_ranges(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {"DIVEd": "30", "VE_tecnica_relatorio": "modo_m"}
        text = _pdf_text(payload)

        self.assertIn("30.00 mm", text)
        self.assertIn("Faixas de referência indisponíveis", text)
        self.assertLess(text.index("CONCLUSÃO"), text.index("ANÁLISE QUANTITATIVA"))
        self.assertEqual(text.count("CONCLUSÃO"), 1)
        self.assertNotIn("16.00 - 24.00 mm", text)
        self.assertNotIn("Vmax aorta", text)
        self.assertNotIn("Regurgitações", text)

    def test_pdf_uses_only_complete_selected_reference_ranges(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {"DIVEd": "30", "SIVd": "7", "VE_tecnica_relatorio": "modo_m"}
        payload["referencia_eco"] = {
            "especie": "Canina", "peso_kg": 10,
            "lvid_d_min": 20, "lvid_d_max": 40,
            "ivs_d_min": 5,
        }
        text = _pdf_text(payload)

        self.assertIn("20.00 - 40.00 mm", text)
        self.assertNotIn("3.50 - 5.50 mm", text)
        self.assertNotIn("Faixas selecionadas no cadastro", text)
        self.assertNotIn("TAPSE pode usar faixa auxiliar por peso do sistema", text)
        self.assertNotIn("Traço indica faixa indisponível", text)

    def test_pdf_does_not_apply_m_mode_ranges_to_2d(self) -> None:
        payload = _base_report("2d")
        payload["medidas"] = {
            "VE_tecnica_relatorio": "2d", "DIVEd_2D": "32", "FE_Teicholz_2D": "57",
        }
        payload["referencia_eco"] = {
            "especie": "Canina", "peso_kg": 10,
            "lvid_d_min": 20, "lvid_d_max": 40,
            "ef_min": 50, "ef_max": 85,
        }
        text = _pdf_text(payload)
        self.assertIn("DIVEd 2D (Diâmetro interno do VE em diástole)\n32.00 mm\n--", text)
        self.assertIn("FE 2D (Teicholz)\n57.00 %\n--", text)
        self.assertNotIn("20.00 - 40.00 mm", text)
        self.assertNotIn("50.00 - 85.00 %", text)

    def test_pdf_keeps_measured_mapse_without_unsupported_auxiliary_range(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {
            "TAPSE": "12", "TAPSE_metodo": "modo_m_apical", "MAPSE": "8", "VE_tecnica_relatorio": "modo_m",
        }
        payload["referencia_eco"] = aplicar_defaults_publicados_caninos({
            "especie": "Canina", "peso_kg": 10,
            "tapse_min": None, "tapse_max": None,
            "mapse_min": None, "mapse_max": None,
        })
        text = _pdf_text(payload)

        self.assertIn("TAPSE (excursão sistólica do plano anular tricúspide)\n12.00 mm\n9.20 - 14.70 mm", text)
        self.assertIn("MAPSE (excursão sistólica do plano anular mitral)\n8.00 mm\n--", text)

    def test_direct_raw_payload_cannot_apply_unsupported_doppler_or_diastolic_ranges(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {"Vmax_aorta": "1.26", "Onda_E": "0.80", "TD": "120"}
        raw_reference = {
            "especie": "Canina", "peso_kg": 10,
            "vmax_ao_min": 0, "vmax_ao_max": 2.2,
            "mv_e_min": 0.5, "mv_e_max": 1.09, "mv_dt_min": 0, "mv_dt_max": 160,
        }
        payload["referencia_eco"] = raw_reference
        text = _pdf_text(payload)
        self.assertIn("Vmax aorta\n1.26 m/s\n--", text)
        self.assertIn("Onda E\n0.80 m/s\n--", text)
        self.assertNotIn("0.00 - 2.20 m/s", text)
        self.assertNotIn("0.50 - 1.09 m/s", text)
        self.assertNotIn("0.00 - 160.00 ms", text)
        self.assertEqual(raw_reference["vmax_ao_max"], 2.2)

    def test_tapse_requires_its_own_acquisition_confirmation_in_pdf(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {"TAPSE": "12", "VE_tecnica_relatorio": "modo_m"}
        payload["referencia_eco"] = {"especie": "Canina", "peso_kg": 10}
        for method in ("", "2d"):
            with self.subTest(method=method):
                payload["medidas"]["TAPSE_metodo"] = method
                text = _pdf_text(payload)
                self.assertIn("TAPSE (excursão sistólica do plano anular tricúspide)\n12.00 mm\n--", text)
                self.assertNotIn("Visser et al. (2015)", text)
                self.assertNotIn("Pariaut et al. (2012)", text)
        payload["medidas"]["TAPSE_metodo"] = "modo_m_apical"
        text = _pdf_text(payload)
        self.assertIn("9.20 - 14.70 mm", text)
        self.assertIn("Visser et al. (2015)", text)

    def test_pdf_blocks_structural_catalog_ranges_beyond_eligible_weight_coverage(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"]["peso"] = "20"
        payload["medidas"] = {"DIVEd": "35", "VE_tecnica_relatorio": "modo_m"}
        payload["referencia_eco"] = {
            "especie": "Canina", "peso_kg": 15, "lvid_d_min": 20, "lvid_d_max": 40,
            "catalog_weight_min": 5, "catalog_weight_max": 15,
        }
        self.assertIn("DIVEd (Diâmetro interno do VE em diástole)\n35.00 mm\n--", _pdf_text(payload))

    def test_pdf_does_not_mix_species_or_substitute_reference_weight_for_missing_patient_weight(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {"DIVEd": "30", "VE_tecnica_relatorio": "modo_m"}
        payload["referencia_eco"] = {"especie": "Canina", "peso_kg": 10, "lvid_d_min": 20, "lvid_d_max": 40}
        payload["paciente"]["peso"] = ""
        self.assertNotIn("20.00 - 40.00 mm", _pdf_text(payload))
        payload["paciente"].update({"peso": "4", "especie": "Felina"})
        self.assertNotIn("20.00 - 40.00 mm", _pdf_text(payload))

    def test_feline_ae_ao_uses_weight_specific_prediction_interval_after_confirmation(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"].update({"peso": "4", "especie": "Felina"})
        payload["medidas"] = {"AE_Ao": "1.46"}
        payload["referencia_eco"] = {
            "especie": "Felina", "peso_kg": 4, "la_ao_min": 0.88, "la_ao_max": 1.5,
        }
        without_method = _pdf_text(payload)
        self.assertNotIn("0.88 - 1.50", without_method)
        self.assertNotIn("0.88 - 1.43", without_method)
        payload["medidas"]["AE_Ao_metodo"] = "2d_eixo_curto_diastole_inicial"
        text = _pdf_text(payload)
        self.assertIn("0.88 - 1.43", text)
        self.assertNotIn("0.88 - 1.50", text)
        self.assertIn("Häggström et al. (2016)", text)

    def test_canine_ae_ao_pdf_shows_method_specific_clinical_limit_without_catalog(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"].update({"nome": "Café teste", "idade": "7m", "peso": "3.6"})
        payload["medidas"] = {
            "Aorta": "9.76", "Atrio_esquerdo": "13.73", "AE_Ao": "1.41",
            "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial",
            "VE_tecnica_relatorio": "modo_m",
        }
        payload["qualitativa"] = {"vasos": "Descrição qualitativa preservada."}
        original = deepcopy(payload)
        text = _pdf_text(payload)
        compact_text = " ".join(text.split())

        self.assertIn("AE/Ao (Átrio esquerdo/Aorta)\n1.41\n<1,60 (2D, eixo curto)", text)
        self.assertIn("eixo curto paraesternal direito na base cardíaca", compact_text)
        self.assertIn("primeira imagem após o fechamento aórtico", compact_text)
        self.assertIn("Limiar clínico geral; interpretar em conjunto", compact_text)
        self.assertIn("Traço indica faixa de referência indisponível.", text)
        self.assertNotIn("Faixas de referência indisponíveis para este paciente", text)
        self.assertNotIn("cadastro", text)
        self.assertNotIn("0.80 - 1.60", text)
        self.assertNotIn("≤1,60", text)
        self.assertNotIn("adultos", text)
        self.assertNotIn("predição", text)
        self.assertLess(text.index("ANÁLISE QUALITATIVA"), text.index("REFERÊNCIAS BIBLIOGRÁFICAS"))
        self.assertLess(text.index("Médico Veterinário"), text.index("REFERÊNCIAS BIBLIOGRÁFICAS"))
        self.assertIn("Rishniw & Erb (2000)", text)
        self.assertIn("10.1111/j.1939-1676.2000.tb02252.x", text)
        self.assertIn("Rishniw (2023)", text)
        self.assertIn("10.1016/j.jvc.2023.04.003", text)
        self.assertNotIn("método sueco", text)
        self.assertNotIn("Hansson et al.", text)
        self.assertEqual(payload, original)

    def test_explicit_swedish_ae_ao_method_adds_its_own_method_studies_to_canine_pdf(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {
            "AE_Ao": "1.41", "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial_sueco",
        }
        original = deepcopy(payload)
        text = _pdf_text(payload)
        compact_text = " ".join(text.split())
        self.assertIn("AE/Ao (Átrio esquerdo/Aorta)\n1.41\n<1,60 (2D, eixo curto)", text)
        self.assertIn("método sueco (Hansson et al., 2002)", compact_text)
        self.assertIn("primeira imagem após o fechamento aórtico", compact_text)
        bibliography = text.partition("REFERÊNCIAS BIBLIOGRÁFICAS")[2]
        self.assertIn("Hansson et al. (2002)", bibliography)
        self.assertIn("10.1111/j.1740-8261.2002.tb01051.x", bibliography)
        self.assertIn("Georgiev et al. (2013)", bibliography)
        self.assertIn("10.1016/j.jvc.2013.02.002", bibliography)
        self.assertIn("Rishniw (2023)", bibliography)
        self.assertNotIn("Rishniw & Erb (2000)", bibliography)
        self.assertNotIn("0.80 - 1.60", text)
        self.assertEqual(payload, original)

    def test_swedish_ae_ao_method_does_not_apply_canine_threshold_or_feline_interval_to_cats(self) -> None:
        payload = _base_report("modo_m")
        payload["paciente"].update({"especie": "Felina", "peso": "4"})
        payload["medidas"] = {
            "AE_Ao": "1.41", "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial_sueco",
        }
        payload["referencia_eco"] = {
            "especie": "Felina", "peso_kg": 4, "la_ao_min": .88, "la_ao_max": 1.5,
        }
        text = _pdf_text(payload)
        self.assertIn("AE/Ao (Átrio esquerdo/Aorta)\n1.41\n--", text)
        self.assertNotIn("<1,60", text)
        self.assertNotIn("0.88 - 1.43", text)
        self.assertNotIn("Hansson", text)
        self.assertNotIn("Georgiev", text)
        self.assertNotIn("Rishniw", text)

    def test_canine_ae_ao_clinical_limit_is_independent_of_weight_and_legacy_catalog(self) -> None:
        for weight in ("", "1", "100", "nan"):
            with self.subTest(weight=weight):
                payload = _base_report("modo_m")
                payload["paciente"]["peso"] = weight
                payload["medidas"] = {
                    "AE_Ao": "1,60", "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial",
                }
                payload["referencia_eco"] = {
                    "especie": "Canina", "peso_kg": 10,
                    "la_ao_min": 0.8, "la_ao_max": 1.6,
                    "catalog_weight_min": 5, "catalog_weight_max": 15,
                }
                text = _pdf_text(payload)
                self.assertIn("1.60\n<1,60 (2D, eixo curto)", text)
                self.assertNotIn("0.80 - 1.60", text)
                self.assertNotIn("Normal", text)
                self.assertIn("Rishniw (2023)", text)

    def test_canine_ae_ao_limit_is_not_applied_without_confirmed_method_or_to_other_species(self) -> None:
        cases = [("Canina", method) for method in (None, "", "outro", "modo_m", "eixo_longo")]
        cases.extend((species, "2d_eixo_curto_diastole_inicial")
                     for species in ("Felina", "", "Outra"))
        for species, method in cases:
            with self.subTest(species=species, method=method):
                payload = _base_report("modo_m")
                payload["paciente"]["especie"] = species
                payload["medidas"] = {"AE_Ao": "1.41"}
                if method is not None:
                    payload["medidas"]["AE_Ao_metodo"] = method
                original = deepcopy(payload)
                text = _pdf_text(payload)
                self.assertIn("AE/Ao (Átrio esquerdo/Aorta)\n1.41\n--", text)
                self.assertNotIn("<1,60", text)
                self.assertNotIn("Limiar clínico geral", text)
                self.assertNotIn("Rishniw", text)
                self.assertEqual(payload, original)

    def test_canine_ae_ao_limit_requires_a_positive_finite_numeric_ratio(self) -> None:
        for value in (None, "", "0", "-1", "nan", "inf", "-inf", "não aferido", True):
            with self.subTest(value=value):
                payload = _base_report("modo_m")
                payload["medidas"] = {
                    "AE_Ao": value, "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial",
                }
                text = _pdf_text(payload)
                self.assertNotIn("<1,60", text)
                self.assertNotIn("Limiar clínico geral", text)
                self.assertNotIn("Rishniw", text)

    def test_canine_ae_ao_limit_is_withheld_when_source_diameter_units_are_ambiguous(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = {
            "DIVEd": "2.5", "DIVES": "1.5", "Aorta": "1.0", "Atrio_esquerdo": "1.4",
            "AE_Ao": "1.4", "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial",
        }
        ambiguous_text = _pdf_text(payload)
        self.assertIn("AE/Ao (Átrio esquerdo/Aorta)\n1.40\n--", ambiguous_text)
        self.assertNotIn("<1,60", ambiguous_text)
        self.assertNotIn("Rishniw", ambiguous_text)

        payload["medidas"].update({
            "unidade_confirmada_Aorta": "cm", "unidade_confirmada_Atrio_esquerdo": "cm",
        })
        confirmed_text = _pdf_text(payload)
        self.assertIn("Aorta\n10.00 mm", confirmed_text)
        self.assertIn("Átrio esquerdo\n14.00 mm", confirmed_text)
        self.assertIn("AE/Ao (Átrio esquerdo/Aorta)\n1.40\n<1,60 (2D, eixo curto)", confirmed_text)

    def test_selected_lv_technique_controls_pdf_measurement_block(self) -> None:
        mode_m_text = _pdf_text(_base_report("modo_m"))
        mode_2d_text = _pdf_text(_base_report("2d"))

        self.assertIn("VE - Modo M", mode_m_text)
        self.assertNotIn("VE - Modo 2D", mode_m_text)
        self.assertIn("VE - Modo 2D", mode_2d_text)
        self.assertNotIn("VE - Modo M", mode_2d_text)
        self.assertIn("99.00 ml", mode_m_text)
        self.assertNotIn("96.00 ml", mode_m_text)
        self.assertIn("96.00 ml", mode_2d_text)
        self.assertNotIn("99.00 ml", mode_2d_text)
        self.assertIn("57.00 %", mode_2d_text)
        self.assertNotIn("66.00 %", mode_2d_text)
        self.assertIn("PSAP estimada", mode_2d_text)
        self.assertIn("61.84 mmHg", mode_2d_text)
        self.assertIn("0.08 m/s", mode_2d_text)
        self.assertIn("E/TRIV", mode_2d_text)
        self.assertIn("2.93", mode_2d_text)
        self.assertNotIn("sugestivo de aumento das pressões", mode_2d_text)
        self.assertIn("E/E'", mode_2d_text)
        self.assertIn("14.00", mode_2d_text)

    def test_annular_excursion_remains_in_pdf_with_2d_lv_technique(self) -> None:
        payload = _base_report("2d")
        payload["medidas"] = {
            "VE_tecnica_relatorio": "2d", "DIVEd_2D": "32",
            "TAPSE": "10", "MAPSE": "8",
        }
        text = _pdf_text(payload)

        self.assertIn("VE - Modo 2D", text)
        self.assertNotIn("VE - Modo M", text)
        self.assertIn("Excursão do plano anular", text)
        self.assertIn("TAPSE (excursão sistólica do plano anular tricúspide)\n10.00 mm", text)
        self.assertIn("MAPSE (excursão sistólica do plano anular mitral)\n8.00 mm", text)

    def test_persisted_2d_measurements_generate_2d_block(self) -> None:
        payload = _base_report("modo_m")
        payload["medidas"] = extrair_medidas_ecocardiograma_da_descricao(
            """
## Medidas Ecocardiograficas
- DIVEd_2D: 31.69
- SIVd_2D: 5.96
- PLVEd_2D: 5.06
- DIVES_2D: 15.39
- SIVs_2D: 8.65
- PLVES_2D: 8.10
- VDF_2D: 40
- VSF_2D: 6
- FE_Teicholz_2D: 85
- DeltaD_FS_2D: 51
- VE_tecnica_relatorio: 2d

## Avaliacao Qualitativa
"""
        )

        text = _pdf_text(payload)

        self.assertIn("VE - Modo 2D", text)
        self.assertNotIn("VE - Modo M", text)
        self.assertIn("31.69 mm", text)
        self.assertIn("40.00 ml", text)
        self.assertIn("85.00 %", text)


if __name__ == "__main__":
    unittest.main()
