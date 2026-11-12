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
os.environ.setdefault("SECRET_KEY", "push-scheduler-service-test-secret-key-1234567890")

from app.models.push_scheduled_notification import PushScheduledNotification
from app.services import push_scheduler_service


class PushSchedulerServiceTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "push-scheduler-service-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        PushScheduledNotification.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def test_run_due_once_processes_up_to_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    now = datetime.now(timezone.utc)
                    for idx in range(3):
                        db.add(
                            PushScheduledNotification(
                                kind=push_scheduler_service.PUSH_SCHEDULE_KIND_PENDING_OS,
                                status=push_scheduler_service.PUSH_SCHEDULE_STATUS_PENDING,
                                module="financeiro",
                                action="payment_pending",
                                resource_type="ordem_servico",
                                resource_id=idx + 1,
                                send_at=now - timedelta(minutes=1),
                                attempts=0,
                            )
                        )
                    db.commit()
                finally:
                    db.close()

                def _mark_sent(_db, row):
                    push_scheduler_service._mark_row_processed(
                        row,
                        status=push_scheduler_service.PUSH_SCHEDULE_STATUS_SENT,
                    )

                with patch.object(push_scheduler_service, "SessionLocal", SessionFactory):
                    with patch.object(
                        push_scheduler_service,
                        "_scheduler_distributed_lock_enabled",
                        return_value=False,
                    ):
                        with patch.object(
                            push_scheduler_service,
                            "_process_pending_os_row",
                            side_effect=_mark_sent,
                        ):
                            payload = push_scheduler_service.run_push_scheduler_due_once(limit=2)

                self.assertEqual(payload["processed"], 2)
                self.assertEqual(payload["sent"], 2)
                self.assertEqual(payload["cancelled"], 0)
                self.assertEqual(payload["errors"], 0)

                verify = SessionFactory()
                try:
                    sent_count = (
                        verify.query(PushScheduledNotification)
                        .filter(
                            PushScheduledNotification.status
                            == push_scheduler_service.PUSH_SCHEDULE_STATUS_SENT
                        )
                        .count()
                    )
                    pending_count = (
                        verify.query(PushScheduledNotification)
                        .filter(
                            PushScheduledNotification.status
                            == push_scheduler_service.PUSH_SCHEDULE_STATUS_PENDING
                        )
                        .count()
                    )
                    self.assertEqual(sent_count, 2)
                    self.assertEqual(pending_count, 1)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_run_due_once_skips_cycle_when_distributed_lock_is_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(
                        PushScheduledNotification(
                            kind=push_scheduler_service.PUSH_SCHEDULE_KIND_PENDING_OS,
                            status=push_scheduler_service.PUSH_SCHEDULE_STATUS_PENDING,
                            module="financeiro",
                            action="payment_pending",
                            resource_type="ordem_servico",
                            resource_id=42,
                            send_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                            attempts=0,
                        )
                    )
                    db.commit()
                finally:
                    db.close()

                with patch.object(push_scheduler_service, "SessionLocal", SessionFactory):
                    with patch.object(
                        push_scheduler_service,
                        "_scheduler_distributed_lock_enabled",
                        return_value=True,
                    ):
                        with patch.object(push_scheduler_service, "_is_postgres", return_value=True):
                            with patch.object(
                                push_scheduler_service,
                                "_try_acquire_pg_scheduler_lock",
                                return_value=False,
                            ) as acquire_mock:
                                payload = push_scheduler_service.run_push_scheduler_due_once(limit=50)

                self.assertEqual(payload["processed"], 0)
                self.assertEqual(payload["sent"], 0)
                self.assertEqual(payload["cancelled"], 0)
                self.assertEqual(payload["errors"], 0)
                acquire_mock.assert_called_once()

                verify = SessionFactory()
                try:
                    pending_count = (
                        verify.query(PushScheduledNotification)
                        .filter(
                            PushScheduledNotification.status
                            == push_scheduler_service.PUSH_SCHEDULE_STATUS_PENDING
                        )
                        .count()
                    )
                    self.assertEqual(pending_count, 1)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_fetch_next_due_row_uses_skip_locked_on_postgres(self) -> None:
        now = datetime.now(timezone.utc)
        db = Mock()
        query = Mock()
        locked_query = Mock()

        db.query.return_value = query
        query.filter.return_value = query
        query.order_by.return_value = query
        query.with_for_update.return_value = locked_query
        locked_query.first.return_value = "row"

        with patch.object(push_scheduler_service, "_is_postgres", return_value=True):
            row = push_scheduler_service._fetch_next_due_row(db, now=now)

        self.assertEqual(row, "row")
        query.with_for_update.assert_called_once_with(skip_locked=True)
        locked_query.first.assert_called_once()


if __name__ == "__main__":
    unittest.main()
