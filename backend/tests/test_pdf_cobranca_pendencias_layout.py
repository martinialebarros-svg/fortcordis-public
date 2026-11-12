import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "cobranca-pdf-layout-test-secret-key-123456789")

from app.api.v1.endpoints import ordens_servico  # noqa: E402


class CobrancaPendenciasPdfLayoutTest(unittest.TestCase):
    def test_long_table_text_wraps_inside_page_width(self) -> None:
        captured = []

        class CaptureTable(Table):
            def __init__(self, data, *args, **kwargs):
                super().__init__(data, *args, **kwargs)
                if len(data[0]) == 6:
                    captured.append((data, self))

        tutor = "FRANCISCO ANTONIO DE SOUZA DA SILVA & FAMILIA"
        with patch.object(ordens_servico, "Table", CaptureTable):
            pdf = ordens_servico._gerar_pdf_cobranca_pendencias(
                itens=[
                    {
                        "chave": "clinica:1",
                        "destinatario_tipo": "clinica",
                        "destinatario_nome": "Clinica de teste",
                        "destinatario_telefone": "",
                        "destinatario_email": "",
                        "numero_os": "OS2026090078123456",
                        "data_atendimento": "2026-09-17",
                        "paciente": "Maria Flor <Filhote> com nome extenso",
                        "tutor": tutor,
                        "servico": "Ecocardiograma Doppler colorido completo",
                        "valor_final": 180,
                    }
                ],
                nome_empresa="Fort Cordis",
                contato_empresa="",
                texto_rodape="",
                filtros_texto="status=Pendente",
            )

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(len(captured), 1)
        data, tabela = captured[0]
        self.assertTrue(all(isinstance(celula, Paragraph) for celula in data[1]))
        self.assertEqual(data[1][0].getPlainText(), "OS2026090078123456")
        self.assertEqual(data[1][2].getPlainText(), "Maria Flor <Filhote> com nome extenso")
        self.assertEqual(data[1][3].getPlainText(), tutor)
        self.assertLessEqual(sum(tabela._colWidths), A4[0] - 28 * mm - 12)
        self.assertGreater(tabela._rowHeights[1], tabela._rowHeights[0])


if __name__ == "__main__":
    unittest.main()
