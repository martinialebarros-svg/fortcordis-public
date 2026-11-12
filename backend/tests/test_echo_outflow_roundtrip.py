"""Outflow import/save/reopen/preview/PDF integration with isolated SQLite.

These tests use the production parser, endpoint functions and PDF renderer.
They do not exercise browser controls, HTTP authentication or a deployed DB.
All patient/report records live only in a new in-memory database per test.
"""

import os
import sys
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "outflow-roundtrip-test-secret-key-1234567890")

from app.api.v1.endpoints import laudos  # noqa: E402
from app.db.database import Base  # noqa: E402
from app.models.laudo import Laudo  # noqa: E402
from app.models.paciente import Paciente  # noqa: E402
from app.services.laudo_pdf_service import render_laudo_pdf  # noqa: E402
from app.utils.ecocardiograma_medidas import (  # noqa: E402
    extrair_medidas_ecocardiograma_da_descricao,
)
from app.utils.ecocardiograma_qualitativa import (  # noqa: E402
    extrair_qualitativa_ecocardiograma_da_descricao,
)
from app.utils.pdf_laudo import gerar_pdf_laudo_eco  # noqa: E402
from app.utils.xml_parser import parse_xml_eco as parse_xml_eco_v1  # noqa: E402
from app.utils.xml_parser_v2 import parse_xml_eco as parse_xml_eco_v2  # noqa: E402


# Deliberately different values at all four acquisition sites. In particular,
# the imported gradients need not equal 4 * the rounded displayed velocity².
SITES = (
    ("VSVE", "LVOT Vmax", "LVOT maxPG", "1.01", "4.11", "via de saída do VE"),
    ("aorta", "Aortic Vmax", "Aortic maxPG", "0.95", "3.61", "aorta"),
    ("VSVD", "RVOT Vmax", "RVOT maxPG", "0.80", "2.57", "via de saída do VD"),
    ("pulmonar", "Pulmonic Vmax", "Pulmonic maxPG", "0.7234", "2.0932", "pulmonar"),
)


def _xml(sites=SITES, *, include_gradients=True):
    parameters = []
    for _, velocity_label, gradient_label, velocity, gradient, _ in sites:
        parameters.append(
            f'<parameter NAME="{velocity_label}"><aver>{velocity}</aver><unit>m/s</unit></parameter>'
        )
        if include_gradients:
            parameters.append(
                f'<parameter NAME="{gradient_label}"><aver>{gradient}</aver><unit>mmHg</unit></parameter>'
            )
    return ("<root>" + "".join(parameters) + "</root>").encode("utf-8")


def _import(parser, xml):
    with redirect_stdout(StringIO()):
        return parser(xml)["medidas"]


def _text(pdf_bytes):
    reader = PdfReader(BytesIO(pdf_bytes))
    return " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())


class EchoOutflowRoundtripTest(unittest.TestCase):
    def setUp(self):
        self._new_database()

    def _new_database(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.session_factory()
        self.user = SimpleNamespace(id=7, nome="Veterinário de teste")
        self.patient = {
            "nome": "EXEMPLO SINTÉTICO",
            "tutor": "Tutor sintético",
            "especie": "Canina",
            "raca": "SRD",
            "sexo": "Macho",
            "peso": "10",
            "data_exame": "2026-10-15",
        }

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _fresh_database_if_used(self):
        if self.db.query(Laudo).count():
            self.db.close()
            self.engine.dispose()
            self._new_database()

    def _payload(self, measurements, qualitative=None):
        return {
            "tipo_laudo": "ecocardiograma",
            "paciente": deepcopy(self.patient),
            "medidas": deepcopy(measurements),
            "qualitativa": deepcopy(qualitative or {}),
            "conteudo": {"conclusao": "EXEMPLO SINTÉTICO - SEM VALIDADE CLÍNICA."},
            "status": "Rascunho",
        }

    def _reopen(self, report_id):
        # A new ORM session ensures assertions read committed state rather than
        # the same object retained by the save/update endpoint.
        self.db.close()
        self.db = self.session_factory()
        detail = laudos.obter_laudo(report_id, db=self.db, current_user=self.user)
        self.assertEqual(
            detail["medidas"],
            extrair_medidas_ecocardiograma_da_descricao(detail["descricao"]),
        )
        return detail

    def _save(self, measurements, qualitative=None):
        result = laudos.criar_laudo_ecocardiograma(
            self._payload(measurements, qualitative), self.db, self.user
        )
        detail = self._reopen(result["id"])
        self.patient["id"] = detail["paciente_id"]
        return detail

    def _resave(self, detail):
        qualitative = extrair_qualitativa_ecocardiograma_da_descricao(detail["descricao"])
        result = laudos.atualizar_laudo(
            detail["id"], self._payload(detail["medidas"], qualitative), self.db, self.user
        )
        self.assertEqual(result.id, detail["id"])
        reopened = self._reopen(detail["id"])
        self.assertEqual(reopened["medidas"], detail["medidas"])
        self.assertEqual(self.db.query(Laudo).count(), 1)
        self.assertEqual(self.db.query(Paciente).count(), 1)
        return reopened

    def _preview_and_saved_pdf_text(self, detail):
        measurements = deepcopy(detail["medidas"])
        qualitative = extrair_qualitativa_ecocardiograma_da_descricao(detail["descricao"])
        payload = self._payload(measurements, qualitative)
        payload["conclusao"] = payload["conteudo"]["conclusao"]
        preview_text = _text(gerar_pdf_laudo_eco(payload))
        self.assertEqual(payload["medidas"], measurements)
        pdf = render_laudo_pdf(self.db, detail["id"], self.user)
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        saved_pdf_text = _text(pdf.content)
        self.db.expire_all()
        self.assertEqual(self.db.get(Laudo, detail["id"]).descricao, detail["descricao"])
        return preview_text, saved_pdf_text

    def test_all_four_imported_sites_and_source_precision_survive_roundtrip(self):
        for parser in (parse_xml_eco_v1, parse_xml_eco_v2):
            with self.subTest(parser=parser.__module__):
                # Start a fresh database also for the second parser.
                self._fresh_database_if_used()
                measurements = _import(parser, _xml())
                detail = self._resave(self._save(measurements))
                for site, velocity_label, gradient_label, velocity, gradient, _ in SITES:
                    for prefix, label, expected in (
                        ("Vmax", velocity_label, velocity), ("Grad", gradient_label, gradient)
                    ):
                        key = f"{prefix}_{site}"
                        self.assertAlmostEqual(float(detail["medidas"][key]), float(expected))
                        self.assertEqual(detail["medidas"][f"{key}_origem"], "importado")
                        self.assertEqual(detail["medidas"][f"{key}_rotulo_origem"], label)

                for text in self._preview_and_saved_pdf_text(detail):
                    for _, _, _, velocity, gradient, location in SITES:
                        self.assertIn(f"Vmax {location} {velocity} m/s", text)
                        self.assertIn(f"Gradiente {location} {gradient} mmHg", text)
                    self.assertIn("Rótulo de origem de Vmax via de saída do VD: RVOT Vmax.", text)
                    self.assertNotIn("4.08 mmHg", text)
                    self.assertNotIn("2.56 mmHg", text)
                    self.assertNotIn("calculado", text)

    def test_each_site_imports_without_creating_a_symmetric_or_relabelled_site(self):
        for parser in (parse_xml_eco_v1, parse_xml_eco_v2):
            for site_data in SITES:
                site, _, _, _, _, location = site_data
                with self.subTest(parser=parser.__module__, site=site):
                    self._fresh_database_if_used()
                    detail = self._resave(self._save(_import(parser, _xml((site_data,)))))
                    for other_site, *_ in SITES:
                        if other_site != site:
                            self.assertNotIn(f"Vmax_{other_site}", detail["medidas"])
                            self.assertNotIn(f"Grad_{other_site}", detail["medidas"])
                    for text in self._preview_and_saved_pdf_text(detail):
                        self.assertIn(f"Vmax {location} ", text)
                        for other_site, _, _, _, _, other_location in SITES:
                            if other_site != site:
                                self.assertNotIn(f"Vmax {other_location} ", text)
                                self.assertNotIn(f"Gradiente {other_location} ", text)

    def test_missing_gradient_is_derived_only_for_its_site_in_preview_and_pdf(self):
        for site_data in SITES:
            site, _, _, velocity, _, location = site_data
            with self.subTest(site=site):
                self._fresh_database_if_used()
                measurements = _import(parse_xml_eco_v1, _xml((site_data,), include_gradients=False))
                self.assertNotIn(f"Grad_{site}", measurements)
                detail = self._resave(self._save(measurements))
                self.assertNotIn(f"Grad_{site}", detail["medidas"])
                expected_gradient = f"{4 * float(velocity) ** 2:.2f}"
                for text in self._preview_and_saved_pdf_text(detail):
                    self.assertIn(
                        f"Gradiente {location} (calculado: 4 × V²) {expected_gradient} mmHg", text
                    )
                    for other_site, _, _, _, _, other_location in SITES:
                        if other_site != site:
                            self.assertNotIn(f"Gradiente {other_location} ", text)
                self.assertNotIn(f"Grad_{site}", self._reopen(detail["id"])["medidas"])

    def test_informed_and_explicit_calculated_provenance_survive_save_and_edit(self):
        measurements = {
            "Vmax_VSVE": "1.01", "Vmax_VSVE_origem": "informado",
            "Grad_VSVE": "4.08", "Grad_VSVE_origem": "calculado",
            "Vmax_VSVD": "0.80", "Vmax_VSVD_origem": "informado",
            "Grad_VSVD": "2.57", "Grad_VSVD_origem": "informado",
        }
        detail = self._resave(self._save(measurements))
        self.assertEqual(detail["medidas"], measurements)
        for text in self._preview_and_saved_pdf_text(detail):
            self.assertIn("Gradiente via de saída do VE (calculado: 4 × V²) 4.08 mmHg", text)
            self.assertIn("Gradiente via de saída do VD 2.57 mmHg", text)
            self.assertNotIn("Gradiente via de saída do VD (calculado", text)

    def test_legacy_pulmonary_values_keep_their_keys_and_unconfirmed_origin(self):
        legacy = {"Vmax_pulmonar": "0.80", "Grad_pulmonar": "2.57"}
        detail = self._resave(self._save(legacy))
        self.assertEqual(detail["medidas"], legacy)
        for text in self._preview_and_saved_pdf_text(detail):
            self.assertIn("Vmax pulmonar 0.80 m/s", text)
            self.assertIn("Gradiente pulmonar 2.57 mmHg", text)
            self.assertIn("Origem não confirmada", text)
            self.assertNotIn("via de saída do VD", text)
            self.assertNotIn("calculado", text)
        self.assertEqual(self._reopen(detail["id"])["medidas"], legacy)

    def test_saved_qualitative_headings_preserve_the_recorded_acquisition_sites(self):
        qualitative = {
            "vasos": "- VSVE: Registro da via esquerda.\n"
                     "- Fluxo aórtico: Registro aórtico.\n"
                     "- VSVD: Registro da via direita.\n"
                     "- Fluxo pulmonar: Registro pulmonar.",
        }
        detail = self._resave(self._save(_import(parse_xml_eco_v1, _xml()), qualitative))
        self.assertEqual(
            extrair_qualitativa_ecocardiograma_da_descricao(detail["descricao"]), qualitative
        )
        for text in self._preview_and_saved_pdf_text(detail):
            for title_and_body in (
                "VSVE Registro da via esquerda.", "Fluxo aórtico Registro aórtico.",
                "VSVD Registro da via direita.", "Fluxo pulmonar Registro pulmonar.",
            ):
                self.assertIn(title_and_body, text)


if __name__ == "__main__":
    unittest.main()
