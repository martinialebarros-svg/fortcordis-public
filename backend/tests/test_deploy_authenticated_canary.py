import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import ExitStack
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


REPO_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_DIR / "scripts" / "deploy_authenticated_canary.py"
SPEC = importlib.util.spec_from_file_location("deploy_authenticated_canary", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar script canary: {SCRIPT_PATH}")
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


class DeployAuthenticatedCanaryValidationTest(unittest.TestCase):
    def test_supabase_session_is_real_and_revoked_even_when_check_fails(self):
        from app.services import supabase_auth
        user = SimpleNamespace(id=1, email="canary@example.invalid")
        identity = {"id": "identity-1"}
        with patch.object(supabase_auth, "find_identity", return_value=identity), \
             patch.object(supabase_auth, "load_app_user", return_value=user), \
             patch.object(supabase_auth, "get_user", return_value=user), \
             patch.object(supabase_auth, "request_auth", side_effect=[
                 {"id": "identity-1", "hashed_token": "one-use"},
                 {"access_token": "temporary-session"},
             ]) as request, patch.object(supabase_auth, "sign_out") as logout:
            with self.assertRaisesRegex(RuntimeError, "check failed"):
                with ExitStack() as cleanup:
                    self.assertEqual(CANARY._supabase_canary_token(None, user, cleanup), "temporary-session")
                    raise RuntimeError("check failed")
            logout.assert_called_once_with("temporary-session")
            self.assertEqual(request.call_args_list[0].args, ("POST", "admin/generate_link"))
            self.assertEqual(request.call_args_list[1].kwargs["body"], {"type": "email", "token_hash": "one-use"})

    def test_supabase_canary_rejects_changed_identity_before_session(self):
        from app.services import supabase_auth
        user = SimpleNamespace(id=1, email="canary@example.invalid")
        with patch.object(supabase_auth, "find_identity", return_value={"id": "expected"}), \
             patch.object(supabase_auth, "load_app_user", return_value=user), \
             patch.object(supabase_auth, "request_auth", return_value={"id": "other", "hashed_token": "one-use"}) as request:
            with ExitStack() as cleanup, self.assertRaisesRegex(RuntimeError, "inconsistente"):
                CANARY._supabase_canary_token(None, user, cleanup)
            self.assertEqual(request.call_count, 1)

    def test_validate_admin_payload_ok(self) -> None:
        payload = {
            "runtime": {
                "ready": True,
                "observability": {
                    "http_5xx_monitor": {"alert_active": False},
                    "upload_dedupe_cleanup_worker": {
                        "enabled": True,
                        "status": "running",
                        "thread_alive": True,
                    },
                },
            }
        }
        self.assertEqual(CANARY._validate_admin_payload(payload), [])

    def test_validate_admin_payload_flags_unhealthy_signals(self) -> None:
        payload = {
            "runtime": {
                "ready": False,
                "observability": {
                    "http_5xx_monitor": {"alert_active": True},
                    "upload_dedupe_cleanup_worker": {
                        "enabled": True,
                        "status": "stopped",
                        "thread_alive": False,
                    },
                },
            }
        }
        errors = CANARY._validate_admin_payload(payload)
        self.assertTrue(any("runtime.ready" in item for item in errors))
        self.assertTrue(any("alert_active=true" in item for item in errors))
        self.assertTrue(any("status invalido" in item for item in errors))
        self.assertTrue(any("thread_alive=false" in item for item in errors))

    def test_validate_admin_payload_accepts_external_worker(self) -> None:
        payload = {
            "runtime": {
                "ready": True,
                "environment": {"background_workers_managed_externally": True},
                "observability": {
                    "http_5xx_monitor": {"alert_active": False},
                    "upload_dedupe_cleanup_worker": {
                        "enabled": True,
                        "status": "stopped",
                        "thread_alive": False,
                    },
                },
            }
        }
        self.assertEqual(CANARY._validate_admin_payload(payload), [])

    def test_validate_agenda_payload_requires_items_list(self) -> None:
        self.assertEqual(CANARY._validate_agenda_payload({"items": []}), [])
        errors = CANARY._validate_agenda_payload({"items": "nao-lista"})
        self.assertTrue(any("items" in item for item in errors))

    def test_http_401_e_403_nao_sao_sucesso_de_canario(self) -> None:
        self.assertEqual(CANARY._validate_success_status(200), [])
        self.assertTrue(any("401" in item for item in CANARY._validate_success_status(401)))
        self.assertTrue(any("403" in item for item in CANARY._validate_success_status(403)))

    def test_latencia_da_agenda_reprova_p95_acima_do_limite(self) -> None:
        errors = CANARY._validate_agenda_latency(
            [100.0, 110.0, 120.0, 130.0, 1500.0],
            expected_samples=5,
            max_p95_ms=1200.0,
        )
        self.assertTrue(any("p95=1500.00ms" in item for item in errors))

    def test_latencia_da_agenda_exige_todas_as_amostras(self) -> None:
        errors = CANARY._validate_agenda_latency(
            [100.0, 110.0, 120.0, 130.0],
            expected_samples=5,
            max_p95_ms=1200.0,
        )
        self.assertTrue(any("4/5" in item for item in errors))

    def test_canario_mede_cinco_leituras_autenticadas_da_agenda(self) -> None:
        original_http_json = CANARY._http_json
        original_monotonic = CANARY.time.monotonic
        instantes = iter([0.0, 0.1, 1.0, 1.2, 2.0, 2.3, 3.0, 3.4, 4.0, 4.5])
        try:
            CANARY._http_json = lambda *_args, **_kwargs: (200, {"items": []})
            CANARY.time.monotonic = lambda: next(instantes)
            errors = CANARY._run_agenda_latency_canary(
                SimpleNamespace(
                    base_url="http://canary.local",
                    timeout_seconds=8,
                    agenda_latency_samples=5,
                    agenda_max_p95_ms=600.0,
                    expected_release_id="abc1234",
                ),
                {"Authorization": "Bearer token"},
            )
        finally:
            CANARY._http_json = original_http_json
            CANARY.time.monotonic = original_monotonic

        self.assertEqual(errors, [])

    def test_deploy_propaga_limite_e_release_para_o_canario(self) -> None:
        deploy_script = (REPO_DIR / "scripts" / "deploy_prod_vps.sh").read_text(encoding="utf-8")
        self.assertIn("AUTH_CANARY_AGENDA_LATENCY_SAMPLES", deploy_script)
        self.assertIn("AUTH_CANARY_AGENDA_MAX_P95_MS", deploy_script)
        self.assertIn("--agenda-latency-samples", deploy_script)
        self.assertIn("--agenda-max-p95-ms", deploy_script)
        self.assertIn("--expected-release-id", deploy_script)

    def test_validate_cleanup_status_payload_requires_expected_keys(self) -> None:
        payload = {
            "last_status": "ok",
            "consecutive_failures": 0,
            "alert_active": False,
        }
        self.assertEqual(CANARY._validate_cleanup_status_payload(payload), [])

        errors = CANARY._validate_cleanup_status_payload({"last_status": "ok"})
        self.assertTrue(any("consecutive_failures" in item for item in errors))
        self.assertTrue(any("alert_active" in item for item in errors))

    def test_validate_assistente_ia_status_payload_ok(self) -> None:
        payload = {
            "enabled": True,
            "configured": True,
            "admin_only": True,
            "model": "gpt-5.6-sol",
        }
        self.assertEqual(CANARY._validate_assistente_ia_status_payload(payload), [])

    def test_validate_assistente_ia_status_payload_flags_blockers(self) -> None:
        errors = CANARY._validate_assistente_ia_status_payload(
            {
                "enabled": False,
                "configured": False,
                "admin_only": False,
                "model": "",
            }
        )
        self.assertEqual(len(errors), 4)
        self.assertTrue(any("credencial" in item for item in errors))
        self.assertTrue(any("admin_only" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
