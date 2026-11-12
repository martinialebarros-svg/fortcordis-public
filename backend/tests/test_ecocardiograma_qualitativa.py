import os
import sys
import unittest
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.utils.ecocardiograma_qualitativa import extrair_qualitativa_ecocardiograma_da_descricao  # noqa: E402
from app.utils.pdf_laudo import gerar_pdf_laudo_eco  # noqa: E402


class QualitativaEcocardiogramaTest(unittest.TestCase):
    def test_preserva_todos_os_itens_do_grupo_e_limita_a_secao(self) -> None:
        descricao = """## Medidas Ecocardiograficas
- DIVEd: 30

## Avaliação Qualitativa
- valvas:
- Valva mitral: espessamento discreto.
- Valva tricúspide: refluxo discreto.
- camaras:
- Átrio esquerdo: sem aumento.
- pericardio: Sem derrame pericárdico.

## Outra seção
- vasos: texto externo
"""
        qualitativa = extrair_qualitativa_ecocardiograma_da_descricao(descricao)

        self.assertEqual(qualitativa["valvas"], "- Valva mitral: espessamento discreto.\n- Valva tricúspide: refluxo discreto.")
        self.assertEqual(qualitativa["camaras"], "- Átrio esquerdo: sem aumento.")
        self.assertEqual(qualitativa["pericardio"], "Sem derrame pericárdico.")
        self.assertNotIn("vasos", qualitativa)

        pdf = gerar_pdf_laudo_eco({
            "paciente": {"nome": "Teste", "especie": "Canina", "peso": "10"},
            "medidas": {"DIVEd": "30"},
            "qualitativa": qualitativa,
            "conclusao": "",
        })
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("espessamento discreto", text)
        self.assertIn("refluxo discreto", text)
        self.assertIn("sem aumento", text)
        self.assertNotIn("texto externo", text)

    def test_nao_extrai_sem_secao_qualitativa(self) -> None:
        self.assertEqual(
            extrair_qualitativa_ecocardiograma_da_descricao("## Medidas Ecocardiograficas\n- valvas: texto indevido"),
            {},
        )


if __name__ == "__main__":
    unittest.main()
