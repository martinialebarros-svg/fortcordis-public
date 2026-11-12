import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-documento-variaveis-vazias-secret-key-1234567890")

from app.services.atendimento.document_context_service import (
    identificar_variaveis_vazias,
    renderizar_template_documento,
)


class IdentificarVariaveisVaziasTest(unittest.TestCase):
    """Achado #42 da auditoria: `{{chave}}` nao resolvida ou vazia ficava
    indistinguivel do texto normal no documento gerado."""

    def test_chave_com_valor_vazio_no_contexto_e_reportada(self) -> None:
        contexto = {"peso": "", "paciente_nome": "Rex"}
        vazias = identificar_variaveis_vazias("{{paciente_nome}}, {{peso}}", contexto)
        self.assertEqual(vazias, ["peso"])

    def test_chave_com_valor_preenchido_nao_e_reportada(self) -> None:
        contexto = {"peso": "8.4 kg", "paciente_nome": "Rex"}
        vazias = identificar_variaveis_vazias("{{paciente_nome}}, {{peso}}", contexto)
        self.assertEqual(vazias, [])

    def test_chave_ausente_do_contexto_nao_e_reportada_como_vazia(self) -> None:
        """Chave que nem existe no contexto (ex.: template com typo ou campo
        novo ainda nao suportado) e um problema diferente - "nao resolvida",
        nao "vazia". `identificar_variaveis_vazias` so cobre o segundo caso;
        o primeiro e detectado pelo `{{...}}` remanescente no texto apos
        `renderizar_template_documento`, que o frontend escaneia ao vivo."""
        contexto = {"peso": "8.4 kg"}
        vazias = identificar_variaveis_vazias("{{crmv}}, {{peso}}", contexto)
        self.assertEqual(vazias, [])
        renderizado = renderizar_template_documento("{{crmv}}, {{peso}}", contexto)
        self.assertEqual(renderizado, "{{crmv}}, 8.4 kg")

    def test_chave_repetida_e_reportada_uma_unica_vez(self) -> None:
        contexto = {"raca": ""}
        vazias = identificar_variaveis_vazias("{{raca}} - {{raca}}", contexto)
        self.assertEqual(vazias, ["raca"])

    def test_template_sem_variaveis_vazias_retorna_lista_vazia(self) -> None:
        vazias = identificar_variaveis_vazias("Texto fixo sem chaves.", {})
        self.assertEqual(vazias, [])


if __name__ == "__main__":
    unittest.main()
