import importlib.util
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_DIR / "scripts" / "runtime_observability_gate.py"
SPEC = importlib.util.spec_from_file_location("runtime_observability_gate", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar o runtime gate: {SCRIPT_PATH}")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def health_payload(*, external_workers: bool) -> dict:
    return {
        "readiness": "ready",
        "background_workers_managed_externally": external_workers,
        "checks": {
            "observability": {
                "http_5xx_monitor": {"alert_active": False},
                "upload_dedupe_cleanup_worker": {
                    "enabled": True,
                    "status": "stopped",
                    "thread_alive": False,
                },
            },
        },
    }


class RuntimeObservabilityGateTest(unittest.TestCase):
    def test_accepts_external_worker_without_local_thread(self) -> None:
        self.assertEqual(GATE._validate_health_payload(health_payload(external_workers=True)), [])

    def test_rejects_inactive_worker_when_managed_in_process(self) -> None:
        errors = GATE._validate_health_payload(health_payload(external_workers=False))
        self.assertTrue(any("status diferente de running" in item for item in errors))
        self.assertTrue(any("thread_alive=false" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
