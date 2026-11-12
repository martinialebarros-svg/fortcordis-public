import json
import os
import sys
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.utils.pdf_laudo import (  # noqa: E402
    SAIDAS_DOPPLER,
    derivar_gradientes_saidas_para_pdf,
    gerar_pdf_laudo_eco,
)


def _payload(measurements):
    return {
        "paciente": {"nome": "EXEMPLO SINTÉTICO", "especie": "Canina", "peso": "10"},
        "medidas": measurements,
        "qualitativa": {},
        "conclusao": "EXEMPLO SINTÉTICO - SEM VALIDADE CLÍNICA.",
    }


def _text(payload):
    reader = PdfReader(BytesIO(gerar_pdf_laudo_eco(payload)))
    return " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())


class PdfLaudoOutflowProvenanceTest(unittest.TestCase):
    def test_imported_gradient_and_precision_survive_saved_payload_pdf(self):
        measurements = {
            "Vmax_VSVE": "1.01", "Grad_VSVE": "4.11",
            "Vmax_VSVE_origem": "importado", "Grad_VSVE_origem": "importado",
            "Vmax_VSVE_rotulo_origem": "LVOT Vmax",
            "Grad_VSVE_rotulo_origem": "LVOT Max PG",
            "Vmax_VSVD": "0.80", "Grad_VSVD": "2.57",
            "Vmax_VSVD_origem": "importado", "Grad_VSVD_origem": "importado",
            "Vmax_pulmonar": "0.7234", "Grad_pulmonar": "2.0932",
            "Vmax_pulmonar_origem": "importado", "Grad_pulmonar_origem": "importado",
            "Vmax_aorta": "0.95", "Grad_aorta": "3.61",
            "Vmax_aorta_origem": "informado", "Grad_aorta_origem": "informado",
        }
        payload = json.loads(json.dumps(_payload(measurements)))
        original = deepcopy(payload)
        text = _text(payload)

        for label, value in (
            ("Vmax via de saída do VE", "1.01 m/s"),
            ("Gradiente via de saída do VE", "4.11 mmHg"),
            ("Vmax via de saída do VD", "0.80 m/s"),
            ("Gradiente via de saída do VD", "2.57 mmHg"),
            ("Vmax aorta", "0.95 m/s"), ("Gradiente aorta", "3.61 mmHg"),
            ("Vmax pulmonar", "0.7234 m/s"), ("Gradiente pulmonar", "2.0932 mmHg"),
        ):
            self.assertIn(f"{label} {value}", text)
        self.assertIn("Rótulo de origem de Vmax via de saída do VE: LVOT Vmax.", text)
        self.assertIn("Rótulo de origem de Gradiente via de saída do VE: LVOT Max PG.", text)
        self.assertNotIn("calculado", text)
        self.assertNotIn("4.08 mmHg", text)
        self.assertEqual(payload, original)

    def test_each_acquisition_derives_only_its_own_missing_gradient(self):
        for velocity, gradient, location in SAIDAS_DOPPLER:
            with self.subTest(velocity=velocity):
                payload = _payload({velocity: "1.01", f"{velocity}_origem": "informado"})
                original = deepcopy(payload)
                text = _text(payload)
                self.assertIn(f"Vmax {location} 1.01 m/s", text)
                self.assertIn(f"Gradiente {location} (calculado: 4 × V²) 4.08 mmHg", text)
                for other_velocity, _, other_location in SAIDAS_DOPPLER:
                    if other_velocity != velocity:
                        self.assertNotIn(f"Vmax {other_location} ", text)
                        self.assertNotIn(f"Gradiente {other_location} ", text)
                self.assertEqual(payload, original)

                derivar_gradientes_saidas_para_pdf(payload)
                self.assertEqual(payload["medidas"][gradient], 4.08)
                self.assertEqual(payload["medidas"][f"{gradient}_origem"], "calculado")

    def test_only_absent_gradient_can_be_derived(self):
        for absent in (None, "", "  "):
            with self.subTest(absent=absent):
                payload = _payload({"Vmax_VSVE": "1.01", "Grad_VSVE": absent})
                derivar_gradientes_saidas_para_pdf(payload)
                self.assertEqual(payload["medidas"]["Grad_VSVE"], 4.08)
        for recorded in ("4,11", "4.1126", "0", "-1", "inválido", "NaN", "Infinity"):
            with self.subTest(recorded=recorded):
                payload = _payload({"Vmax_VSVE": "1.01", "Grad_VSVE": recorded})
                derivar_gradientes_saidas_para_pdf(payload)
                self.assertEqual(payload["medidas"]["Grad_VSVE"], recorded)
                self.assertNotIn("Grad_VSVE_origem", payload["medidas"])
        for invalid_velocity in ("0", "-1", "inválido", "NaN", "Infinity", "1e308"):
            with self.subTest(invalid_velocity=invalid_velocity):
                payload = _payload({"Vmax_VSVE": invalid_velocity})
                derivar_gradientes_saidas_para_pdf(payload)
                self.assertNotIn("Grad_VSVE", payload["medidas"])

    def test_invalid_filled_gradient_is_visible_for_confirmation_without_substitution(self):
        payload = _payload({"Vmax_VSVE": "1.01", "Grad_VSVE": "inválido <conferir>"})
        text = _text(payload)
        self.assertIn("Gradiente via de saída do VE inválido <conferir> (valor a confirmar)", text)
        self.assertNotIn("4.08 mmHg", text)
        self.assertNotIn("calculado", text)

    def test_explicitly_calculated_gradient_follows_changed_or_missing_velocity(self):
        for velocity, gradient, location in SAIDAS_DOPPLER:
            with self.subTest(velocity=velocity):
                payload = _payload({
                    velocity: "1.20", gradient: "4.08", f"{gradient}_origem": "calculado",
                })
                text = _text(payload)
                self.assertIn(f"Gradiente {location} (calculado: 4 × V²) 5.76 mmHg", text)
                self.assertEqual(payload["medidas"][gradient], "4.08")
                for absent in (None, "", "inválido"):
                    payload["medidas"][velocity] = absent
                    derivar_gradientes_saidas_para_pdf(payload)
                    self.assertNotIn(gradient, payload["medidas"])
                    self.assertNotIn(f"{gradient}_origem", payload["medidas"])
                    payload["medidas"].update({gradient: "4.08", f"{gradient}_origem": "calculado"})

    def test_legacy_pulmonary_field_is_not_moved_or_declared_as_rvot(self):
        payload = _payload({"Vmax_pulmonar": "0.80", "Grad_pulmonar": "2.57"})
        original = deepcopy(payload)
        text = _text(payload)
        self.assertIn("Vmax pulmonar 0.80 m/s", text)
        self.assertIn("Gradiente pulmonar 2.57 mmHg", text)
        self.assertIn("Origem não confirmada: Vmax pulmonar; Gradiente pulmonar.", text)
        self.assertNotIn("via de saída do VD", text)
        self.assertNotIn("calculado", text)
        self.assertEqual(payload, original)

    def test_legacy_vsve_gradient_keeps_value_without_calculation_claim(self):
        text = _text(_payload({"Vmax_VSVE": "1.01", "Grad_VSVE": "4.11"}))
        self.assertIn("Gradiente via de saída do VE 4.11 mmHg", text)
        self.assertIn("Origem não confirmada", text)
        self.assertNotIn("calculado", text)
        self.assertNotIn("4 × V²", text)

    def test_saved_qualitative_outflow_titles_and_text_are_preserved(self):
        payload = _payload({})
        payload["qualitativa"] = {
            "vasos": "- VSVD: Texto salvo da via direita.\n- Fluxo pulmonar: Texto salvo pulmonar.\n"
                     "- VSVE: Texto salvo da via esquerda.\n- Fluxo aórtico: Texto salvo aórtico.",
        }
        text = _text(payload)
        for title, body in (
            ("VSVD", "Texto salvo da via direita."),
            ("Fluxo pulmonar", "Texto salvo pulmonar."),
            ("VSVE", "Texto salvo da via esquerda."),
            ("Fluxo aórtico", "Texto salvo aórtico."),
        ):
            self.assertIn(f"{title} {body}", text)


if __name__ == "__main__":
    unittest.main()
