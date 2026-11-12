import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "upload-dedupe-metrics-endpoint-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return _FakeResult(self.rows)


class _FakeUser:
    def __init__(self, *, is_admin: bool):
        self.id = 1
        self.nome = "Metrics User"
        self._is_admin = is_admin

    def tem_papel(self, papel_nome: str) -> bool:
        return self._is_admin and str(papel_nome).lower() == "admin"


class UploadDedupeMetricsEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.admin_user = _FakeUser(is_admin=True)
        self.non_admin_user = _FakeUser(is_admin=False)

    def test_consultar_metricas_upload_dedupe_rejects_invalid_start_date(self) -> None:
        db = _FakeDB(rows=[])
        with self.assertRaises(HTTPException) as ctx:
            atendimento.consultar_metricas_upload_dedupe(
                data_inicio="2026-99-01",
                data_fim=None,
                clinica_id=None,
                db=db,
                current_user=self.admin_user,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("data_inicio invalido", str(ctx.exception.detail))

    def test_consultar_metricas_upload_dedupe_rejects_inverted_date_range(self) -> None:
        db = _FakeDB(rows=[])
        with self.assertRaises(HTTPException) as ctx:
            atendimento.consultar_metricas_upload_dedupe(
                data_inicio="2026-04-05",
                data_fim="2026-04-04",
                clinica_id=None,
                db=db,
                current_user=self.admin_user,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("data_inicio", str(ctx.exception.detail))

    def test_consultar_metricas_upload_dedupe_returns_daily_aggregation(self) -> None:
        db = _FakeDB(
            rows=[
                ("2026-04-04", 5, 2, 1, 8),
                ("2026-04-03", 3, 1, 0, 4),
            ]
        )

        payload = atendimento.consultar_metricas_upload_dedupe(
            data_inicio="2026-04-03",
            data_fim="2026-04-04",
            clinica_id=7,
            db=db,
            current_user=self.admin_user,
        )

        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["items"][0]["date"], "2026-04-04")
        self.assertEqual(payload["items"][0]["uploads_novos"], 5)
        self.assertEqual(payload["items"][0]["dedupe_precheck"], 2)
        self.assertEqual(payload["items"][0]["dedupe_collision"], 1)
        self.assertEqual(payload["items"][0]["total_uploads"], 8)
        self.assertEqual(payload["filters"]["clinica_id"], 7)
        self.assertEqual(len(db.calls), 1)

    def test_cleanup_upload_dedupe_metricas_requires_admin(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            atendimento.executar_cleanup_upload_dedupe_metricas(
                current_user=self.non_admin_user,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    @patch("app.api.v1.endpoints.atendimento.run_upload_dedupe_cleanup")
    def test_cleanup_upload_dedupe_metricas_returns_payload_for_admin(self, mock_run) -> None:
        mock_run.return_value = {
            "run_id": 11,
            "executor": "manual",
            "status": "success",
            "retention_days": 90,
            "cutoff_date": "2026-01-04",
            "deleted_rows": 3,
            "duration_ms": 80,
            "consecutive_failures": 0,
        }

        payload = atendimento.executar_cleanup_upload_dedupe_metricas(
            current_user=self.admin_user,
        )

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["deleted_rows"], 3)
        mock_run.assert_called_once_with(executor=atendimento.UPLOAD_DEDUPE_CLEANUP_EXECUTOR_MANUAL)

    @patch("app.api.v1.endpoints.atendimento.run_upload_dedupe_cleanup")
    def test_cleanup_upload_dedupe_metricas_returns_409_when_busy(self, mock_run) -> None:
        mock_run.side_effect = atendimento.UploadDedupeCleanupBusyError("busy lock")

        with self.assertRaises(HTTPException) as ctx:
            atendimento.executar_cleanup_upload_dedupe_metricas(
                current_user=self.admin_user,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("busy lock", str(ctx.exception.detail))

    @patch("app.api.v1.endpoints.atendimento.run_upload_dedupe_cleanup")
    def test_cleanup_upload_dedupe_metricas_returns_500_on_execution_error(self, mock_run) -> None:
        mock_run.side_effect = atendimento.UploadDedupeCleanupExecutionError("cleanup failed")

        with self.assertRaises(HTTPException) as ctx:
            atendimento.executar_cleanup_upload_dedupe_metricas(
                current_user=self.admin_user,
            )

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("cleanup failed", str(ctx.exception.detail))

    def test_status_cleanup_upload_dedupe_metricas_requires_admin(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            atendimento.consultar_status_cleanup_upload_dedupe_metricas(
                current_user=self.non_admin_user,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    @patch("app.api.v1.endpoints.atendimento.get_upload_dedupe_cleanup_status")
    def test_status_cleanup_upload_dedupe_metricas_returns_payload_for_admin(self, mock_status) -> None:
        mock_status.return_value = {
            "last_run_id": 20,
            "last_run_at": "2026-04-04T23:40:00",
            "last_success_at": "2026-04-04T23:40:00",
            "last_status": "success",
            "last_deleted_rows": 2,
            "last_cutoff_date": "2026-01-04",
            "last_error": None,
            "last_duration_ms": 101,
            "consecutive_failures": 0,
            "alert_active": False,
        }

        payload = atendimento.consultar_status_cleanup_upload_dedupe_metricas(
            current_user=self.admin_user,
        )

        self.assertEqual(payload["last_status"], "success")
        self.assertFalse(payload["alert_active"])
        mock_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
