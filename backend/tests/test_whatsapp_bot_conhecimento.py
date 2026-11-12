"""Liga o wrapper do bot ao retorno REAL de search_knowledge.

Este arquivo existe por causa de uma regressao concreta: o wrapper comparava
o `score` normalizado de `search_knowledge` (teto 1.0) contra um piso de 2.0,
o que fazia `buscar_conhecimento_institucional` devolver ok=False para toda
pergunta e todo documento. As intents `area_atendimento`, `como_agendar` e
`como_solicitar_exame` ficavam permanentemente em `sem_fonte`, e o bug
atravessou tres fases porque nenhum teste percorria o caminho real - todos
montavam `tools_ok` a mao.
"""
import hashlib
import os
import sys
import uuid
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-conhecimento-test-secret-key-1234567890")

from app.models.assistente_ia import AssistenteIAConhecimentoDocumento
from app.services import whatsapp_bot_tools as tools


def _ctx(db):
    return tools.WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=1)


class WhatsAppBotConhecimentoTest(unittest.TestCase):
    def _factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-conhecimento-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        AssistenteIAConhecimentoDocumento.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _doc(self, db, *, titulo, conteudo, categoria="institucional", fonte="Recepcao FortCordis", status="active"):
        # `id` e uuid String(36) e `conteudo_sha256` e NOT NULL - o caminho de
        # producao passa por create_document, que preenche os dois.
        doc = AssistenteIAConhecimentoDocumento(
            id=uuid.uuid4().hex[:36],
            titulo=titulo,
            categoria=categoria,
            conteudo=conteudo,
            fonte=fonte,
            conteudo_sha256=hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
            status=status,
            criado_por_id=1,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    _CONTEUDO_AGENDAR = (
        "Para agendar uma consulta ou exame na FortCordis, o tutor pode falar com a "
        "recepcao pelo WhatsApp ou por telefone. O agendamento e confirmado no mesmo "
        "dia e a equipe orienta sobre o preparo necessario para cada exame."
    )

    def _buscar(self, db, consulta):
        """Executa o caminho REAL, provando que nao ha rede.

        Nenhum documento destes testes fica com `semantic_status == "ready"`,
        entao `semantic_search_documents` retorna [] antes de qualquer
        embedding. O side_effect abaixo transforma essa expectativa em
        assercao: se algum dia o caminho semantico for alcancado, o teste
        falha em vez de fazer chamada paga em silencio.
        """
        from app.services import assistente_ia_autonomy as autonomy

        with patch.object(
            autonomy,
            "_embed_texts",
            side_effect=AssertionError("teste nao deve chamar embeddings"),
        ):
            return tools.buscar_conhecimento_institucional(_ctx(db), consulta=consulta)

    # --- o caso que falhava antes da correcao --------------------------

    def test_documento_institucional_realista_e_recuperado(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._doc(db, titulo="Como agendar na FortCordis", conteudo=self._CONTEUDO_AGENDAR)
                    resultado = self._buscar(db, "como faco para agendar uma consulta?")
                finally:
                    db.close()

                self.assertTrue(resultado["ok"], resultado)
                self.assertGreaterEqual(len(resultado["trechos"]), 1)
                trecho = resultado["trechos"][0]
                self.assertEqual(trecho["titulo"], "Como agendar na FortCordis")
                self.assertEqual(trecho["fonte"], "Recepcao FortCordis")
                self.assertTrue(trecho["trecho"])
            finally:
                engine.dispose()

    def test_piso_de_relevancia_e_alcancavel_na_escala_real(self) -> None:
        """Guarda contra reintroduzir um piso fora de escala.

        O `score` de search_knowledge tem teto 1.0 (0.35 lexical + 0.65
        semantico). Qualquer piso acima disso desliga a base inteira.
        """
        self.assertLessEqual(tools.CONHECIMENTO_SEMANTIC_SCORE_MINIMO, 1.0)
        # keyword_score e absoluto (5/termo no titulo, 1/termo no conteudo),
        # entao um piso pequeno e legitimo - mas nao pode ser comparado com
        # `score`. O teste acima prova o caminho ponta a ponta.
        self.assertGreater(tools.CONHECIMENTO_KEYWORD_SCORE_MINIMO, 0)

    # --- os tres filtros, cada um com diagnostico ----------------------

    def test_categoria_default_manual_e_descartada_com_diagnostico(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._doc(
                        db, titulo="Como agendar na FortCordis",
                        conteudo=self._CONTEUDO_AGENDAR, categoria="manual",
                    )
                    resultado = self._buscar(db, "como faco para agendar uma consulta?")
                finally:
                    db.close()

                self.assertFalse(resultado["ok"])
                self.assertEqual(resultado["motivo"], "todos_descartados")
                self.assertEqual(resultado["descartados"]["categoria"], 1)
            finally:
                engine.dispose()

    def test_documento_sem_fonte_e_descartado_com_diagnostico(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._doc(
                        db, titulo="Como agendar na FortCordis",
                        conteudo=self._CONTEUDO_AGENDAR, fonte=None,
                    )
                    resultado = self._buscar(db, "como faco para agendar uma consulta?")
                finally:
                    db.close()

                self.assertFalse(resultado["ok"])
                self.assertEqual(resultado["descartados"]["sem_fonte"], 1)
            finally:
                engine.dispose()

    def test_variacoes_de_categoria_sao_aceitas(self) -> None:
        """A UI de admin e campo de texto livre; quem digita
        'Institucional - Tutor' quer o mesmo que 'institucional'."""
        for categoria in ("Institucional", "INSTITUCIONAL", "institucional_tutor",
                          "Institucional - Clinica", "atendimento", "Atendimento WhatsApp"):
            with self.subTest(categoria=categoria):
                with tempfile.TemporaryDirectory() as tmpdir:
                    Factory, engine = self._factory(tmpdir)
                    try:
                        db = Factory()
                        try:
                            self._doc(
                                db, titulo="Como agendar na FortCordis",
                                conteudo=self._CONTEUDO_AGENDAR, categoria=categoria,
                            )
                            resultado = self._buscar(db, "como faco para agendar uma consulta?")
                        finally:
                            db.close()
                        self.assertTrue(resultado["ok"], f"{categoria}: {resultado}")
                    finally:
                        engine.dispose()

    def test_categoria_de_staff_continua_fora(self) -> None:
        """A base e compartilhada com o assistente interno e contem
        procedimento clinico. Alargar a allowlist para o balde default
        faria manual de staff alimentar resposta a cliente."""
        for categoria in ("manual", "operacao", "procedimento", "clinico"):
            with self.subTest(categoria=categoria):
                self.assertFalse(tools._categoria_e_institucional(categoria))

    def test_base_vazia_nao_estoura(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    resultado = self._buscar(db, "como faco para agendar uma consulta?")
                finally:
                    db.close()
                self.assertFalse(resultado["ok"])
            finally:
                engine.dispose()

    def test_documento_arquivado_nao_e_recuperado(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._doc(
                        db, titulo="Como agendar na FortCordis",
                        conteudo=self._CONTEUDO_AGENDAR, status="archived",
                    )
                    resultado = self._buscar(db, "como faco para agendar uma consulta?")
                finally:
                    db.close()
                self.assertFalse(resultado["ok"])
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
