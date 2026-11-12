import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-queue-test-secret-key-1234567890")

from app.models.whatsapp_bot import WhatsAppBotJob
from app.services import whatsapp_bot_queue_service as queue_service


class WhatsAppBotQueueServiceTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-queue-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        WhatsAppBotJob.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def test_enqueue_cria_job_pending_com_debounce(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    now = datetime.now(timezone.utc)
                    created = queue_service.enqueue_job_for_inbound_message(
                        db,
                        wa_identity="558588018899",
                        conversation_id="conv-1",
                        wa_message_id="wamid.1",
                        now=now,
                    )
                    self.assertTrue(created)

                    job = db.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "wamid.1").first()
                    self.assertIsNotNone(job)
                    self.assertEqual(job.status, "pending")
                    self.assertEqual(job.attempts, 0)
                    expected_scheduled_for = now + timedelta(seconds=12)
                    self.assertAlmostEqual(
                        job.scheduled_for.replace(tzinfo=timezone.utc).timestamp(),
                        expected_scheduled_for.timestamp(),
                        delta=1,
                    )
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_reentrega_do_mesmo_wa_message_id_nao_cria_segundo_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.dup",
                    )
                    created_again = queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.dup",
                    )
                    self.assertFalse(created_again)

                    count = (
                        db.query(WhatsAppBotJob)
                        .filter(WhatsAppBotJob.wa_message_id == "wamid.dup")
                        .count()
                    )
                    self.assertEqual(count, 1)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_mensagem_nova_supersede_job_pending_anterior_da_mesma_conversa(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.1",
                    )
                    queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.2",
                    )
                    queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.3",
                    )

                    jobs = (
                        db.query(WhatsAppBotJob)
                        .filter(WhatsAppBotJob.wa_identity == "558588018899")
                        .order_by(WhatsAppBotJob.id.asc())
                        .all()
                    )
                    self.assertEqual(len(jobs), 3)
                    self.assertEqual(jobs[0].status, "superseded")
                    self.assertEqual(jobs[1].status, "superseded")
                    self.assertEqual(jobs[2].status, "pending")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_job_em_processing_nao_e_superseded_cb001(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.1",
                    )
                    em_processamento = db.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "wamid.1").first()
                    em_processamento.status = "processing"
                    db.commit()

                    queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.2",
                    )

                    db.refresh(em_processamento)
                    self.assertEqual(em_processamento.status, "processing")

                    novo = db.query(WhatsAppBotJob).filter(WhatsAppBotJob.wa_message_id == "wamid.2").first()
                    self.assertEqual(novo.status, "pending")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_conversas_diferentes_nao_se_afetam(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558588018899", conversation_id="conv-1", wa_message_id="wamid.1",
                    )
                    queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="558511122334", conversation_id="conv-2", wa_message_id="wamid.2",
                    )

                    jobs = db.query(WhatsAppBotJob).filter(WhatsAppBotJob.status == "pending").all()
                    self.assertEqual(len(jobs), 2)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_payload_incompleto_nao_cria_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    created = queue_service.enqueue_job_for_inbound_message(
                        db, wa_identity="", conversation_id="conv-1", wa_message_id="wamid.1",
                    )
                    self.assertFalse(created)
                    self.assertEqual(db.query(WhatsAppBotJob).count(), 0)
                finally:
                    db.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
