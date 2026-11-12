import os
import sys
import tempfile
import unittest
import json
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-process-job-test-secret-key-1234567890")

from app.models.alerta_interno import AlertaInterno
from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotContextoSelecao
from app.models.whatsapp_bot import WhatsAppBotSolicitacao
from app.models.whatsapp_bot import WhatsAppBotConversaEstado, WhatsAppBotJob, WhatsAppBotResposta
from app.services import whatsapp_bot_gates as gates
from app.services import whatsapp_bot_handoff_service as handoff_service
from app.services import whatsapp_bot_worker_service as worker
from app.services.whatsapp_bot_generation import ResultadoGeracao


def _fake_response(payload):
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value=payload)
    return response


class WhatsAppBotProcessJobTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-process-job-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            WhatsAppBotJob.__table__,
            WhatsAppBotResposta.__table__, WhatsAppBotSolicitacao.__table__,
            WhatsAppBotConversaEstado.__table__,
            WhatsAppBotContextoSelecao.__table__,
            Configuracao.__table__,
            AlertaInterno.__table__,
        ):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _make_job(self, db, *, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.1"):
        job = WhatsAppBotJob(
            wa_identity=wa_identity,
            conversation_id=conversation_id,
            wa_message_id=wa_message_id,
            status="processing",
            scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=5),
            attempts=0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def _enable_bot(self, db):
        db.add(Configuracao(whatsapp_bot_atendimento_habilitado=True))
        db.commit()

    def test_bot_desabilitado_suprime_sem_chamar_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", False):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            job = self._make_job(db)
                            job_id = job.id
                            with patch.object(worker.httpx, "get") as get_mock:
                                result = worker._process_job(db, job)
                                db.commit()
                            get_mock.assert_not_called()
                        finally:
                            db.close()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(result, "done")
                    self.assertEqual(resposta.decisao, "suppressed")
                    self.assertEqual(resposta.motivo, "bot_desabilitado")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_modo_off_por_conversa_suprime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            db.add(WhatsAppBotConversaEstado(wa_identity="558588018899", modo="off"))
                            db.commit()
                            job = self._make_job(db)
                            job_id = job.id
                            with patch.object(worker.httpx, "get") as get_mock:
                                worker._process_job(db, job)
                                db.commit()
                            get_mock.assert_not_called()
                        finally:
                            db.close()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "suppressed")
                    self.assertEqual(resposta.motivo, "modo_off")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_pausa_local_consulta_mensagem_antes_de_suprimir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            db.add(
                                WhatsAppBotConversaEstado(
                                    wa_identity="558588018899",
                                    modo="suggest",
                                    pausado_ate=datetime.now(timezone.utc) + timedelta(hours=1),
                                )
                            )
                            db.commit()
                            job = self._make_job(db)
                            job_id = job.id
                            with patch.object(worker.httpx, "get", side_effect=[_fake_response({"data": [{
                                "id": "conv-1", "last_message_at": datetime.now(timezone.utc).isoformat(),
                                "last_message_body": "oi", "last_message_from_me": False,
                            }]}), _fake_response({"data": []})]) as get_mock, patch.object(worker, "_bot_internal_client_config", return_value=("http://node", {}, 1)):
                                worker._process_job(db, job)
                                db.commit()
                            self.assertEqual(get_mock.call_count, 2)
                        finally:
                            db.close()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "suppressed")
                    self.assertEqual(resposta.motivo, "pausado")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def _run_with_node_mocks(self, db, job, *, conversation_row, message_row):
        """A mensagem atual vem da conversa; o histórico detecta alertas fragmentados."""
        conversation_row = {
            **conversation_row,
            "last_message_body": message_row.get("body"),
            "last_message_from_me": message_row.get("from_me"),
            "last_message_type": message_row.get("type"),
            "last_message_at": message_row.get("created_at") or "2026-08-23T12:00:00+00:00",
        }
        conversations_response = _fake_response({"data": [conversation_row]})
        with patch.object(gates.settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"):
            with patch.object(gates.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "segredo"):
                with patch.object(handoff_service, "send_whatsapp_message_push_notification") as push_mock:
                    with patch.object(handoff_service.httpx, "patch", return_value=_fake_response({})) as patch_mock:
                        with patch.object(worker.httpx, "get", side_effect=[conversations_response, _fake_response({"data": [message_row]})]) as get_mock:
                            result = worker._process_job(db, job)
                            db.commit()
        return result, get_mock, patch_mock, push_mock

    def test_conversa_divergente_suprime_sem_responder(self) -> None:
        """A busca e por telefone; o job carrega a conversa que o originou.

        Se o Node devolver outra conversa para o mesmo telefone, o claim, a
        janela e a ultima mensagem lidos sao de OUTRA conversa. Responder com
        base nisso seria pior do que nao responder.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db, conversation_id="conv-1")
                            job_id = job.id
                            result, _get, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={
                                    "id": "conv-OUTRA",
                                    "wa_phone_number": "558588018899",
                                    "last_agent_id": None,
                                    "last_inbound_at": datetime.now(timezone.utc).isoformat(),
                                },
                                message_row={"wa_message_id": "wamid.x", "from_me": False, "type": "text", "body": "oi"},
                            )
                        finally:
                            db.close()

                self.assertEqual(result, "done")
                patch_mock.assert_not_called()
                push_mock.assert_not_called()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "suppressed")
                    self.assertEqual(resposta.motivo, "conversa_divergente")
                    self.assertIsNone(resposta.texto_gerado)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_claim_detectado_no_node_pausa_e_grava_estado_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            result, get_mock, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": 7, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "oi"},
                            )
                        finally:
                            db.close()

                # Consulta também fragmentos anteriores antes de aplicar a pausa.
                self.assertEqual(get_mock.call_count, 2)
                patch_mock.assert_not_called()
                push_mock.assert_not_called()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "suppressed")
                    self.assertEqual(resposta.motivo, "pausado")
                    estado = verify.query(WhatsAppBotConversaEstado).filter(WhatsAppBotConversaEstado.wa_identity == "558588018899").first()
                    self.assertIsNotNone(estado)
                    self.assertGreater(estado.pausado_ate.replace(tzinfo=timezone.utc), datetime.now(timezone.utc))
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_resposta_humana_from_me_pausa(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            result, get_mock, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": None, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                message_row={"wa_message_id": "wamid.staff", "from_me": True, "type": "text", "body": "Ja te respondo"},
                            )
                        finally:
                            db.close()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "suppressed")
                    self.assertEqual(resposta.motivo, "pausado")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_tipo_nao_suportado_vira_handoff_com_alerta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            result, get_mock, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": None, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "audio", "body": "[audio]"},
                            )
                        finally:
                            db.close()

                patch_mock.assert_called_once()
                push_mock.assert_called_once()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "handoff")
                    self.assertEqual(resposta.motivo, "tipo_nao_suportado")
                    alertas = verify.query(AlertaInterno).count()
                    self.assertEqual(alertas, 1)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_emergencia_dispara_handoff_critico_com_alerta_patch_e_push(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            result, get_mock, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": None, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "meu cachorro nao esta respirando, socorro"},
                            )
                        finally:
                            db.close()

                patch_mock.assert_called_once()
                push_mock.assert_called_once()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "handoff")
                    self.assertEqual(resposta.motivo, "emergencia")
                    self.assertIn("Ligue agora", resposta.texto_gerado)

                    alerta = verify.query(AlertaInterno).first()
                    self.assertIsNotNone(alerta)
                    self.assertEqual(alerta.nivel, "critico")

                    estado = verify.query(WhatsAppBotConversaEstado).filter(WhatsAppBotConversaEstado.wa_identity == "558588018899").first()
                    self.assertEqual(estado.handoff_motivo, "emergencia")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_emergencia_ignora_pausa_e_janela_fechada(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            # last_agent_id preenchido (conversa reivindicada) e
                            # last_inbound_at antigo (janela de 24h fechada) -
                            # mesmo assim a emergencia tem que passar na frente.
                            result, get_mock, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={
                                    "id": "conv-1",
                                    "wa_phone_number": "558588018899",
                                    "last_agent_id": 3,
                                    "last_inbound_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
                                },
                                message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "convulsao agora, o que eu faco"},
                            )
                        finally:
                            db.close()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "handoff")
                    self.assertEqual(resposta.motivo, "emergencia")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_pedido_de_humano_dispara_handoff_com_alerta_patch_e_push(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            result, get_mock, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": None, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "quero falar com um atendente"},
                            )
                        finally:
                            db.close()

                patch_mock.assert_called_once()
                push_mock.assert_called_once()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "handoff")
                    self.assertEqual(resposta.motivo, "pedido_humano")
                    self.assertTrue(resposta.texto_gerado)

                    alerta = verify.query(AlertaInterno).first()
                    self.assertEqual(alerta.nivel, "aviso")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_janela_de_24h_fechada_suprime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            result, get_mock, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={
                                    "id": "conv-1",
                                    "wa_phone_number": "558588018899",
                                    "last_agent_id": None,
                                    "last_inbound_at": (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
                                },
                                message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "oi, ainda esta ai?"},
                            )
                        finally:
                            db.close()

                patch_mock.assert_not_called()
                push_mock.assert_not_called()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "suppressed")
                    self.assertEqual(resposta.motivo, "janela_fechada")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_todos_portoes_abertos_com_identidade_nao_resolvida_vira_handoff(self) -> None:
        """Fase 4: passados os portoes, o job entra na geracao.

        Aqui a identidade nao resolve (a base deste teste nao tem as tabelas
        de cadastro), e RF-016 manda nao mencionar nenhum dado de registro -
        entao o caminho correto e handoff, sem chamar provider nenhum.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            result, get_mock, patch_mock, push_mock = self._run_with_node_mocks(
                                db,
                                job,
                                conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": None, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "qual o horario de funcionamento?"},
                            )
                        finally:
                            db.close()

                patch_mock.assert_called_once()
                push_mock.assert_called_once()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "handoff")
                    self.assertEqual(resposta.motivo, "identidade_indisponivel")
                    self.assertEqual(resposta.resolution, "unavailable")
                    self.assertIsNone(resposta.texto_gerado)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_cortesia_suprime_antes_de_gerar(self) -> None:
        """RF-P11: "Bom dia, obrigada." nao pode consumir LLM.

        Caso real do piloto em producao (2026-08-25): a Vet Plus agradeceu, o
        gerador rodou e o guardrail barrou por `sem_fonte`, gastando 1210
        tokens de entrada e 9,3s para entregar nada - e ainda contando como
        bloqueio na metrica que decide o `auto`.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        with patch.object(worker, "gerar_resposta") as gerar_mock:
                            db = SessionFactory()
                            try:
                                self._enable_bot(db)
                                job = self._make_job(db)
                                job_id = job.id
                                self._run_with_node_mocks(
                                    db,
                                    job,
                                    conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": None, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                    message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "Bom dia, obrigada."},
                                )
                            finally:
                                db.close()

                # NFR-P02: barrar nao custa token.
                gerar_mock.assert_not_called()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "suppressed")
                    self.assertEqual(resposta.motivo, "sem_pergunta")
                    self.assertIsNone(resposta.texto_gerado)
                    self.assertIsNone(resposta.input_tokens)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_convite_novo_pedido_passa_pelo_worker_sem_furar_protecoes(self):
        from app.services.whatsapp_bot_disponibilidade import convidar
        scenarios = [
            ('sim', False, None, 0, 'sent', 'continuidade_administrativa'),
            ('não', False, None, 0, 'sent', 'continuidade_administrativa'),
            ('sim', True, None, 0, 'suppressed', 'pausado'),
            ('sim', False, 3, 0, 'suppressed', 'pausado'),
            ('sim', False, None, 25, 'suppressed', 'janela_fechada'),
            ('sim, meu cachorro está convulsionando', False, None, 0, 'handoff', 'emergencia'),
        ]
        for message, paused, agent, hours, decision, reason in scenarios:
            with self.subTest(message=message, paused=paused, agent=agent, hours=hours), tempfile.TemporaryDirectory() as tmpdir:
                factory, engine = self._build_session_factory(tmpdir)
                try:
                    with factory() as db, ExitStack() as stack:
                        self._enable_bot(db)
                        now = datetime.now(timezone.utc)
                        db.add(WhatsAppBotConversaEstado(wa_identity='558588018899', modo='auto',
                            pausado_ate=now + timedelta(hours=1) if paused else None))
                        pedido = WhatsAppBotSolicitacao(id=1, resposta_id=1, wa_identity='558588018899',
                            conversation_id='conv-1', clinica_id=9, resumo='Pedido anterior', status='cancelado',
                            prazo_em=now, created_at=now, updated_at=now, versao=1, historico='[]')
                        db.add(pedido); db.flush()
                        text, audit = convidar(pedido, 'eco', '558588018899', 9, 'conv-1')
                        db.add(WhatsAppBotResposta(job_id=100, wa_identity='558588018899', conversation_id='conv-1',
                            clinica_id=9, decisao='sent', texto_gerado=text, texto_enviado=text,
                            tools_usadas=json.dumps(audit), created_at=now))
                        db.commit()
                        job = self._make_job(db)
                        stack.enter_context(patch.object(gates.settings, 'WHATSAPP_BOT_ENABLED', True))
                        stack.enter_context(patch.object(gates.settings, 'WHATSAPP_BOT_AUTO_SEND_ENABLED', True))
                        stack.enter_context(patch.object(gates, 'SessionLocal', factory))
                        stack.enter_context(patch('app.services.whatsapp_bot_generation._resolver_contexto',
                            return_value={'resolution':'matched', 'match_type':'clinica', 'clinicas':[{'id':9,'nome':'Teste'}]}))
                        stack.enter_context(patch('app.services.whatsapp_bot_generation.resolve_modo_efetivo', return_value=('auto',None)))
                        provider = stack.enter_context(patch('app.services.whatsapp_bot_generation.get_whatsapp_bot_reply_provider'))
                        def delivered(_db, _job, resposta):
                            resposta.decisao = 'sent'
                            resposta.texto_enviado = resposta.texto_gerado
                        deliver = stack.enter_context(patch.object(worker, 'deliver_automatic_reply', side_effect=delivered))
                        self._run_with_node_mocks(db, job,
                            conversation_row={'id':'conv-1', 'wa_phone_number':'558588018899', 'last_agent_id':agent,
                                              'last_inbound_at':(now-timedelta(hours=hours)).isoformat()},
                            message_row={'wa_message_id':'wamid.1', 'from_me':False, 'type':'text', 'body':message})
                        result = db.query(WhatsAppBotResposta).filter_by(job_id=job.id).one()
                        self.assertEqual((result.decisao, result.motivo), (decision, reason))
                        self.assertEqual(deliver.call_count, int(decision == 'sent'))
                        provider.assert_not_called()
                        self.assertEqual(db.query(WhatsAppBotSolicitacao).count(), 1)
                        self.assertEqual(pedido.status, 'cancelado')
                        self.assertIsNone(pedido.agendamento_id)
                        if message == 'sim' and decision == 'sent':
                            coleta = json.loads(result.tools_usadas)['solicitacao_agendamento']
                            self.assertEqual(coleta['dados'], {'exame':'eco'})
                            self.assertEqual(coleta['status'], 'coletando')
                        if message == 'não':
                            self.assertNotIn('solicitacao_agendamento', json.loads(result.tools_usadas))
                finally:
                    engine.dispose()

    def test_cortesia_com_pergunta_junto_continua_gerando(self) -> None:
        """O portao nao pode engolir pergunta de verdade.

        "obrigada" esta na mensagem, mas ha pergunta - e casamento por
        substring, aqui, seria um bot mudo.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        with patch.object(worker, "gerar_resposta") as gerar_mock:
                            gerar_mock.return_value = ResultadoGeracao(
                                decisao="handoff", motivo="identidade_nao_resolvida"
                            )
                            db = SessionFactory()
                            try:
                                self._enable_bot(db)
                                job = self._make_job(db)
                                job_id = job.id
                                self._run_with_node_mocks(
                                    db,
                                    job,
                                    conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": None, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                    message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "Bom dia, obrigada. Voces fazem ecocardiograma?"},
                                )
                            finally:
                                db.close()

                gerar_mock.assert_called_once()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertNotEqual(resposta.motivo, "sem_pergunta")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_emergencia_vence_cortesia(self) -> None:
        """Ordem dos portoes: emergencia roda antes e nao pode ser mascarada."""
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        # No worker o simbolo e importado direto no namespace
                        # do modulo; patchar em `gates` nao teria efeito nenhum
                        # e o teste passaria sem testar nada.
                        with patch.object(worker, "detecta_cortesia", return_value=True):
                            db = SessionFactory()
                            try:
                                self._enable_bot(db)
                                job = self._make_job(db)
                                job_id = job.id
                                self._run_with_node_mocks(
                                    db,
                                    job,
                                    conversation_row={"id": "conv-1", "wa_phone_number": "558588018899", "last_agent_id": None, "last_inbound_at": datetime.now(timezone.utc).isoformat()},
                                    message_row={"wa_message_id": "wamid.1", "from_me": False, "type": "text", "body": "socorro, meu cachorro esta convulsionando"},
                                )
                            finally:
                                db.close()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job_id).first()
                    self.assertEqual(resposta.decisao, "handoff")
                    self.assertEqual(resposta.motivo, "emergencia")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_resultado_do_gerador_e_persistido_com_auditoria_completa(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
                    with patch.object(gates, "SessionLocal", SessionFactory):
                        db = SessionFactory()
                        try:
                            self._enable_bot(db)
                            job = self._make_job(db)
                            job_id = job.id
                            gerado = ResultadoGeracao(
                                decisao="blocked",
                                motivo="diagnostico",
                                texto_gerado="texto bloqueado",
                                modelo="fake-model",
                                prompt_version="prompt-v1",
                                tools_usadas='{"tools_ok":["consultar_dados_institucionais"]}',
                                input_tokens=120,
                                output_tokens=40,
                                latencia_ms=321,
                                resolution="matched",
                                match_type="tutor",
                            )
                            with patch.object(worker, "gerar_resposta", return_value=gerado):
                                self._run_with_node_mocks(
                                    db,
                                    job,
                                    conversation_row={
                                        "id": "conv-1",
                                        "wa_phone_number": "558588018899",
                                        "last_agent_id": None,
                                        "last_inbound_at": datetime.now(timezone.utc).isoformat(),
                                    },
                                    message_row={
                                        "wa_message_id": "wamid.1",
                                        "from_me": False,
                                        "type": "text",
                                        "body": "mensagem segura para o teste",
                                    },
                                )
                        finally:
                            db.close()

                verify = SessionFactory()
                try:
                    resposta = verify.query(WhatsAppBotResposta).filter_by(job_id=job_id).first()
                    self.assertEqual(resposta.decisao, "blocked")
                    self.assertEqual(resposta.motivo, "diagnostico")
                    self.assertEqual(resposta.texto_gerado, "texto bloqueado")
                    self.assertEqual(resposta.modelo, "fake-model")
                    self.assertEqual(resposta.prompt_version, "prompt-v1")
                    self.assertIn("consultar_dados_institucionais", resposta.tools_usadas)
                    self.assertEqual(resposta.input_tokens, 120)
                    self.assertEqual(resposta.output_tokens, 40)
                    self.assertEqual(resposta.latencia_ms, 321)
                    self.assertEqual(resposta.resolution, "matched")
                    self.assertEqual(resposta.match_type, "tutor")
                finally:
                    verify.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
