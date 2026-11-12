"""Independent low-weight resolver-to-PDF contract, with synthetic patients only."""
import os
import re
import sys
import unittest
from copy import deepcopy
from datetime import date, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "synthetic-low-weight-pdf-test-secret-1234567890")

from pypdf import PdfReader
from app.services.echo_reference_resolver import load_echo_reference, resolve_echo_reference
from app.utils.pdf_laudo import (
    aplicar_referencia_eco, criar_secao_referencias_eco, formatar_referencia, gerar_pdf_laudo_eco,
    recalcular_dived_normalizado_para_pdf, referencias_2d_caninas_publicadas,
)

KEYS = {"DIVEd": "lvid_d", "DIVES": "lvid_s", "SIVd": "ivs_d", "SIVs": "ivs_s",
        "PLVEd": "lvpw_d", "PLVES": "lvpw_s"}
MEASUREMENTS = {"VE_tecnica_relatorio": "modo_m", "DIVEd": "20", "DIVES": "12",
                "SIVd": "5", "SIVs": "8", "PLVEd": "5", "PLVES": "8"}


def report(species="Canina", weight=2.5, age="2 anos", reference=None):
    return {"paciente": {"nome": "QA SINTETICO BAIXO PESO", "tutor": "QA TUTOR",
                         "especie": species, "peso": str(weight), "idade": age,
                         "data_exame": "2026-10-27", "raca": "SRD", "sexo": "Macho"},
            "medidas": dict(MEASUREMENTS), "referencia_eco": reference,
            "conclusao": "TESTE SINTETICO. Sem finalidade clinica.",
            "qualitativa": {"funcao": "Texto oficial sintetico preservado."},
            "clinica": "Clinica sintetica"}


def reference(species="Canina", weight=2.5, age="2 anos"):
    return resolve_echo_reference({"especie": species, "peso_kg": weight}, peso_kg=weight,
                                  medidas=MEASUREMENTS, idade=age)


def pdf(payload):
    before = deepcopy(payload)
    data = gerar_pdf_laudo_eco(payload)
    assert payload == before
    reader = PdfReader(BytesIO(data))
    text = re.sub(r"\s+", " ", "\n".join(page.extract_text() or "" for page in reader.pages))
    return reader, text


class PdfLaudoLowWeightTest(unittest.TestCase):
    def test_historical_age_matches_exam_for_all_report_types_and_pdf_paths(self):
        from app.models.laudo import Laudo
        from app.models.paciente import Paciente
        from app.services.laudo_pdf_service import render_laudo_pdf
        from app.api.v1.endpoints.laudos import gerar_pdf_laudo, obter_laudo, _parse_data_exame

        for entrypoint in ("service", "endpoint", "saved_report"):
            for species in ("Canina", "Felina"):
                for exam_date, report_date, birth, observations, expected, expected_date in (
                    (date(2018, 8, 15), date(2020, 1, 15), "2018-01-15", "", "7m", "15/08/2018"),
                    (date(2020, 1, 15), None, "2018-01-15", "", "2a", "15/01/2020"),
                    (None, date(2018, 8, 15), "2018-01-15", "", "7m", "15/08/2018"),
                    (date(2018, 8, 15), None, None, "Idade: 7 meses", "7 meses", "15/08/2018"),
                    (_parse_data_exame("2019-01-14T23:30:00-03:00").astimezone(timezone.utc), None,
                     "2018-01-15", "", "11m", "14/01/2019"),
                    (None, _parse_data_exame("2019-01-14T23:30:00-03:00").astimezone(timezone.utc),
                     "2018-01-15", "", "11m", "14/01/2019"),
                    (_parse_data_exame("2019-01-14").astimezone(timezone.utc), None,
                     "2018-01-15", "", "11m", "14/01/2019"),
                    (_parse_data_exame("2020-01-15T23:30:00-03:00").astimezone(timezone.utc), None,
                     "2018-01-15", "", "2a", "15/01/2020"),
                    (_parse_data_exame("2019-01-15T00:00:00Z"), None,
                     "2018-01-15", "", "1a", "15/01/2019"),
                    (None, _parse_data_exame("2019-01-15T00:00:00Z"),
                     "2018-01-15", "", "11m", "14/01/2019"),
                ):
                    with self.subTest(entrypoint=entrypoint, species=species, expected=expected, fallback=exam_date is None):
                        patient = SimpleNamespace(id=8, nome="QA IDADE HISTORICA", especie=species,
                                                  peso_kg=2.25, tutor_id=None, nascimento=birth,
                                                  observacoes=observations, raca="SRD", sexo="Macho")
                        description = "## Medidas Ecocardiograficas\n" + "\n".join(
                            f"- {key}: {value}" for key, value in MEASUREMENTS.items())
                        laudo = SimpleNamespace(id=91, paciente_id=8, clinic_id=None,
                            medico_solicitante="Clinica sintetica", data_exame=exam_date,
                            data_laudo=report_date, descricao=description, diagnostico="Teste sintetico.",
                            observacoes="", anexos=None, tipo="ecocardiograma", titulo="QA sintetico",
                            status="Rascunho", created_at=None, updated_at=None,
                            veterinario_parceiro_id=None, whatsapp_envios=None)
                        before = deepcopy((vars(patient), vars(laudo)))
                        rows = {Laudo: laudo, Paciente: patient}
                        database = MagicMock()
                        def query_for(model):
                            query = MagicMock()
                            query.filter.return_value = query
                            query.order_by.return_value = query
                            query.first.return_value = rows.get(model)
                            query.all.return_value = []
                            return query
                        database.query.side_effect = query_for
                        with patch("app.services.laudo_pdf_service.compute_laudo_pdf_cache_key", return_value="synthetic-cache-key"), \
                             patch("app.api.v1.endpoints.laudos.load_echo_editor_source", return_value=SimpleNamespace(
                                 laudo=laudo, paciente=patient, tutor=None, imagens=[], revision="echo-v1:" + "0" * 64)), \
                             patch("app.api.v1.endpoints.laudos.compute_laudo_pdf_cache_key", return_value="synthetic-cache-key"), \
                             patch("app.api.v1.endpoints.laudos.get_cached_laudo_pdf_job", return_value=None), \
                             patch("app.api.v1.endpoints.laudos._serialize_portal_release_state", return_value={}), \
                             patch("app.utils.pdf_laudo.gerar_pdf_laudo_eco", return_value=b"synthetic-renderer-capture") as renderer:
                            user = SimpleNamespace(id=1, nome="QA VETERINARIO")
                            if entrypoint == "saved_report":
                                saved = obter_laudo(91, db=database, current_user=user)
                                self.assertEqual(saved["paciente"]["idade"], expected)
                                renderer.assert_not_called()
                            else:
                                if entrypoint == "endpoint":
                                    generated = gerar_pdf_laudo(91, db=database, current_user=user)
                                    self.assertIn(expected_date[6:] + "-" + expected_date[3:5] + "-" + expected_date[:2], generated.headers["content-disposition"])
                                else:
                                    generated = render_laudo_pdf(database, 91, user)
                                    self.assertTrue(generated.filename.startswith(expected_date[6:] + "-" + expected_date[3:5] + "-" + expected_date[:2]))
                                payload = renderer.call_args.args[0]
                                self.assertEqual(payload["paciente"]["idade"], expected)
                                self.assertEqual(payload["paciente"]["data_exame"], expected_date)
                                for prefix in KEYS.values():
                                    status = payload["referencia_eco"]["range_metadata"][prefix]["status"]
                                    self.assertEqual(status, "published" if expected in {"1a", "2a"} else "unavailable")
                            laudo.tipo = "pressao_arterial"
                            if entrypoint == "saved_report":
                                saved_other = obter_laudo(91, db=database, current_user=user)
                                self.assertEqual(saved_other["paciente"]["idade"], expected)
                            else:
                                with patch("app.utils.pdf_laudo.gerar_pdf_laudo_pressao", return_value=b"synthetic-other-modality") as other_renderer:
                                    render_laudo_pdf(database, 91, user)
                                    self.assertEqual(other_renderer.call_args.args[0]["paciente"]["idade"], expected)
                            laudo.tipo = "ecocardiograma"
                        if entrypoint != "saved_report":
                            _, text = pdf(payload)
                            doi = "10.3389/fvets.2022.918457" if species == "Canina" else "10.1111/jvim.14569"
                            self.assertEqual(doi in text, expected in {"1a", "2a"})
                        self.assertEqual((vars(patient), vars(laudo)), before)
                        database.add.assert_not_called()
                        database.commit.assert_not_called()

    def test_real_pdf_loader_keeps_the_same_precise_weight_for_reference_and_renderer(self):
        from app.models.laudo import Laudo
        from app.models.paciente import Paciente
        from app.models.configuracao import Configuracao, ConfiguracaoUsuario
        from app.services.laudo_pdf_service import render_laudo_pdf
        from app.api.v1.endpoints.laudos import gerar_pdf_laudo

        cases = [(entrypoint, species, weight) for entrypoint in ("service", "endpoint")
                 for species, weight in (("Felina", 2.25), ("Canina", 2.65))]
        for entrypoint, species, weight in cases:
            with self.subTest(entrypoint=entrypoint, species=species, weight=weight):
                patient = SimpleNamespace(id=8, nome="QA PESO PRECISO", especie=species,
                                          peso_kg=weight, tutor_id=None, nascimento=None,
                                          observacoes="", raca="SRD", sexo="Macho")
                description = "## Medidas Ecocardiograficas\n" + "\n".join(
                    f"- {key}: {value}" for key, value in MEASUREMENTS.items()) + "\n\n## Avaliacao Qualitativa\n"
                laudo = SimpleNamespace(id=91, paciente_id=8, clinic_id=None,
                                        medico_solicitante="Clinica sintetica", data_exame=date(2026, 10, 27),
                                        data_laudo=None, descricao=description, diagnostico="Teste sintetico.",
                                        observacoes="", anexos=None, tipo="ecocardiograma")
                rows = {Laudo: laudo, Paciente: patient, Configuracao: None, ConfiguracaoUsuario: None}
                database = MagicMock()
                def query_for(model):
                    query = MagicMock()
                    query.filter.return_value = query
                    query.first.return_value = rows.get(model)
                    query.all.return_value = []
                    return query
                database.query.side_effect = query_for
                with patch("app.services.laudo_pdf_service.compute_laudo_pdf_cache_key", return_value="synthetic-cache-key"), \
                     patch("app.api.v1.endpoints.laudos.compute_laudo_pdf_cache_key", return_value="synthetic-cache-key"), \
                     patch("app.api.v1.endpoints.laudos.get_cached_laudo_pdf_job", return_value=None), \
                     patch("app.services.laudo_pdf_service._listar_imagens_incluidas_no_pdf", return_value=[]), \
                     patch("app.services.laudo_pdf_service.idade_do_paciente", return_value="2 anos"), \
                     patch("app.api.v1.endpoints.laudos._extrair_ecocardiograma_cabecalho_de_anexos", return_value={}), \
                     patch("app.api.v1.endpoints.laudos._extrair_pressao_arterial_de_anexos", return_value=None), \
                     patch("app.services.echo_reference_resolver.load_echo_reference", wraps=load_echo_reference) as loader, \
                     patch("app.utils.pdf_laudo.gerar_pdf_laudo_eco", return_value=b"synthetic-renderer-capture") as renderer:
                    user = SimpleNamespace(id=1, nome="QA VETERINARIO")
                    if entrypoint == "endpoint":
                        response = gerar_pdf_laudo(91, db=database, current_user=user)
                        self.assertEqual(response.media_type, "application/pdf")
                    else:
                        generated = render_laudo_pdf(database, 91, user)
                        self.assertEqual(generated.content, b"synthetic-renderer-capture")
                payload = renderer.call_args.args[0]
                self.assertEqual(loader.call_args.kwargs["weight_kg"], weight)
                self.assertEqual(float(payload["paciente"]["peso"]), weight)
                selected = payload["referencia_eco"]
                self.assertEqual(selected["patient_weight_kg"], weight)
                rendered = resolve_echo_reference(selected, peso_kg=float(payload["paciente"]["peso"]),
                                                   medidas=payload["medidas"], idade=payload["paciente"]["idade"])
                expected = reference(species, weight)
                for prefix in KEYS.values():
                    self.assertEqual(rendered[f"{prefix}_min"], expected[f"{prefix}_min"])
                    self.assertEqual(rendered[f"{prefix}_max"], expected[f"{prefix}_max"])
                database.add.assert_not_called()
                database.commit.assert_not_called()

    def test_no_catalog_loader_supplies_six_source_bound_dimensions_without_database_writes(self):
        database = MagicMock()
        query = database.query.return_value
        query.filter.return_value = query
        query.all.return_value = []
        for species, doi in (("Canina", "10.3389/fvets.2022.918457"), ("Gato", "10.1111/jvim.14569")):
            with self.subTest(species=species):
                resolved = load_echo_reference(database, species=species, weight_kg=2,
                                               medidas=MEASUREMENTS, idade="2 anos")
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved["reference_origin"], "computed")
                for prefix in KEYS.values():
                    self.assertEqual(resolved["range_metadata"][prefix]["doi"], doi)
                    self.assertGreater(resolved[f"{prefix}_min"], 0)
                    self.assertGreater(resolved[f"{prefix}_max"], resolved[f"{prefix}_min"])
                for prefix in ("ao", "la", "la_ao", "tapse", "mapse", "fs", "ef", "vmax_ao", "vmax_pulm"):
                    self.assertIsNone(resolved[f"{prefix}_min"])
                    self.assertIsNone(resolved[f"{prefix}_max"])
                database.add.assert_not_called()
                database.commit.assert_not_called()

    def test_estimates_have_text_but_never_numerical_comparison_bounds(self):
        parameters = [{"chave": key, "unidade": "mm"} for key in KEYS]
        for species, weight, age, context in (("Canina", 1, "2 anos", "weight_extrapolation"),
                                             ("Felina", 1, "2 anos", "weight_extrapolation"),
                                             ("Canina", 2.5, None, "age_unconfirmed")):
            with self.subTest(species=species, weight=weight, age=age):
                resolved = reference(species, weight, age)
                for key, parameter in zip(KEYS, aplicar_referencia_eco(parameters, resolved)):
                    meta = resolved["range_metadata"][KEYS[key]]
                    self.assertEqual(meta["status"], "estimated")
                    self.assertEqual(meta["estimate_context"], context)
                    self.assertIsNone(parameter["ref_min"])
                    self.assertIsNone(parameter["ref_max"])
                    self.assertTrue(parameter["ref_text"].startswith("Est." if weight < 1.5 else "Adultos"))

    def test_juvenile_has_neither_comparison_bounds_nor_adult_estimates(self):
        for species in ("Canina", "Felina"):
            resolved = reference(species, 2, "7m")
            for prefix in KEYS.values():
                meta = resolved["range_metadata"][prefix]
                self.assertEqual(meta["status"], "unavailable")
                self.assertIsNone(resolved[f"{prefix}_min"])
                self.assertIsNone(resolved[f"{prefix}_max"])
                self.assertNotIn("estimate_min", meta)
                self.assertNotIn("estimate_max", meta)

    def test_canine_bibliography_attributes_the_computed_m_ranges_to_isayama(self):
        payload = report(reference=reference())
        text = " ".join(item.getPlainText() for item in criar_secao_referencias_eco(payload)
                        if hasattr(item, "getPlainText"))
        self.assertIn("Isayama et al. (2022)", text)
        self.assertIn("10.3389/fvets.2022.918457", text)
        self.assertIn("Tabela 2", text)
        self.assertIn("limites alométricos aproximados", text.lower())
        # Cornell may still document its separately labelled normalized index;
        # it must not be presented as the source of these six calculated limits.
        self.assertNotRegex(text, r"Tabela 2 de Cornell|limites alométricos aproximados[^.]*Cornell")

    def test_actual_renderer_without_catalog_prints_the_correct_six_intervals_and_sources(self):
        for species, weight, source in (("Canina", 2.5, "Isayama"), ("Felina", 2.25, "Häggström")):
            with self.subTest(species=species):
                payload = report(species, weight)
                reader, text = pdf(payload)
                expected = reference(species, weight)
                self.assertGreaterEqual(len(reader.pages), 1)
                for prefix in KEYS.values():
                    self.assertIn(formatar_referencia(expected[f"{prefix}_min"], expected[f"{prefix}_max"], "mm"), text)
                self.assertIn(source, text)
                self.assertIn("Texto oficial sintetico preservado.", text)
                if species == "Canina":
                    self.assertIn("10.3389/fvets.2022.918457", text)
                else:
                    self.assertIn("interpolação", text)
                    self.assertNotIn("Isayama", text)

    def test_actual_estimated_pdf_labels_extrapolation_and_never_recasts_it_as_an_interval(self):
        for species in ("Canina", "Felina"):
            _, text = pdf(report(species, 1))
            resolved = reference(species, 1)
            self.assertIn("Est.:", text)
            self.assertIn("estimativa por extrapolação abaixo de 1,5 kg", text)
            self.assertIn("não constitui intervalo individual validado", text)
            self.assertIn("não permite classificação automática", text)
            for prefix in KEYS.values():
                meta = resolved["range_metadata"][prefix]
                self.assertNotIn(formatar_referencia(meta["estimate_min"], meta["estimate_max"], "mm"), text)

    def test_actual_unknown_age_pdf_is_neutral_and_known_juvenile_retracts_an_adult_carrier(self):
        _, unknown = pdf(report(age=None))
        self.assertIn("Adultos:", unknown)
        self.assertIn("confirmar idade/maturidade", unknown)
        carrier = reference(weight=2, age="2 anos")
        _, juvenile = pdf(report(weight=2, age="7m", reference=carrier))
        self.assertIn("adultos não aplicada a paciente em crescimento", juvenile)
        self.assertNotIn("Dimensões em modo M: limites alométricos aproximados calculados", juvenile)
        self.assertNotIn("Isayama", juvenile)
        self.assertNotIn("Est.:", juvenile)
        self.assertNotIn("Adultos:", juvenile)
        for prefix in KEYS.values():
            self.assertNotIn(formatar_referencia(carrier[f"{prefix}_min"], carrier[f"{prefix}_max"], "mm"), juvenile)

    def test_unknown_age_extrapolated_pdf_preserves_both_independent_limitations(self):
        for species in ("Canina", "Felina"):
            for weight in (1, 1.49, 1.5):
                with self.subTest(species=species, weight=weight):
                    payload = report(species, weight, age=None)
                    _, text = pdf(payload)
                    self.assertIn("confirmar idade/maturidade", text)
                    self.assertEqual("estimativa por extrapolação abaixo de 1,5 kg" in text, weight < 1.5)
                    if weight < 1.5:
                        self.assertIn("não constitui intervalo individual validado", text)
                        self.assertIn("não permite classificação automática", text)

    def test_unknown_age_note_requires_an_actually_displayed_estimated_m_model(self):
        for species in ("Canina", "Felina"):
            for weight in (1, 1.49, 1.5):
                for age in ("2 anos", "7m"):
                    with self.subTest(species=species, weight=weight, age=age):
                        _, text = pdf(report(species, weight, age))
                        self.assertNotIn("confirmar idade/maturidade", text)
                        self.assertEqual("estimativa por extrapolação abaixo de 1,5 kg" in text,
                                         weight < 1.5 and age == "2 anos")
                with self.subTest(species=species, weight=weight, technique="2d"):
                    payload = report(species, weight, age=None)
                    payload["medidas"] = {"VE_tecnica_relatorio": "2d", "DIVEd_2D": "22"}
                    self.assertNotIn("confirmar idade/maturidade", pdf(payload)[1])
            for key, prefix in KEYS.items():
                with self.subTest(species=species, custom_key=key):
                    custom = {"especie": species, "peso_kg": 2.5,
                              f"{prefix}_min": 1, f"{prefix}_max": 99}
                    original = deepcopy(custom)
                    payload = report(species, 2.5, age=None, reference=custom)
                    payload["medidas"] = {"VE_tecnica_relatorio": "modo_m", key: MEASUREMENTS[key]}
                    if species == "Felina":
                        payload["medidas"]["TAPSE"] = "9"
                    _, text = pdf(payload)
                    self.assertIn("1.00 - 99.00 mm", text)
                    self.assertNotIn("confirmar idade/maturidade", text)
                    self.assertEqual(custom, original)

    def test_feline_juvenile_computed_carrier_does_not_cite_unused_adult_m_source(self):
        for species in ("Felina", "Cat"):
            for weight in (1, 2.25, 2.99):
                for stale_carrier in (False, True):
                    with self.subTest(species=species, weight=weight, stale_carrier=stale_carrier):
                        carrier = reference(species, weight) if stale_carrier else None
                        _, text = pdf(report(species, weight, "7m", carrier))
                        self.assertNotIn("Häggström", text)
                        self.assertNotIn("10.1111/jvim.14569", text)
                        self.assertNotIn("interpolação entre os pesos", text)
                        self.assertNotIn("Est.:", text)
                        self.assertNotIn("Adultos:", text)
                        self.assertIn("20.00 mm", text)
                        self.assertIn("Texto oficial sintetico preservado.", text)

    def test_feline_computed_source_remains_for_applied_bounds_and_neutral_estimates(self):
        for weight, age, marker in ((2.25, "2 anos", "interpolação"),
                                    (2.25, None, "Adultos:"),
                                    (1, "2 anos", "Est.:"), (1, None, "Est.:")):
            with self.subTest(weight=weight, age=age):
                _, text = pdf(report("Felina", weight, age))
                self.assertIn("Häggström et al. (2016)", text)
                self.assertIn("10.1111/jvim.14569", text)
                self.assertIn(marker, text)

    def test_feline_computed_m_source_requires_an_actually_displayed_reference(self):
        for value in ("", "0", "nan"):
            with self.subTest(value=value):
                payload = report("Felina", 2.25)
                payload["medidas"] = {"VE_tecnica_relatorio": "modo_m", "DIVEd": value}
                _, text = pdf(payload)
                self.assertNotIn("Häggström", text)
                self.assertNotIn("10.1111/jvim.14569", text)
        ambiguous = report("Felina", 2.25)
        ambiguous["medidas"] = {"VE_tecnica_relatorio": "modo_m", "DIVEd": "1.2",
                                  "DIVES": "0.7", "SIVd": "0.4"}
        _, text = pdf(ambiguous)
        self.assertIn("unidade a confirmar", text.lower())
        self.assertNotIn("Häggström", text)

    def test_feline_juvenile_m_source_does_not_remove_other_marker_bibliography(self):
        payload = report("Felina", 2.25, "7m")
        payload["medidas"].update({"TAPSE": "9", "MAPSE": "6", "AE_diametro_max": "14",
                                    "AE_diametro_min": "10", "Fluxo_auricular": "0.2",
                                    "Vmax_aorta": "0.9", "Vmax_pulmonar": "0.8"})
        _, text = pdf(payload)
        self.assertNotIn("Häggström", text)
        for source in ("Spalla et al. (2017)", "Fuentes et al. (2020)", "Schober et al. (2006)",
                       "Kochie et al. (2021)", "Domanjko Petric et al. (2012)"):
            self.assertIn(source, text)

    def test_feline_legacy_catalog_and_published_fs_ae_ao_sources_remain_independent(self):
        legacy = report("Felina", 4)
        legacy["referencia_eco"] = {"especie": "Felina", "peso_kg": 4}
        self.assertIn("Häggström", pdf(legacy)[1])
        for key, value, fields in (
            ("DeltaD_FS", "45", {"fs_min": 28, "fs_max": 62}),
            ("AE_Ao", "1.2", {"la_ao_min": .88, "la_ao_max": 1.43}),
        ):
            with self.subTest(key=key):
                payload = report("Felina", 4)
                payload["medidas"] = {key: value, "VE_tecnica_relatorio": "modo_m",
                                        "AE_Ao_metodo": "2d_eixo_curto_diastole_inicial"}
                payload["referencia_eco"] = {"especie": "Felina", "peso_kg": 4, **fields}
                self.assertIn("Häggström", pdf(payload)[1])

    def test_known_centimeter_provenance_matches_mm_pdf_and_ambiguous_lengths_have_no_range(self):
        mm = report()
        cm = deepcopy(mm)
        for key in KEYS:
            cm["medidas"][key] = str(float(cm["medidas"][key]) / 10)
            cm["medidas"][f"unidade_confirmada_{key}"] = "cm"
        self.assertEqual(pdf(mm)[1], pdf(cm)[1])
        ambiguous = report()
        for key in KEYS:
            ambiguous["medidas"][key] = str(float(ambiguous["medidas"][key]) / 10)
        _, text = pdf(ambiguous)
        self.assertIn("unidade a confirmar", text.lower())
        resolved = reference()
        for prefix in ("lvid_d", "ivs_d", "lvpw_d"):
            self.assertNotIn(formatar_referencia(resolved[f"{prefix}_min"], resolved[f"{prefix}_max"], "mm"), text)

    def test_weight_change_recomputes_a_stale_carrier_and_preserves_its_raw_history(self):
        carrier = reference(weight=2)
        before = deepcopy(carrier)
        payload = report(weight=2.5, reference=carrier)
        _, text = pdf(payload)
        current = reference(weight=2.5)
        self.assertIn(formatar_referencia(current["lvid_d_min"], current["lvid_d_max"], "mm"), text)
        self.assertNotIn(formatar_referencia(carrier["lvid_d_min"], carrier["lvid_d_max"], "mm"), text)
        self.assertEqual(carrier, before)
        self.assertEqual(resolve_echo_reference(current), current)

    def test_custom_ranges_survive_without_becoming_isayama_or_rewritten_catalog(self):
        custom = {"especie": "Canina", "peso_kg": 2.5,
                  **{f"{prefix}_{end}": value for prefix in KEYS.values() for end, value in (("min", 1), ("max", 99))}}
        original = deepcopy(custom)
        _, text = pdf(report(reference=custom))
        self.assertIn("1.00 - 99.00 mm", text)
        self.assertNotIn("Isayama", text)
        self.assertEqual(custom, original)

    def test_model_sources_do_not_attribute_unmeasured_models_to_the_only_custom_dimension(self):
        for species, weight, source, doi in (("Canina", 2.5, "Isayama", "10.3389/fvets.2022.918457"),
                                             ("Felina", 2.25, "Häggström", "10.1111/jvim.14569")):
            for key, prefix in KEYS.items():
                for age in ("2 anos", None):
                    with self.subTest(species=species, key=key, age=age):
                        custom = {"especie": species, "peso_kg": weight,
                                  f"{prefix}_min": 1, f"{prefix}_max": 99}
                        original = deepcopy(custom)
                        payload = report(species, weight, age, custom)
                        payload["medidas"] = {"VE_tecnica_relatorio": "modo_m", key: MEASUREMENTS[key]}
                        if species == "Felina":
                            # Keep another bibliography source present so an
                            # unused model cannot leak back through footnotes.
                            payload["medidas"]["TAPSE"] = "9"
                        _, text = pdf(payload)
                        self.assertIn("1.00 - 99.00 mm", text)
                        self.assertNotIn(source, text)
                        self.assertNotIn(doi, text)
                        self.assertNotIn("Adultos:", text)
                        if species == "Felina":
                            self.assertIn("Spalla et al. (2017)", text)
                        self.assertEqual(custom, original)

    def test_model_source_remains_when_another_measured_dimension_uses_its_model(self):
        keys = list(KEYS)
        for species, weight, doi in (("Canina", 2.5, "10.3389/fvets.2022.918457"),
                                     ("Felina", 2.25, "10.1111/jvim.14569")):
            for index, (key, prefix) in enumerate(KEYS.items()):
                with self.subTest(species=species, key=key):
                    model_key = keys[(index + 1) % len(keys)]
                    custom = {"especie": species, "peso_kg": weight,
                              f"{prefix}_min": 1, f"{prefix}_max": 99}
                    payload = report(species, weight, reference=custom)
                    payload["medidas"] = {"VE_tecnica_relatorio": "modo_m", key: MEASUREMENTS[key],
                                            model_key: MEASUREMENTS[model_key]}
                    _, text = pdf(payload)
                    expected = reference(species, weight)
                    self.assertIn("1.00 - 99.00 mm", text)
                    self.assertIn(formatar_referencia(expected[KEYS[model_key] + "_min"],
                                                     expected[KEYS[model_key] + "_max"], "mm"), text)
                    self.assertIn(doi, text)
                    self.assertIn("Tabela 2 de Isayama" if species == "Canina" else "interpolação entre os pesos", text)

    def test_canine_source_requires_a_finite_unambiguous_applicable_measured_model(self):
        for value in ("", "0", "nan"):
            with self.subTest(value=value):
                payload = report()
                payload["medidas"] = {"VE_tecnica_relatorio": "modo_m", "DIVEd": value}
                self.assertNotIn("Isayama", pdf(payload)[1])
        ambiguous = report()
        ambiguous["medidas"] = {"VE_tecnica_relatorio": "modo_m", "DIVEd": "1.2",
                                  "DIVES": "0.7", "SIVd": "0.4"}
        _, text = pdf(ambiguous)
        self.assertIn("unidade a confirmar", text.lower())
        self.assertNotIn("Isayama", text)
        for weight, age, marker in ((2.5, None, "Adultos:"), (1, "2 anos", "Est.:")):
            with self.subTest(weight=weight, age=age):
                _, text = pdf(report(weight=weight, age=age))
                self.assertIn(marker, text)
                self.assertIn("10.3389/fvets.2022.918457", text)
        self.assertNotIn("Isayama", pdf(report(age="7m"))[1])
        two_d = report()
        two_d["medidas"].update({"VE_tecnica_relatorio": "2d", "DIVEd_2D": "22"})
        self.assertNotIn("Isayama", pdf(two_d)[1])

    def test_2d_does_not_receive_the_m_fallback_or_extend_visser_below_its_domain(self):
        for weight in (2.7, 2.5):
            payload = report(weight=weight)
            payload["medidas"] = {"VE_tecnica_relatorio": "2d", "VE_vista_2D": "eixo_curto", "DIVEd_2D": "22"}
            _, text = pdf(payload)
            self.assertNotIn("Isayama", text)
            if weight >= 2.6:
                self.assertIn("Visser et al. (2019)", text)
            else:
                self.assertNotIn("Visser et al. (2019)", text)

    def test_2d_adult_reference_never_applies_to_a_known_juvenile_even_with_confirmed_view(self):
        for weight in (2.59, 2.6, 2.7, 2.99, 3):
            for view in ("eixo_curto", "eixo_longo"):
                for age in ("7m", "2 anos", None):
                    with self.subTest(weight=weight, view=view, age=age):
                        payload = report(weight=weight, age=age, reference=reference(weight=weight))
                        payload["medidas"] = {
                            "VE_tecnica_relatorio": "2d", "VE_vista_2D": view,
                            "DIVEd_2D": "22", "DIVES_2D": "12", "DeltaD_FS_2D": "45.45",
                            "DIVEd_normalizado_2D": "9.99",
                        }
                        original = deepcopy(payload)
                        ranges = referencias_2d_caninas_publicadas(payload)
                        eligible = weight >= 2.6 and age != "7m"
                        self.assertEqual(bool(ranges), eligible)
                        self.assertEqual(payload, original)
                        recalculated = deepcopy(payload)
                        recalcular_dived_normalizado_para_pdf(recalculated)
                        self.assertEqual("DIVEd_normalizado_2D" in recalculated["medidas"], eligible)
                        if not eligible:
                            self.assertEqual(ranges, {})

        unconfirmed = report(weight=2.7, age="2 anos", reference=reference(weight=2.7))
        unconfirmed["medidas"] = {"VE_tecnica_relatorio": "2d", "DIVEd_2D": "22"}
        self.assertEqual(referencias_2d_caninas_publicadas(unconfirmed), {})

    def test_actual_2d_pdf_rejects_juvenile_adult_intervals_and_index_without_changing_raw_values(self):
        for weight in (2.59, 2.6, 2.7, 2.99, 3):
            for view in ("eixo_curto", "eixo_longo"):
                for age in ("7m", "2 anos", None):
                    with self.subTest(weight=weight, view=view, age=age):
                        # Below 3 kg, exercise the new no-catalog renderer
                        # carrier. At 3 kg retain the existing catalog contract.
                        carrier = reference(weight=weight) if weight == 3 else None
                        payload = report(weight=weight, age=age, reference=carrier)
                        payload["medidas"] = {
                            "VE_tecnica_relatorio": "2d", "VE_vista_2D": view,
                            "DIVEd_2D": "22", "DIVES_2D": "12", "DeltaD_FS_2D": "45.45",
                            "DIVEd_normalizado_2D": "9.99",
                        }
                        _, text = pdf(payload)
                        eligible = weight >= 2.6 and age != "7m"
                        self.assertEqual("Visser et al. (2019)" in text, eligible)
                        self.assertEqual("DIVEd normalizado 2D" in text, eligible)
                        self.assertIn("22.00 mm", text)
                        self.assertIn("12.00 mm", text)
                        self.assertIn("45.45 %", text)
                        self.assertIn("Texto oficial sintetico preservado.", text)
                        self.assertNotIn("Isayama", text)

    def test_unknown_species_cannot_receive_feline_or_toy_dog_limits(self):
        _, text = pdf(report("Equina", 2))
        self.assertNotIn("Isayama", text)
        self.assertNotIn("Häggström", text)
        self.assertNotIn("Est.:", text)


if __name__ == "__main__":
    unittest.main()
