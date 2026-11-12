"""Painel de configuracao do bot: prontidao, conteudo e simulacao (Fase 6)."""
import hashlib
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-painel-test-secret-key-1234567890")

from app.api.v1.endpoints import whatsapp_bot
from app.models.assistente_ia import AssistenteIAConhecimentoDocumento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.whatsapp_bot import WhatsAppBotSolicitacao
from app.models.whatsapp_bot import WhatsAppBotResposta
from app.services import whatsapp_bot_readiness_service as readiness

CONTEUDO_AGENDAR = (
    "Para agendar uma consulta ou exame na FortCordis, o tutor fala com a recepcao "
    "pelo WhatsApp ou por telefone. A equipe confirma o horario e orienta o preparo."
)


class _Admin(SimpleNamespace):
    def tem_papel(self, papel):
        return papel == "admin"


class WhatsAppBotPainelTest(unittest.TestCase):
    def _factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "painel.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__, Servico.__table__, Paciente.__table__,
            Clinica.__table__,
            Laudo.__table__, Exame.__table__, AtendimentoClinico.__table__,
            AssistenteIAConhecimentoDocumento.__table__, WhatsAppBotResposta.__table__, WhatsAppBotSolicitacao.__table__,
        ):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _doc(self, db, *, categoria="institucional", fonte="Recepcao", conteudo=CONTEUDO_AGENDAR):
        db.add(AssistenteIAConhecimentoDocumento(
            id=uuid.uuid4().hex[:36], titulo="Como agendar na FortCordis",
            categoria=categoria, conteudo=conteudo, fonte=fonte,
            conteudo_sha256=hashlib.sha256(conteudo.encode()).hexdigest(),
            status="active", criado_por_id=1,
        ))
        db.commit()

    def _sem_rede(self):
        from app.services import assistente_ia_autonomy as autonomy
        return patch.object(
            autonomy, "_embed_texts", side_effect=AssertionError("teste nao deve chamar embeddings")
        )

    # --- prontidao -----------------------------------------------------

    def test_prontidao_base_vazia_aponta_o_que_falta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    with self._sem_rede():
                        r = readiness.coletar_prontidao(db)
                finally:
                    db.close()

                self.assertEqual(set(r["personas"]), {"tutor", "clinica"})
                for persona in ("tutor", "clinica"):
                    itens = {i["intent"]: i for i in r["personas"][persona]["itens"]}
                    # As tres intents de conhecimento nao tem fonte com base vazia.
                    for intent in ("area_atendimento",):
                        self.assertFalse(itens[intent]["pronto"], f"{persona}/{intent}")
                        self.assertTrue(itens[intent]["diagnostico"])
                # Sem Configuracao nem Servico, institucional e preco tambem faltam.
                tutor = {i["intent"]: i for i in r["personas"]["tutor"]["itens"]}
                self.assertFalse(tutor["endereco"]["pronto"])
                self.assertFalse(tutor["preco_servico"]["pronto"])
            finally:
                engine.dispose()

    def test_prontidao_fica_verde_quando_a_fonte_existe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(
                        cidade="Fortaleza", endereco="Rua Teste, 100",
                        telefone="8533334444", email="contato@fortcordis.com",
                    ))
                    db.add(Servico(nome="Ecocardiograma", ativo=True, preco_fortaleza_comercial=420,
                                    preco_domiciliar_comercial=520))
                    db.commit()
                    self._doc(db)
                    with self._sem_rede():
                        r = readiness.coletar_prontidao(db)
                finally:
                    db.close()

                tutor = {i["intent"]: i for i in r["personas"]["tutor"]["itens"]}
                self.assertTrue(tutor["endereco"]["pronto"])
                self.assertTrue(tutor["formas_contato"]["pronto"])
                self.assertTrue(tutor["preco_servico"]["pronto"])
                self.assertTrue(tutor["horario_funcionamento"]["pronto"])
                self.assertTrue(tutor["como_agendar"]["pronto"], tutor["como_agendar"])
            finally:
                engine.dispose()

    def test_prontidao_nao_da_verde_com_cadastro_institucional_vazio(self) -> None:
        """Falso verde medido em stage (2026-08-23).

        Existia linha de `Configuracao` com so cidade e estado. A tool
        respondia `ok=True`, e o painel — cuja funcao e justamente dizer se o
        bot consegue responder — pintava `endereco` e `formas_contato` de
        verde sem haver endereco nem telefone cadastrado.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(cidade="Fortaleza", estado="CE"))
                    db.commit()
                    with self._sem_rede():
                        r = readiness.coletar_prontidao(db)
                finally:
                    db.close()

                for persona in ("tutor", "clinica"):
                    itens = {i["intent"]: i for i in r["personas"][persona]["itens"]}
                    for intent in ("endereco", "formas_contato"):
                        self.assertFalse(itens[intent]["pronto"], f"{persona}/{intent}")
                        self.assertTrue(itens[intent]["diagnostico"], f"{persona}/{intent}")
            finally:
                engine.dispose()

    def test_prontidao_separa_endereco_de_formas_de_contato(self) -> None:
        """Uma tool sustenta duas intents; o veredito nao pode ser um so."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    # Telefone preenchido, endereco ainda vazio.
                    db.add(Configuracao(cidade="Fortaleza", telefone="(85) 3333-4444"))
                    db.commit()
                    with self._sem_rede():
                        r = readiness.coletar_prontidao(db)
                finally:
                    db.close()

                tutor = {i["intent"]: i for i in r["personas"]["tutor"]["itens"]}
                self.assertTrue(tutor["formas_contato"]["pronto"])
                self.assertFalse(tutor["endereco"]["pronto"])
                self.assertIn("Endereco vazio", tutor["endereco"]["diagnostico"])
            finally:
                engine.dispose()

    def test_preco_servico_e_sondado_mas_nao_e_auto_elegivel(self) -> None:
        """Tirar do `auto` nao pode apagar do painel.

        A prontidao sonda `INTENTS_ATENDIDAS_POR_PERSONA`; so a elegibilidade
        vem de `INTENTS_AUTO_POR_PERSONA`. Se as duas fossem a mesma lista, o
        admin perderia a visibilidade de que a fonte de preco esta sa.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(cidade="Fortaleza", endereco="Rua Teste, 100", telefone="8533334444"))
                    db.add(Servico(nome="Ecocardiograma", ativo=True, preco_fortaleza_comercial=420,
                                    preco_domiciliar_comercial=520))
                    db.commit()
                    with self._sem_rede():
                        r = readiness.coletar_prontidao(db)
                finally:
                    db.close()

                for persona in ("tutor", "clinica"):
                    itens = {i["intent"]: i for i in r["personas"][persona]["itens"]}
                    self.assertIn("preco_servico", itens, f"{persona}: sumiu do painel")
                    self.assertTrue(itens["preco_servico"]["pronto"], f"{persona}: fonte deveria estar sa")
                    self.assertFalse(
                        itens["preco_servico"]["auto_elegivel"],
                        f"{persona}: preco nao pode ser auto-elegivel enquanto plantao nao for modelado",
                    )
                    # As demais continuam auto-elegiveis.
                    self.assertTrue(itens["horario_funcionamento"]["auto_elegivel"], persona)
            finally:
                engine.dispose()

    def test_prontidao_explica_categoria_errada_em_vez_de_so_dizer_nao(self) -> None:
        """O diagnostico e o ponto do painel: cadastrar as cegas foi o que
        deixou a regressao do piso passar tres fases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._doc(db, categoria="manual")
                    with self._sem_rede():
                        r = readiness.coletar_prontidao(db)
                finally:
                    db.close()

                item = {i["intent"]: i for i in r["personas"]["tutor"]["itens"]}["como_agendar"]
                self.assertFalse(item["pronto"])
                self.assertIn("categoria", item["diagnostico"].lower())
            finally:
                engine.dispose()

    def test_prontidao_explica_fonte_ausente(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._doc(db, fonte=None)
                    with self._sem_rede():
                        r = readiness.coletar_prontidao(db)
                finally:
                    db.close()
                item = {i["intent"]: i for i in r["personas"]["tutor"]["itens"]}["como_agendar"]
                self.assertFalse(item["pronto"])
                self.assertIn("fonte", item["diagnostico"].lower())
            finally:
                engine.dispose()

    def test_prontidao_nao_chama_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    from app.services import whatsapp_bot_providers as providers
                    with patch.object(
                        providers, "get_whatsapp_bot_reply_provider",
                        side_effect=AssertionError("prontidao nao deve chamar LLM"),
                    ):
                        with self._sem_rede():
                            r = readiness.coletar_prontidao(db)
                    self.assertIn("resumo", r)
                finally:
                    db.close()
            finally:
                engine.dispose()

    # --- conteudo ------------------------------------------------------

    def test_listagem_separa_visivel_de_ignorado_pelo_bot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._doc(db, categoria="institucional")
                    self._doc(db, categoria="manual", conteudo=CONTEUDO_AGENDAR + " Variante interna.")
                    r = whatsapp_bot.listar_conhecimento_do_bot(db=db, current_user=_Admin(id=1))
                finally:
                    db.close()
                self.assertEqual(r["total_visiveis"], 1)
                self.assertEqual(r["total_ignorados"], 1)
            finally:
                engine.dispose()

    def test_publico_define_categoria_sem_campo_livre(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    for publico, esperado in (
                        ("tutor", "institucional_tutor"),
                        ("clinica", "institucional_clinica"),
                        ("ambos", "institucional"),
                    ):
                        req = whatsapp_bot.WhatsAppBotConhecimentoCreateRequest(
                            titulo=f"Doc {publico}",
                            conteudo=CONTEUDO_AGENDAR + f" Publico {publico}.",
                            publico=publico,
                            fonte="Recepcao FortCordis",
                        )
                        r = whatsapp_bot.criar_conhecimento_do_bot(
                            req, db=db, current_user=_Admin(id=1, nome="Admin", email="a@b.c")
                        )
                        self.assertEqual(r["categoria_aplicada"], esperado)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_publico_invalido_e_422(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    req = whatsapp_bot.WhatsAppBotConhecimentoCreateRequest(
                        titulo="Doc", conteudo=CONTEUDO_AGENDAR, publico="staff", fonte="Recepcao",
                    )
                    with self.assertRaises(HTTPException) as ctx:
                        whatsapp_bot.criar_conhecimento_do_bot(req, db=db, current_user=_Admin(id=1))
                    self.assertEqual(ctx.exception.status_code, 422)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_fonte_e_obrigatoria_no_schema(self) -> None:
        """A fonte opcional era um dos jeitos silenciosos de tornar o
        documento invisivel para o bot."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            whatsapp_bot.WhatsAppBotConhecimentoCreateRequest(
                titulo="Doc", conteudo=CONTEUDO_AGENDAR, publico="ambos",
            )

    # --- simulacao -----------------------------------------------------

    def test_simulacao_nao_persiste_resposta(self) -> None:
        """Se gravasse, a simulacao entraria no denominador de aceite e
        contaminaria o numero que autoriza o modo auto."""
        from app.services import whatsapp_bot_simulation_service as sim
        from app.services.whatsapp_bot_providers import GeneratedReply
        from app.schemas.whatsapp_bot import WhatsAppBotReplyOutput

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    db.add(Configuracao(cidade="Fortaleza", endereco="Rua Teste, 100",
                                        telefone="8533334444", email="c@f.com"))
                    db.commit()
                    fake = SimpleNamespace(generate=Mock(return_value=GeneratedReply(
                        output=WhatsAppBotReplyOutput(
                            texto="Atendimento automatico da FortCordis. Posso chamar uma pessoa.",
                            intent="formas_contato", fontes=[], precisa_humano=False,
                        ),
                        model="fake", input_tokens=10, output_tokens=5,
                    )))
                    with patch.object(sim, "gerar_resposta", wraps=sim.gerar_resposta):
                        with patch(
                            "app.services.whatsapp_bot_generation.get_whatsapp_bot_reply_provider",
                            return_value=fake,
                        ):
                            with self._sem_rede():
                                r = sim.simular_resposta(db, mensagem="como falo com voces?", persona="tutor")
                    total = db.query(WhatsAppBotResposta).count()
                finally:
                    db.close()

                self.assertTrue(r["simulacao"])
                self.assertEqual(r["persona"], "tutor")
                self.assertEqual(total, 0, "simulacao nao pode gravar resposta")
                self.assertIn("nao contaminar", r["observacao"])
            finally:
                engine.dispose()

    def test_simulacao_recusa_persona_e_mensagem_invalidas(self) -> None:
        from app.services import whatsapp_bot_simulation_service as sim

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    with self.assertRaises(ValueError):
                        sim.simular_resposta(db, mensagem="oi", persona="tutor")
                    with self.assertRaises(ValueError):
                        sim.simular_resposta(db, mensagem="mensagem valida", persona="staff")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_persona_forcada_nao_vaza_dado_de_cliente(self) -> None:
        """A simulacao assume a persona, mas com escopo sintetico: as tools de
        dado do cliente tem que voltar vazias."""
        from app.services.whatsapp_bot_tools import WhatsAppBotToolContext, consultar_status_laudo

        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    tutor_real_id = 77
                    pac = Paciente(nome="Thor", tutor_id=tutor_real_id, ativo=1)
                    db.add(pac); db.commit()
                    laudo = Laudo(paciente_id=pac.id, veterinario_id=1, tipo="exame",
                                  titulo="Eco", status="Liberado no portal")
                    db.add(laudo); db.commit()
                    db.add(Exame(paciente_id=pac.id, laudo_id=laudo.id,
                                 tipo_exame="Ecocardiograma", status="Concluido"))
                    db.commit()

                    ctx = WhatsAppBotToolContext(db=db, match_type="tutor", tutor_id=0)
                    r = consultar_status_laudo(ctx)
                finally:
                    db.close()
                self.assertFalse(r["ok"], "escopo sintetico nao pode alcancar dado real")
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
