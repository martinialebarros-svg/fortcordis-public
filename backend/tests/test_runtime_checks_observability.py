import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "runtime-checks-observability-test-secret-key-1234567890")

from app.core import runtime_checks


class RuntimeChecksObservabilityTest(unittest.TestCase):
    @patch.object(runtime_checks.settings, "FORTCORDIS_PROCESS_ROLE", "all")
    def test_runtime_report_includes_observability_and_warnings(self) -> None:
        with patch.object(runtime_checks, "_check_database", return_value={"connected": True, "status": "connected", "error": None}):
            with patch.object(
                runtime_checks,
                "_check_migrations",
                return_value={
                    "tracking_table_exists": True,
                    "pending_count": 0,
                    "warnings": [],
                },
            ):
                with patch.object(
                    runtime_checks,
                    "_check_secret_key",
                    return_value={"configured": True, "strong": True, "warning": None},
                ):
                    with patch.object(runtime_checks, "get_laudo_pdf_storage_dir", return_value="/tmp/laudos-jobs"):
                        with patch.object(
                            runtime_checks,
                            "get_http_5xx_monitor_status",
                            return_value={
                                "window_minutes": 5,
                                "threshold": 20,
                                "recent_5xx_count": 25,
                                "alert_active": True,
                                "last_5xx_at": "2026-04-05T00:00:00+00:00",
                                "config_warnings": [],
                            },
                        ):
                            with patch.object(
                                runtime_checks,
                                "get_upload_dedupe_cleanup_worker_runtime_state",
                                return_value={
                                    "enabled": True,
                                    "status": "stopped",
                                    "thread_alive": False,
                                    "worker_started": True,
                                    "stop_signal_set": False,
                                    "poll_seconds": 60,
                                    "config_error": None,
                                },
                            ):
                                report = runtime_checks.build_runtime_report()

        self.assertIn("observability", report)
        self.assertIn("http_5xx_monitor", report["observability"])
        self.assertIn("http_latency_monitor", report["observability"])
        self.assertIn("upload_dedupe_cleanup_worker", report["observability"])
        self.assertTrue(report["ready"])
        joined_warnings = " | ".join(report["warnings"])
        self.assertIn("erro(s) HTTP 5xx", joined_warnings)
        self.assertIn("worker de auto-cleanup dedupe habilitado, mas inativo".lower(), joined_warnings.lower())

    def test_production_requires_strong_secret_key_by_default(self) -> None:
        with patch.object(runtime_checks.settings, "APP_ENV", "production"):
            with patch.object(runtime_checks.settings, "ENFORCE_STRONG_SECRET_KEY_IN_PRODUCTION", True):
                with patch.object(
                    runtime_checks,
                    "_check_database",
                    return_value={"connected": True, "status": "connected", "error": None},
                ):
                    with patch.object(
                        runtime_checks,
                        "_check_migrations",
                        return_value={
                            "tracking_table_exists": True,
                            "pending_count": 0,
                            "warnings": [],
                        },
                    ):
                        with patch.object(
                            runtime_checks,
                            "_check_secret_key",
                            return_value={"configured": True, "strong": False, "warning": "fraca"},
                        ):
                            report = runtime_checks.build_runtime_report()

        self.assertFalse(report["ready"])
        joined_issues = " | ".join(report["startup_enforced_issues"])
        self.assertIn("APP_ENV=production exige SECRET_KEY forte", joined_issues)

    def test_non_production_does_not_fail_without_strong_secret_by_default(self) -> None:
        with patch.object(runtime_checks.settings, "APP_ENV", "development"):
            with patch.object(runtime_checks.settings, "ENFORCE_STRONG_SECRET_KEY_IN_PRODUCTION", True):
                with patch.object(
                    runtime_checks,
                    "_check_database",
                    return_value={"connected": True, "status": "connected", "error": None},
                ):
                    with patch.object(
                        runtime_checks,
                        "_check_migrations",
                        return_value={
                            "tracking_table_exists": True,
                            "pending_count": 0,
                            "warnings": [],
                        },
                    ):
                        with patch.object(
                            runtime_checks,
                            "_check_secret_key",
                            return_value={"configured": True, "strong": False, "warning": "fraca"},
                        ):
                            report = runtime_checks.build_runtime_report()

        self.assertTrue(report["ready"])


if __name__ == "__main__":
    unittest.main()
