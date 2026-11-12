import os
import sys
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "admin-hardening-readiness-test-secret-key-1234567890")

from app.api.v1.endpoints import admin


class _FakeAdminUser:
    id = 1
    nome = "Admin Teste"


class AdminHardeningReadinessTest(unittest.TestCase):
    def test_payload_includes_runtime_observability_and_readiness_issues(self) -> None:
        runtime_report = {
            "status": "healthy",
            "ready": True,
            "warnings": [],
            "readiness_issues": [],
            "environment": {
                "process_role": "api",
                "background_workers_managed_externally": True,
            },
            "observability": {
                "http_5xx_monitor": {
                    "window_minutes": 5,
                    "threshold": 20,
                    "recent_5xx_count": 2,
                    "alert_active": False,
                    "last_5xx_at": None,
                    "config_warnings": [],
                },
                "upload_dedupe_cleanup_worker": {
                    "enabled": True,
                    "status": "running",
                    "thread_alive": True,
                    "worker_started": True,
                    "stop_signal_set": False,
                    "poll_seconds": 60,
                    "config_error": None,
                },
            },
        }

        with patch.object(admin, "build_runtime_report", return_value=runtime_report):
            with patch.object(admin, "_avaliar_migracoes", return_value={"safe_to_enable": True, "blockers": [], "details": {}, "current_value": False}):
                with patch.object(admin, "_avaliar_secret_key", return_value={"safe_to_enable": True, "blockers": [], "details": {}, "current_value": False}):
                    with patch.object(admin, "_avaliar_senhas_legadas", return_value={"safe_to_disable": True, "blockers": [], "details": {}, "current_value": True}):
                        with patch.object(admin, "_avaliar_fallback_permissoes", return_value={"safe_to_disable": True, "blockers": [], "details": {}, "current_value": True}):
                            payload = admin.obter_hardening_readiness(
                                current_user=_FakeAdminUser(),
                                db=object(),
                            )

        self.assertIn("runtime", payload)
        self.assertIn("environment", payload["runtime"])
        self.assertIn("observability", payload["runtime"])
        self.assertIn("readiness_issues", payload["runtime"])
        self.assertEqual(
            payload["runtime"]["observability"]["http_5xx_monitor"]["recent_5xx_count"],
            2,
        )
        self.assertTrue(payload["runtime"]["environment"]["background_workers_managed_externally"])

    def test_latency_observability_endpoint_delegates_only_for_an_admin_dependency(self) -> None:
        expected = {"available": True, "groups": []}
        with patch.object(admin, "get_persisted_http_latency_summary", return_value=expected) as summary:
            payload = admin.obter_latencia_http_persistida(
                hours=24,
                current_user=_FakeAdminUser(),
                db=object(),
            )

        self.assertIs(payload, expected)
        summary.assert_called_once_with(ANY, hours=24)
        route = next(
            route
            for route in admin.router.routes
            if getattr(route, "path", "") == "/observability/http-latency"
        )
        self.assertTrue(route.dependant.dependencies)
        role_dependency = route.dependant.dependencies[0].call
        captured_values = [
            cell.cell_contents
            for cell in (getattr(role_dependency, "__closure__", None) or [])
        ]
        self.assertIn("admin", captured_values)

    def test_frontend_observability_summary_is_restricted_to_admin(self) -> None:
        expected = {"available": True, "groups": []}
        with patch.object(admin, "get_frontend_performance_summary", return_value=expected) as summary:
            payload = admin.obter_desempenho_frontend_persistido(
                hours=24,
                current_user=_FakeAdminUser(),
                db=object(),
            )

        self.assertIs(payload, expected)
        summary.assert_called_once_with(ANY, hours=24)
        route = next(
            route
            for route in admin.router.routes
            if getattr(route, "path", "") == "/observability/frontend-performance"
        )
        role_dependency = route.dependant.dependencies[0].call
        captured_values = [
            cell.cell_contents
            for cell in (getattr(role_dependency, "__closure__", None) or [])
        ]
        self.assertIn("admin", captured_values)


if __name__ == "__main__":
    unittest.main()
