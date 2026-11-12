import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-endpoints-test-secret-key-1234567890")

from app.api.v1.endpoints import whatsapp_bot
from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotContextoSelecao
from app.models.whatsapp_bot import WhatsAppBotSolicitacao
from app.models.whatsapp_bot import WhatsAppBotConversaEstado, WhatsAppBotJob, WhatsAppBotResposta


class WhatsAppBotEndpointsTest(unittest.TestCase):
    def setUp(self):
        # Transporte do endpoint isolado; escopo real coberto em test_whatsapp_bot_contexto_entrega.
        guard = patch("app.services.whatsapp_contexto_selecao_service.resposta_contexto_vigente", return_value=True)
        guard.start()
        self.addCleanup(guard.stop)

    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-endpoints-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            WhatsAppBotContextoSelecao.__table__,
            Configuracao.__table__,
            WhatsAppBotConversaEstado.__table__,
            WhatsAppBotJob.__table__,
            WhatsAppBotResposta.__table__, WhatsAppBotSolicitacao.__table__,
        ):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _user(self, user_id=1):
        return SimpleNamespace(id=user_id)

    def _create_draft(self, db, *, texto="Rascunho original"):
        job = WhatsAppBotJob(
            wa_identity="558588018899",
            conversation_id="77",
            wa_message_id=f"wamid.{texto}",
            status="done",
            scheduled_for=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()
        resposta = WhatsAppBotResposta(
            job_id=job.id,
            wa_identity=job.wa_identity,
            conversation_id=job.conversation_id,
            decisao="draft",
            motivo="modo_suggest",
            texto_gerado=texto,
        )
        db.add(resposta)
        db.commit()
        db.refresh(resposta)
        return resposta

    def test_get_estado_sem_linha_usa_default_institucional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao(whatsapp_bot_modo="auto"))
                    db.commit()
                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                self.assertEqual(resposta["modo"], "auto")
                self.assertEqual(resposta["modo_origem"], "institucional")
                self.assertIsNone(resposta["pausado_ate"])
                self.assertFalse(resposta["pausado"])
                self.assertIsNone(resposta["rascunho_pendente"])
            finally:
                engine.dispose()

    def test_patch_estado_altera_modo_da_conversa(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    resposta = whatsapp_bot.atualizar_conversa_estado(
                        "558588018899",
                        whatsapp_bot.WhatsAppBotConversaEstadoUpdateRequest(modo="auto"),
                        db=db,
                        current_user=self._user(42),
                    )
                finally:
                    db.close()

                self.assertEqual(resposta["modo"], "auto")
                self.assertEqual(resposta["modo_origem"], "conversa")

                verify = SessionFactory()
                try:
                    estado = (
                        verify.query(WhatsAppBotConversaEstado)
                        .filter(WhatsAppBotConversaEstado.wa_identity == "558588018899")
                        .first()
                    )
                    self.assertEqual(estado.modo, "auto")
                    self.assertEqual(estado.atualizado_por_id, 42)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_patch_estado_modo_invalido_e_422(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    with self.assertRaises(HTTPException) as ctx:
                        whatsapp_bot.atualizar_conversa_estado(
                            "558588018899",
                            whatsapp_bot.WhatsAppBotConversaEstadoUpdateRequest(modo="invalido"),
                            db=db,
                            current_user=self._user(),
                        )
                    self.assertEqual(ctx.exception.status_code, 422)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_patch_estado_pausar_e_despausar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    pausado = whatsapp_bot.atualizar_conversa_estado(
                        "558588018899",
                        whatsapp_bot.WhatsAppBotConversaEstadoUpdateRequest(pausar=True),
                        db=db,
                        current_user=self._user(),
                    )
                    self.assertTrue(pausado["pausado"])
                    self.assertIsNotNone(pausado["pausado_ate"])

                    despausado = whatsapp_bot.atualizar_conversa_estado(
                        "558588018899",
                        whatsapp_bot.WhatsAppBotConversaEstadoUpdateRequest(pausar=False),
                        db=db,
                        current_user=self._user(),
                    )
                    self.assertFalse(despausado["pausado"])
                    self.assertIsNone(despausado["pausado_ate"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_get_estado_expoe_rascunho_pendente(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    job = WhatsAppBotJob(
                        wa_identity="558588018899",
                        conversation_id="conv-1",
                        wa_message_id="wamid.1",
                        status="done",
                        scheduled_for=datetime.now(timezone.utc),
                    )
                    db.add(job)
                    db.commit()
                    db.add(
                        WhatsAppBotResposta(
                            job_id=job.id,
                            wa_identity="558588018899",
                            conversation_id="conv-1",
                            decisao="draft",
                            motivo="intent_fora_da_allowlist",
                            texto_gerado="Ola! posso ajudar?",
                        )
                    )
                    db.commit()

                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                self.assertIsNotNone(resposta["rascunho_pendente"])
                self.assertEqual(resposta["rascunho_pendente"]["texto_gerado"], "Ola! posso ajudar?")
            finally:
                engine.dispose()

    def _seed_resposta(self, db, *, decisao, motivo, texto_gerado=None, wa_identity="558588018899"):
        job = WhatsAppBotJob(
            wa_identity=wa_identity,
            conversation_id="conv-1",
            wa_message_id=f"wamid.{decisao}.{motivo}",
            status="done",
            scheduled_for=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()
        db.add(
            WhatsAppBotResposta(
                job_id=job.id,
                wa_identity=wa_identity,
                conversation_id="conv-1",
                decisao=decisao,
                motivo=motivo,
                texto_gerado=texto_gerado,
            )
        )
        db.commit()

    def test_get_estado_expoe_bloqueio_com_motivo_e_sem_o_texto_recusado(self) -> None:
        """RF-022: bloqueio nunca vira silencio.

        O texto fica DE FORA de proposito: em `blocked` ele e exatamente o que o
        guardrail recusou, e devolve-lo poria a frase proibida a um
        copiar-colar de ir ao cliente.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    self._seed_resposta(
                        db,
                        decisao="blocked",
                        motivo="diagnostico",
                        texto_gerado="Pelo quadro parece cardiomiopatia dilatada.",
                    )
                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                recusa = resposta["ultima_recusa"]
                self.assertIsNotNone(recusa)
                self.assertEqual(recusa["decisao"], "blocked")
                self.assertEqual(recusa["motivo"], "diagnostico")
                self.assertNotIn("texto_gerado", recusa)
                self.assertNotIn("cardiomiopatia", json.dumps(resposta, default=str))
                self.assertIsNone(resposta["rascunho_pendente"])
            finally:
                engine.dispose()

    def test_get_estado_expoe_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    self._seed_resposta(db, decisao="handoff", motivo="emergencia")
                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                self.assertEqual(resposta["ultima_recusa"]["decisao"], "handoff")
                self.assertEqual(resposta["ultima_recusa"]["motivo"], "emergencia")
            finally:
                engine.dispose()

    def test_bloqueio_superado_por_rascunho_novo_nao_reaparece(self) -> None:
        """Olhamos a ULTIMA resposta, nao "a ultima recusa".

        Senao um bloqueio velho ficaria pendurado na tela para sempre, mesmo
        depois de o bot ter conseguido responder na mensagem seguinte.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    self._seed_resposta(db, decisao="blocked", motivo="sem_fonte")
                    self._seed_resposta(
                        db, decisao="draft", motivo="modo_suggest", texto_gerado="Funcionamos das 08h as 14h."
                    )
                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                self.assertIsNone(resposta["ultima_recusa"])
                self.assertEqual(resposta["rascunho_pendente"]["texto_gerado"], "Funcionamos das 08h as 14h.")
            finally:
                engine.dispose()

    def test_suppressed_nao_entra_em_ultima_recusa(self) -> None:
        """`suppressed` nunca e "recusa": a chave dele e `ultimo_silencio`.

        Separar as duas mantem `ultima_recusa` com a semantica estreita de
        "o guardrail barrou" e evita que a uniao fechada do frontend quebre.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    self._seed_resposta(db, decisao="suppressed", motivo="pausado")
                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                self.assertIsNone(resposta["ultima_recusa"])
            finally:
                engine.dispose()

    def test_supressao_acionavel_vira_aviso_de_silencio(self) -> None:
        """O caso medido em producao em 2026-08-25.

        Um envio assistido pausou a conversa e as mensagens seguintes do
        cliente viraram `suppressed/pausado`. Nada aparecia na central, e o
        dono concluiu que o bot estava quebrado - estava correto, so mudo.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    self._seed_resposta(db, decisao="suppressed", motivo="pausado")
                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                silencio = resposta["ultimo_silencio"]
                self.assertIsNotNone(silencio)
                self.assertEqual(silencio["motivo"], "pausado")
                self.assertIn("criado_em", silencio)
                # Linha suprimida nunca grava texto; nao devolvemos o campo.
                self.assertNotIn("texto_gerado", silencio)
                self.assertNotIn("decisao", silencio)
            finally:
                engine.dispose()

    def test_supressao_de_rotina_nao_vira_aviso(self) -> None:
        """Alertar sobre operacao normal treina o atendente a ignorar a area.

        `bot_desabilitado` apareceria em TODA conversa com o kill switch
        desligado; `modo_off` e redundante com `modo`, que ja esta no payload;
        `sem_pergunta` e a cortesia da RF-P11, e alertar inverteria a regra.
        """
        for motivo in ("bot_desabilitado", "modo_off", "sem_pergunta", "fora_do_piloto"):
            with self.subTest(motivo=motivo):
                with tempfile.TemporaryDirectory() as tmpdir:
                    SessionFactory, engine = self._build_session_factory(tmpdir)
                    try:
                        db = SessionFactory()
                        try:
                            self._seed_resposta(db, decisao="suppressed", motivo=motivo)
                            resposta = whatsapp_bot.get_conversa_estado(
                                "558588018899", db=db, current_user=self._user()
                            )
                        finally:
                            db.close()
                        self.assertIsNone(resposta["ultimo_silencio"], motivo)
                        self.assertIsNone(resposta["ultima_recusa"], motivo)
                    finally:
                        engine.dispose()

    def test_silencio_posterior_nao_apaga_a_tela_toda(self) -> None:
        """Regressao: a regra e "a ULTIMA linha", entao uma supressao depois de
        um bloqueio zerava `ultima_recusa` e a central ficava em branco.

        Agora a transicao troca um aviso pelo outro, em vez de virar vazio.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    self._seed_resposta(db, decisao="blocked", motivo="diagnostico")
                    self._seed_resposta(db, decisao="suppressed", motivo="pausado")
                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                self.assertIsNone(resposta["ultima_recusa"])
                self.assertIsNotNone(resposta["ultimo_silencio"])
                self.assertEqual(resposta["ultimo_silencio"]["motivo"], "pausado")
            finally:
                engine.dispose()

    def test_rascunho_novo_supera_o_aviso_de_silencio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    self._seed_resposta(db, decisao="suppressed", motivo="pausado")
                    self._seed_resposta(
                        db, decisao="draft", motivo="modo_suggest", texto_gerado="Posso ajudar?"
                    )
                    resposta = whatsapp_bot.get_conversa_estado("558588018899", db=db, current_user=self._user())
                finally:
                    db.close()

                self.assertIsNone(resposta["ultimo_silencio"])
                self.assertIsNotNone(resposta["rascunho_pendente"])
            finally:
                engine.dispose()

    def test_preview_nao_altera_nada_e_conta_por_status_e_decisao(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao(whatsapp_bot_atendimento_habilitado=True, whatsapp_bot_modo="suggest"))
                    db.add(
                        WhatsAppBotJob(
                            wa_identity="a", conversation_id="c1", wa_message_id="m1",
                            status="pending", scheduled_for=datetime.now(timezone.utc),
                        )
                    )
                    db.add(
                        WhatsAppBotJob(
                            wa_identity="b", conversation_id="c2", wa_message_id="m2",
                            status="done", scheduled_for=datetime.now(timezone.utc),
                        )
                    )
                    db.commit()
                    job_done = db.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "m2").first()
                    db.add(
                        WhatsAppBotResposta(
                            job_id=job_done.id, wa_identity="b", conversation_id="c2", decisao="suppressed",
                            motivo="janela_fechada",
                        )
                    )
                    db.commit()

                    resposta = whatsapp_bot.preview_whatsapp_bot(db=db, current_user=self._user())
                finally:
                    db.close()

                self.assertEqual(resposta["jobs_por_status"], {"pending": 1, "done": 1})
                self.assertEqual(resposta["respostas_por_decisao"], {"suppressed": 1})
                self.assertTrue(resposta["whatsapp_bot_atendimento_habilitado_banco"])
                self.assertEqual(resposta["whatsapp_bot_modo_institucional"], "suggest")

                verify = SessionFactory()
                try:
                    self.assertEqual(verify.query(WhatsAppBotJob).count(), 2)
                    self.assertEqual(verify.query(WhatsAppBotResposta).count(), 1)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_enviar_rascunho_editado_e_idempotente(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    resposta = self._create_draft(db)
                    node_response = Mock()
                    node_response.raise_for_status.return_value = None
                    node_response.json.return_value = {"status": "sent", "idempotent": False}
                    with (
                        patch.object(whatsapp_bot.settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://node"),
                        patch.object(whatsapp_bot.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "internal"),
                        patch.object(whatsapp_bot.httpx, "post", return_value=node_response) as post,
                        patch.object(whatsapp_bot, "registrar_auditoria") as audit,
                    ):
                        primeira = whatsapp_bot.enviar_rascunho(
                            resposta.id,
                            whatsapp_bot.WhatsAppBotRespostaEnviarRequest(texto="Texto revisado"),
                            db=db,
                            current_user=self._user(42),
                        )
                        segunda = whatsapp_bot.enviar_rascunho(
                            resposta.id,
                            whatsapp_bot.WhatsAppBotRespostaEnviarRequest(),
                            db=db,
                            current_user=self._user(42),
                        )

                    self.assertEqual(primeira["status"], "sent")
                    self.assertFalse(primeira["idempotent"])
                    self.assertTrue(segunda["idempotent"])
                    post.assert_called_once()
                    request_json = post.call_args.kwargs["json"]
                    self.assertEqual(request_json["body"], "Texto revisado")
                    self.assertEqual(request_json["metadata"]["origem"], "bot")
                    self.assertEqual(
                        request_json["metadata"]["idempotency_key"],
                        f"whatsapp-bot-resposta-{resposta.id}",
                    )
                    audit.assert_called_once()

                    db.expire_all()
                    persistida = db.query(WhatsAppBotResposta).filter_by(id=resposta.id).first()
                    self.assertEqual(persistida.decisao, "sent")
                    self.assertEqual(persistida.feedback, "positivo")
                    self.assertEqual(persistida.texto_enviado, "Texto revisado")
                    self.assertEqual(persistida.enviado_por_id, 42)
                    estado = db.query(WhatsAppBotConversaEstado).filter_by(
                        wa_identity=resposta.wa_identity
                    ).first()
                    self.assertIsNone(estado)  # Aprovar resposta nao assume a conversa.
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_descartar_rascunho_sem_envio_e_idempotente(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    resposta = self._create_draft(db, texto="Descartar")
                    with patch.object(whatsapp_bot, "registrar_auditoria") as audit:
                        primeira = whatsapp_bot.descartar_rascunho(
                            resposta.id, db=db, current_user=self._user(7)
                        )
                        segunda = whatsapp_bot.descartar_rascunho(
                            resposta.id, db=db, current_user=self._user(7)
                        )
                    self.assertFalse(primeira["idempotent"])
                    self.assertTrue(segunda["idempotent"])
                    audit.assert_called_once()
                    db.expire_all()
                    persistida = db.query(WhatsAppBotResposta).filter_by(id=resposta.id).first()
                    self.assertEqual(persistida.decisao, "draft")
                    self.assertEqual(persistida.feedback, "negativo")
                    self.assertIsNone(persistida.texto_enviado)
                    self.assertEqual(persistida.enviado_por_id, 7)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_falha_no_node_devolve_rascunho_para_revisao(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    resposta = self._create_draft(db, texto="Tentar depois")
                    with (
                        patch.object(whatsapp_bot.settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://node"),
                        patch.object(whatsapp_bot.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "internal"),
                        patch.object(whatsapp_bot.httpx, "post", side_effect=RuntimeError("offline")),
                        patch.object(whatsapp_bot, "registrar_auditoria") as audit,
                    ):
                        with self.assertRaises(HTTPException) as raised:
                            whatsapp_bot.enviar_rascunho(
                                resposta.id,
                                whatsapp_bot.WhatsAppBotRespostaEnviarRequest(),
                                db=db,
                                current_user=self._user(42),
                            )

                    self.assertEqual(raised.exception.status_code, 502)
                    audit.assert_not_called()
                    db.expire_all()
                    persistida = db.query(WhatsAppBotResposta).filter_by(id=resposta.id).first()
                    self.assertEqual(persistida.decisao, "draft")
                    self.assertIsNone(persistida.feedback)
                    self.assertIsNone(persistida.texto_enviado)
                    self.assertIsNone(persistida.enviado_por_id)
                finally:
                    db.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
