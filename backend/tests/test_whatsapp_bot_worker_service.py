import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-worker-test-secret-key-1234567890")

from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotSolicitacao
from app.models.whatsapp_bot import WhatsAppBotJob, WhatsAppBotResposta
from app.services import whatsapp_bot_queue_service as queue_service
from app.services import whatsapp_bot_worker_service as worker


class WhatsAppBotWorkerServiceTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-worker-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        WhatsAppBotJob.__table__.create(engine, checkfirst=True)
        WhatsAppBotSolicitacao.__table__.create(engine, checkfirst=True)
        WhatsAppBotResposta.__table__.create(engine, checkfirst=True)
        Configuracao.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def test_run_due_once_processa_job_pending_e_grava_resposta_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db,
                        wa_identity="558588018899",
                        conversation_id="conv-1",
                        wa_message_id="wamid.1",
                        now=datetime.now(timezone.utc) - timedelta(seconds=30),
                    )
                finally:
                    db.close()

                with patch.object(worker, "SessionLocal", SessionFactory):
                    with patch.object(worker, "_distributed_lock_enabled", return_value=False):
                        payload = worker.run_whatsapp_bot_worker_due_once(limit=10)

                self.assertEqual(payload, {"processed": 1, "done": 1, "errors": 0})

                verify = SessionFactory()
                try:
                    job = verify.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "wamid.1").first()
                    self.assertEqual(job.status, "done")
                    resposta = verify.query(WhatsAppBotResposta).filter(WhatsAppBotResposta.job_id == job.id).first()
                    self.assertIsNotNone(resposta)
                    self.assertEqual(resposta.decisao, "suppressed")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_run_due_once_nao_toca_job_ainda_nao_devido(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db,
                        wa_identity="558588018899",
                        conversation_id="conv-1",
                        wa_message_id="wamid.futuro",
                        now=datetime.now(timezone.utc),
                    )
                finally:
                    db.close()

                with patch.object(worker, "SessionLocal", SessionFactory):
                    with patch.object(worker, "_distributed_lock_enabled", return_value=False):
                        payload = worker.run_whatsapp_bot_worker_due_once(limit=10)

                self.assertEqual(payload, {"processed": 0, "done": 0, "errors": 0})
            finally:
                engine.dispose()

    def test_falha_incrementa_attempts_e_grava_last_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db,
                        wa_identity="558588018899",
                        conversation_id="conv-1",
                        wa_message_id="wamid.erro",
                        now=datetime.now(timezone.utc) - timedelta(seconds=30),
                    )
                finally:
                    db.close()

                with patch.object(worker, "SessionLocal", SessionFactory):
                    with patch.object(worker, "_distributed_lock_enabled", return_value=False):
                        with patch.object(worker, "_process_job", side_effect=RuntimeError("boom")):
                            payload = worker.run_whatsapp_bot_worker_due_once(limit=10)

                self.assertEqual(payload, {"processed": 1, "done": 0, "errors": 1})

                verify = SessionFactory()
                try:
                    job = verify.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "wamid.erro").first()
                    self.assertEqual(job.attempts, 1)
                    self.assertIn("boom", job.last_error)
                    self.assertEqual(job.status, "pending")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_falha_nao_vaza_telefone_em_log_nem_last_error(self) -> None:
        telefone = "558588018899"
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db,
                        wa_identity=telefone,
                        conversation_id="conv-pii",
                        wa_message_id="wamid.pii",
                        now=datetime.now(timezone.utc) - timedelta(seconds=30),
                    )
                finally:
                    db.close()

                erro = RuntimeError(
                    f"GET http://127.0.0.1:3010/conversations?phone={telefone}&limit=1 falhou"
                )
                with self.assertLogs(worker.logger.name, level="ERROR") as captured:
                    with patch.object(worker, "SessionLocal", SessionFactory):
                        with patch.object(worker, "_distributed_lock_enabled", return_value=False):
                            with patch.object(worker, "_process_job", side_effect=erro):
                                payload = worker.run_whatsapp_bot_worker_due_once(limit=10)

                self.assertEqual(payload, {"processed": 1, "done": 0, "errors": 1})
                logs = "\n".join(captured.output)
                self.assertNotIn(telefone, logs)
                self.assertIn("[REDACTED]", logs)

                verify = SessionFactory()
                try:
                    job = verify.query(WhatsAppBotJob).filter_by(wa_message_id="wamid.pii").first()
                    self.assertNotIn(telefone, job.last_error or "")
                    self.assertIn("[REDACTED]", job.last_error or "")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_job_para_de_ser_reprocessado_ao_esgotar_tentativas(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db,
                        wa_identity="558588018899",
                        conversation_id="conv-1",
                        wa_message_id="wamid.esgotado",
                        now=datetime.now(timezone.utc) - timedelta(seconds=30),
                    )
                finally:
                    db.close()

                with patch.object(worker, "SessionLocal", SessionFactory):
                    with patch.object(worker, "_distributed_lock_enabled", return_value=False):
                        with patch.object(worker, "_max_attempts", return_value=2), patch.object(worker, "_handoff_operacional"):
                            # poll_seconds=0 simula a passagem de um ciclo entre cada
                            # chamada, sem depender do relogio real do teste.
                            with patch.object(worker, "_worker_poll_seconds", return_value=0):
                                with patch.object(worker, "_process_job", side_effect=RuntimeError("boom")):
                                    worker.run_whatsapp_bot_worker_due_once(limit=10)
                                    worker.run_whatsapp_bot_worker_due_once(limit=10)
                                    # 3a chamada: job ja tem attempts=2 (>= max), nao deve ser buscado de novo.
                                    payload = worker.run_whatsapp_bot_worker_due_once(limit=10)

                self.assertEqual(payload, {"processed": 0, "done": 0, "errors": 0})

                verify = SessionFactory()
                try:
                    job = verify.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "wamid.esgotado").first()
                    self.assertEqual(job.attempts, 2)
                    self.assertEqual(job.status, "error")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_run_due_once_pula_ciclo_com_lock_distribuido_ocupado(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db,
                        wa_identity="558588018899",
                        conversation_id="conv-1",
                        wa_message_id="wamid.lock",
                        now=datetime.now(timezone.utc) - timedelta(seconds=30),
                    )
                finally:
                    db.close()

                with patch.object(worker, "SessionLocal", SessionFactory):
                    with patch.object(worker, "_distributed_lock_enabled", return_value=True):
                        with patch.object(worker, "_is_postgres", return_value=True):
                            with patch.object(worker, "_try_acquire_pg_lock", return_value=False) as acquire_mock:
                                payload = worker.run_whatsapp_bot_worker_due_once(limit=10)

                self.assertEqual(payload, {"processed": 0, "done": 0, "errors": 0})
                acquire_mock.assert_called_once()

                verify = SessionFactory()
                try:
                    job = verify.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "wamid.lock").first()
                    self.assertEqual(job.status, "pending")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    # is_whatsapp_bot_enabled agora vive em whatsapp_bot_gates (RF-008) - ver
    # test_whatsapp_bot_gates.test_is_whatsapp_bot_enabled_exige_env_e_banco.
    # worker.is_whatsapp_bot_enabled continua disponivel (reexportado), so nao
    # e mais testado aqui para nao duplicar o teste com um SessionLocal errado.

    def test_reconciliation_enfileira_ultima_mensagem_inbound_sem_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                now_iso = datetime.now(timezone.utc).isoformat()

                conversations_response = Mock()
                conversations_response.raise_for_status = Mock()
                conversations_response.json = Mock(return_value={
                    "data": [
                        {"id": "conv-1", "wa_phone_number": "558588018899", "last_inbound_at": now_iso},
                    ]
                })

                messages_response = Mock()
                messages_response.raise_for_status = Mock()
                messages_response.json = Mock(return_value={
                    "data": [
                        {"wa_message_id": "wamid.reconciliado", "from_me": False, "type": "text", "created_at": now_iso},
                    ]
                })

                with patch.object(worker.settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"):
                    with patch.object(worker.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "segredo"):
                        with patch.object(worker.httpx, "get", side_effect=[conversations_response, messages_response]) as get_mock:
                            db = SessionFactory()
                            try:
                                result = worker.run_reconciliation_sweep(db)
                            finally:
                                db.close()

                self.assertEqual(result, {"checked": 1, "enqueued": 1})
                self.assertEqual(get_mock.call_count, 2)

                verify = SessionFactory()
                try:
                    job = verify.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "wamid.reconciliado").first()
                    self.assertIsNotNone(job)
                    self.assertEqual(job.wa_identity, "558588018899")
                    self.assertEqual(job.conversation_id, "conv-1")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_reconciliation_pega_a_ultima_pagina_em_conversa_longa(self) -> None:
        """Regressao: `/conversations/:id/messages` e ASC paginado.

        A versao anterior pedia `page=1&limit=200` e usava `rows[-1]`, ou seja,
        em conversa com mais de 200 mensagens pegava a 200a mais ANTIGA e
        tratava como se fosse a ultima. Aqui a conversa tem 350 mensagens: a
        certa esta na pagina 350, e a primeira pagina traz uma isca antiga.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                now_iso = datetime.now(timezone.utc).isoformat()

                conversations_response = Mock()
                conversations_response.raise_for_status = Mock()
                conversations_response.json = Mock(return_value={
                    "data": [
                        {"id": "conv-1", "wa_phone_number": "558588018899", "last_inbound_at": now_iso},
                    ]
                })

                primeira_pagina = Mock()
                primeira_pagina.raise_for_status = Mock()
                primeira_pagina.json = Mock(return_value={
                    "data": [{"wa_message_id": "wamid.ANTIGA", "from_me": False, "type": "text"}],
                    "pagination": {"page": 1, "limit": 1, "total": 350},
                })

                ultima_pagina = Mock()
                ultima_pagina.raise_for_status = Mock()
                ultima_pagina.json = Mock(return_value={
                    "data": [{"wa_message_id": "wamid.RECENTE", "from_me": False, "type": "text", "created_at": now_iso}],
                    "pagination": {"page": 350, "limit": 1, "total": 350},
                })

                with patch.object(worker.settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"):
                    with patch.object(worker.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "segredo"):
                        with patch.object(
                            worker.httpx,
                            "get",
                            side_effect=[conversations_response, primeira_pagina, ultima_pagina],
                        ) as get_mock:
                            db = SessionFactory()
                            try:
                                result = worker.run_reconciliation_sweep(db)
                            finally:
                                db.close()

                self.assertEqual(result, {"checked": 1, "enqueued": 1})
                # A ultima chamada tem que pedir a pagina 350, nao a 1.
                self.assertEqual(get_mock.call_args_list[-1].kwargs["params"], {"limit": 1, "page": 350, "bot_context": "true"})

                verify = SessionFactory()
                try:
                    self.assertIsNotNone(
                        verify.query(WhatsAppBotJob)
                        .filter(WhatsAppBotJob.wa_message_id == "wamid.RECENTE")
                        .first()
                    )
                    self.assertIsNone(
                        verify.query(WhatsAppBotJob)
                        .filter(WhatsAppBotJob.wa_message_id == "wamid.ANTIGA")
                        .first(),
                        "enfileirou a mensagem antiga da primeira pagina",
                    )
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_reconciliation_ignora_conversa_cuja_ultima_mensagem_e_from_me(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                now_iso = datetime.now(timezone.utc).isoformat()

                conversations_response = Mock()
                conversations_response.raise_for_status = Mock()
                conversations_response.json = Mock(return_value={
                    "data": [
                        {"id": "conv-1", "wa_phone_number": "558588018899", "last_inbound_at": now_iso},
                    ]
                })
                messages_response = Mock()
                messages_response.raise_for_status = Mock()
                messages_response.json = Mock(return_value={
                    "data": [
                        {"wa_message_id": "wamid.staff", "from_me": True, "type": "text"},
                    ]
                })

                with patch.object(worker.settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"):
                    with patch.object(worker.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "segredo"):
                        with patch.object(worker.httpx, "get", side_effect=[conversations_response, messages_response]):
                            db = SessionFactory()
                            try:
                                result = worker.run_reconciliation_sweep(db)
                            finally:
                                db.close()

                self.assertEqual(result, {"checked": 1, "enqueued": 0})

                verify = SessionFactory()
                try:
                    self.assertEqual(verify.query(WhatsAppBotJob).count(), 0)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_reconciliation_sem_configuracao_do_servico_node_retorna_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(worker.settings, "WHATSAPP_AGENDA_SERVICE_URL", ""):
                    with patch.object(worker.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", ""):
                        db = SessionFactory()
                        try:
                            result = worker.run_reconciliation_sweep(db)
                        finally:
                            db.close()

                self.assertEqual(result, {"checked": 0, "enqueued": 0})
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
