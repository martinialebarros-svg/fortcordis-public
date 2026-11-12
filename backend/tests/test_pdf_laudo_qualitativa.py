import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.utils import pdf_laudo


class PdfLaudoQualitativaTest(unittest.TestCase):
    @staticmethod
    def _extrair_textos(elementos):
        textos = []

        def _visitar(item):
            if hasattr(item, "getPlainText"):
                textos.append(item.getPlainText())
            if hasattr(item, "_content"):
                for subitem in item._content:
                    _visitar(subitem)
            if hasattr(item, "_cellvalues"):
                for row in item._cellvalues:
                    for celula in row:
                        if isinstance(celula, list):
                            for subitem in celula:
                                _visitar(subitem)
                        else:
                            _visitar(celula)

        for item in elementos:
            _visitar(item)
        return textos

    def test_criar_secao_qualitativa_renderiza_grupos_e_itens_em_blocos(self) -> None:
        elementos = pdf_laudo.criar_secao_qualitativa(
            {
                "valvas": "  - Valva mitral: Texto mitral.\n  - Valva aortica: Texto aortico.",
                "ad_vd": "  - Atrio direito: Texto AD.\n  - Ventriculo direito: Texto VD.",
            }
        )

        textos = self._extrair_textos(elementos)
        texto_unico = "\n".join(textos)

        self.assertIn("Valvas", textos)
        self.assertIn("Câmaras direitas", textos)
        self.assertIn("• Valva mitral", texto_unico)
        self.assertIn("Texto mitral.", texto_unico)
        self.assertIn("• Valva aortica", texto_unico)
        self.assertIn("Texto aortico.", texto_unico)
        self.assertIn("• Atrio direito", texto_unico)
        self.assertIn("Texto AD.", texto_unico)
        self.assertIn("• Ventriculo direito", texto_unico)
        self.assertIn("Texto VD.", texto_unico)

    def test_criar_secao_conclusao_renderiza_paragrafos_e_lista(self) -> None:
        elementos = pdf_laudo.criar_secao_conclusao(
            "Primeiro paragrafo.\n\n- Item A: detalhe A.\n- Item B: detalhe B."
        )

        textos = self._extrair_textos(elementos)
        texto_unico = "\n".join(textos)

        self.assertIn("CONCLUSÃO", texto_unico)
        self.assertIn("Primeiro paragrafo.", texto_unico)
        self.assertIn("• Item A", texto_unico)
        self.assertIn("detalhe A.", texto_unico)
        self.assertIn("• Item B", texto_unico)
        self.assertIn("detalhe B.", texto_unico)

    def test_criar_secao_pressao_arterial_renderiza_resumo_procedimento_e_classificacao(self) -> None:
        elementos = pdf_laudo.criar_secao_pressao_arterial(
            {
                "pas_1": "180",
                "pas_2": "170",
                "pas_3": "160",
                "pas_media": "170",
                "metodo": "Doppler",
                "manguito": "3",
                "membro": "Toracico direito",
                "decubito": "Lateral",
                "obs_extra": "Paciente agitado.",
            }
        )

        textos = self._extrair_textos(elementos)
        texto_unico = "\n".join(textos)

        self.assertIn("PRESSAO ARTERIAL (ANEXO)", texto_unico)
        self.assertIn("1a afericao", texto_unico)
        self.assertIn("PAS media", texto_unico)
        self.assertIn("170 mmHg", texto_unico)
        self.assertIn("Metodo", texto_unico)
        self.assertIn("Doppler", texto_unico)
        self.assertIn("Classificacao PAS", texto_unico)
        self.assertIn("Moderadamente elevada (160 a 179 mmHg)", texto_unico)
        self.assertIn("Observacoes adicionais", texto_unico)
        self.assertIn("Paciente agitado.", texto_unico)

    def test_criar_cabecalho_nao_forca_defaults_de_ritmo_ou_estado(self) -> None:
        elementos = pdf_laudo.criar_cabecalho(
            {
                "paciente": {
                    "nome": "Thor",
                    "especie": "Canina",
                    "raca": "SRD",
                    "sexo": "Macho",
                    "idade": "5 anos",
                    "peso": "10.0",
                    "tutor": "Maria",
                    "solicitante": "Dr. Joao",
                    "data_exame": "14/03/2026",
                    "ritmo": "",
                    "estado": "",
                    "fc": "",
                },
                "clinica": "Clinica Teste",
            }
        )

        textos = self._extrair_textos(elementos)
        texto_unico = "\n".join(textos)

        self.assertNotIn("Sinusal", texto_unico)
        self.assertNotIn("Calmo", texto_unico)
        self.assertNotIn("bpm", texto_unico)
        self.assertNotIn("Ritmo | FC | Estado", texto_unico)


if __name__ == "__main__":
    unittest.main()
