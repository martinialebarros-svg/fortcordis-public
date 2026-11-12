import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "upload-dedupe-cleanup-service-test-secret-key-1234567890")

from app.models.atendimento_clinico import UploadDedupeCleanupRun, UploadDedupeMetrica
from app.services import upload_dedupe_cleanup_service


class UploadDedupeCleanupServiceTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "upload-dedupe-cleanup-service-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        UploadDedupeMetrica.__table__.create(engine, checkfirst=True)
        UploadDedupeCleanupRun.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _patch_cleanup_settings(self, **overrides):
        defaults = {
            "UPLOAD_DEDUPE_METRICS_AUTOCLEAN_ENABLED": True,
            "UPLOAD_DEDUPE_METRICS_AUTOCLEAN_INTERVAL_HOURS": 24,
            "UPLOAD_DEDUPE_METRICS_RETENTION_DAYS": 90,
            "UPLOAD_DEDUPE_METRICS_AUTOCLEAN_TIMEOUT_SECONDS": 120,
            "UPLOAD_DEDUPE_METRICS_AUTOCLEAN_STARTUP_JITTER_SECONDS": 0,
            "UPLOAD_DEDUPE_METRICS_CLEANUP_BATCH_SIZE": 1000,
            "UPLOAD_DEDUPE_CLEANUP_RUNS_RETENTION_DAYS": 90,
        }
        defaults.update(overrides)

        stack = ExitStack()
        for key, value in defaults.items():
            stack.enter_context(patch.object(upload_dedupe_cleanup_service.settings, key, value))
        return stack

    def test_run_manual_cleanup_deletes_only_old_metrics_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add_all(
                        [
                            UploadDedupeMetrica(
                                atendimento_id=10,
                                clinica_id=1,
                                evento="upload_novo",
                                dedupe_key="k1",
                                created_at=datetime.now(timezone.utc) - timedelta(days=120),
                            ),
                            UploadDedupeMetrica(
                                atendimento_id=11,
                                clinica_id=1,
                                evento="upload_novo",
                                dedupe_key="k2",
                                created_at=datetime.now(timezone.utc) - timedelta(days=3),
                            ),
                        ]
                    )
                    db.commit()
                finally:
                    db.close()

                with patch.object(upload_dedupe_cleanup_service, "SessionLocal", SessionFactory):
                    with self._patch_cleanup_settings(
                        UPLOAD_DEDUPE_METRICS_RETENTION_DAYS=30,
                        UPLOAD_DEDUPE_METRICS_CLEANUP_BATCH_SIZE=100,
                    ):
                        payload = upload_dedupe_cleanup_service.run_upload_dedupe_cleanup(
                            executor=upload_dedupe_cleanup_service.UPLOAD_DEDUPE_CLEANUP_EXECUTOR_MANUAL
                        )

                self.assertEqual(payload["status"], "success")
                self.assertEqual(payload["deleted_rows"], 1)

                verify = SessionFactory()
                try:
                    metricas = verify.query(UploadDedupeMetrica).all()
                    self.assertEqual(len(metricas), 1)
                    self.assertEqual(metricas[0].atendimento_id, 11)

                    runs = verify.query(UploadDedupeCleanupRun).all()
                    self.assertEqual(len(runs), 1)
                    self.assertEqual(runs[0].executor, "manual")
                    self.assertEqual(runs[0].status, "success")
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_run_manual_cleanup_raises_busy_when_lock_is_held(self) -> None:
        acquired = upload_dedupe_cleanup_service._LOCAL_CLEANUP_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            with self.assertRaises(upload_dedupe_cleanup_service.UploadDedupeCleanupBusyError):
                upload_dedupe_cleanup_service.run_upload_dedupe_cleanup(
                    executor=upload_dedupe_cleanup_service.UPLOAD_DEDUPE_CLEANUP_EXECUTOR_MANUAL
                )
        finally:
            if upload_dedupe_cleanup_service._LOCAL_CLEANUP_LOCK.locked():
                upload_dedupe_cleanup_service._LOCAL_CLEANUP_LOCK.release()

    def test_get_status_marks_alert_active_on_three_consecutive_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    now = datetime.now(timezone.utc)
                    db.add(
                        UploadDedupeCleanupRun(
                            executor="automatic",
                            status="success",
                            retention_days=90,
                            cutoff_date="2025-12-01",
                            deleted_rows=4,
                            error_message=None,
                            duration_ms=80,
                            started_at=now - timedelta(hours=4),
                            finished_at=now - timedelta(hours=4),
                            created_at=now - timedelta(hours=4),
                        )
                    )
                    for idx in range(3):
                        ts = now - timedelta(hours=3 - idx)
                        db.add(
                            UploadDedupeCleanupRun(
                                executor="automatic",
                                status="error",
                                retention_days=90,
                                cutoff_date="2025-12-01",
                                deleted_rows=0,
                                error_message="falha",
                                duration_ms=50,
                                started_at=ts,
                                finished_at=ts,
                                created_at=ts,
                            )
                        )
                    db.commit()
                finally:
                    db.close()

                with patch.object(upload_dedupe_cleanup_service, "SessionLocal", SessionFactory):
                    payload = upload_dedupe_cleanup_service.get_upload_dedupe_cleanup_status()

                self.assertEqual(payload["last_status"], "error")
                self.assertEqual(payload["consecutive_failures"], 3)
                self.assertTrue(payload["alert_active"])
                self.assertIsNotNone(payload["last_success_at"])
            finally:
                engine.dispose()

    def test_maybe_run_automatic_cleanup_maps_execution_error(self) -> None:
        with patch.object(
            upload_dedupe_cleanup_service,
            "run_upload_dedupe_cleanup",
            side_effect=upload_dedupe_cleanup_service.UploadDedupeCleanupExecutionError("boom"),
        ):
            payload = upload_dedupe_cleanup_service.maybe_run_automatic_upload_dedupe_cleanup()

        self.assertFalse(payload["executed"])
        self.assertEqual(payload["reason"], "error")

    def test_run_automatic_cleanup_respects_interval_not_reached(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    now = datetime.now(timezone.utc)
                    db.add(
                        UploadDedupeCleanupRun(
                            executor="automatic",
                            status="success",
                            retention_days=90,
                            cutoff_date="2025-12-01",
                            deleted_rows=1,
                            error_message=None,
                            duration_ms=60,
                            started_at=now,
                            finished_at=now,
                            created_at=now,
                        )
                    )
                    db.commit()
                finally:
                    db.close()

                with patch.object(upload_dedupe_cleanup_service, "SessionLocal", SessionFactory):
                    with self._patch_cleanup_settings(
                        UPLOAD_DEDUPE_METRICS_AUTOCLEAN_ENABLED=True,
                        UPLOAD_DEDUPE_METRICS_AUTOCLEAN_INTERVAL_HOURS=24,
                    ):
                        payload = upload_dedupe_cleanup_service.run_upload_dedupe_cleanup(
                            executor=upload_dedupe_cleanup_service.UPLOAD_DEDUPE_CLEANUP_EXECUTOR_AUTOMATIC
                        )

                self.assertFalse(payload["executed"])
                self.assertEqual(payload["reason"], "interval_not_reached")

                verify = SessionFactory()
                try:
                    self.assertEqual(verify.query(UploadDedupeCleanupRun).count(), 1)
                finally:
                    verify.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
