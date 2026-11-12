"""Contrato opcional com PostgreSQL LOCAL e banco exclusivo de testes."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlparse

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from app.models.whatsapp_bot import WhatsAppBotJob
from app.services import whatsapp_bot_worker_service as worker


class WhatsAppBotPostgresLockTest(unittest.TestCase):
    def test_lock_distribuido_sobrevive_a_commits_e_e_liberado(self):
        url = os.environ.get("WHATSAPP_BOT_TEST_DATABASE_URL")
        if not url:
            self.skipTest("Defina WHATSAPP_BOT_TEST_DATABASE_URL para banco local de testes")
        parsed = urlparse(url)
        assert parsed.hostname == "127.0.0.1" and "test" in parsed.path
        engine = create_engine(url)
        WhatsAppBotJob.__table__.create(engine, checkfirst=True)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            job = WhatsAppBotJob(wa_identity="5585000000000", conversation_id="lock-test", wa_message_id="wamid.lock-test", status="pending", scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=30))
            db.add(job)
            db.commit()
            job_id = job.id
        lock_key = 80433999
        def process(db, job):
            db.commit()
            with engine.connect() as conn, Session(bind=conn) as competing:
                assert not worker._try_acquire_pg_lock(competing, lock_key=lock_key)
            job.status = "done"
            return "done"
        try:
            with patch.object(worker, "SessionLocal", factory), patch.object(worker, "_distributed_lock_key", return_value=lock_key), patch.object(worker, "_distributed_lock_enabled", return_value=True), patch.object(worker, "_process_job", side_effect=process):
                assert worker.run_whatsapp_bot_worker_due_once(limit=1)["done"] == 1
            with engine.connect() as conn, Session(bind=conn) as competing:
                assert worker._try_acquire_pg_lock(competing, lock_key=lock_key)
                worker._release_pg_lock(competing, lock_key=lock_key)
        finally:
            with factory() as db:
                db.query(WhatsAppBotJob).filter_by(id=job_id).delete()
                db.commit()
            engine.dispose()
