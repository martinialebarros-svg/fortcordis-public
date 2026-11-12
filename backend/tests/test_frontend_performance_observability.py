import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "frontend-performance-test-secret-key-1234567890")

from app.api.v1.endpoints import observability
from app.db import database
from app.models.runtime_frontend_performance_metric import RuntimeFrontendPerformanceMetric
from app.services import frontend_performance

MIGRATION_PATH = (
    BACKEND_DIR
    / "migrations"
    / "versions"
    / "20260930_94_frontend_performance_metrics.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_20260930_94", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


MIGRATION = _load_migration()


class _FakeUser:
    id = 99


class FrontendPerformanceObservabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        frontend_performance.reset_frontend_performance_state_for_tests()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.tmpdir.name) / 'metrics.db'}")
        with self.engine.begin() as connection:
            MIGRATION.upgrade(connection, "sqlite")
            MIGRATION.upgrade(connection, "sqlite")
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.session_patch = patch.object(database, "SessionLocal", self.session_factory)
        self.session_patch.start()

    def tearDown(self) -> None:
        self.session_patch.stop()
        self.engine.dispose()
        self.tmpdir.cleanup()
        frontend_performance.reset_frontend_performance_state_for_tests()

    def test_migration_is_idempotent_and_creates_bounded_indexes(self) -> None:
        inspector = inspect(self.engine)
        self.assertIn("runtime_frontend_performance_metrics", inspector.get_table_names())
        index_names = {
            item["name"]
            for item in inspector.get_indexes("runtime_frontend_performance_metrics")
        }
        self.assertIn("ix_runtime_frontend_performance_created_at", index_names)
        self.assertIn("ix_runtime_frontend_performance_route_release_created", index_names)

    def test_sample_persists_only_safe_fields_and_summary_percentiles(self) -> None:
        payloads = [
            {
                "route_group": "/dashboard",
                "navigation_type": "client",
                "outcome": "ready",
                "shell_ms": 80,
                "content_ms": 200,
            },
            {
                "route_group": "/dashboard",
                "navigation_type": "client",
                "outcome": "partial",
                "shell_ms": 100,
                "content_ms": 4_000,
            },
            {
                "route_group": "/dashboard",
                "navigation_type": "client",
                "outcome": "timeout",
                "shell_ms": 120,
                "content_ms": None,
            },
        ]
        from app.services import runtime_observability
        with patch.object(runtime_observability.settings, "RUNTIME_HTTP_LATENCY_PERSIST_ENABLED", True), patch.object(
            runtime_observability.settings,
            "RUNTIME_HTTP_LATENCY_RELEASE_ID",
            "release-rum-123",
        ):
            samples = [frontend_performance.build_frontend_performance_sample(item) for item in payloads]
            self.assertTrue(all(frontend_performance.persist_frontend_performance_sample(item) for item in samples))

        self.assertEqual(
            set(samples[0]),
            {
                "route_group",
                "release_id",
                "navigation_type",
                "outcome",
                "shell_ms",
                "content_ms",
                "created_at",
            },
        )
        db = self.session_factory()
        try:
            rows = db.query(RuntimeFrontendPerformanceMetric).all()
            summary = frontend_performance.get_frontend_performance_summary(db, hours=24)
        finally:
            db.close()

        self.assertEqual(len(rows), 3)
        self.assertFalse(hasattr(rows[0], "user_id"))
        self.assertTrue(summary["available"])
        self.assertFalse(summary["truncated"])
        group = summary["groups"][0]
        self.assertEqual(group["route_group"], "/dashboard")
        self.assertEqual(group["release_id"], "release-rum-123")
        self.assertEqual(group["sample_count"], 3)
        self.assertEqual(group["shell_p95_ms"], 120.0)
        self.assertEqual(group["content_p50_ms"], 200.0)
        self.assertEqual(group["content_p95_ms"], 4000.0)
        self.assertEqual(group["slow_content_count"], 1)
        self.assertEqual(group["partial_count"], 1)
        self.assertEqual(group["timeout_count"], 1)

    def test_invalid_route_duration_and_content_order_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            frontend_performance.build_frontend_performance_sample({
                "route_group": "/pacientes/42",
                "navigation_type": "client",
                "outcome": "ready",
                "shell_ms": 10,
                "content_ms": 20,
            })
        with self.assertRaises(ValueError):
            frontend_performance.build_frontend_performance_sample({
                "route_group": "/laudos",
                "navigation_type": "client",
                "outcome": "ready",
                "shell_ms": 200,
                "content_ms": 100,
            })
        with self.assertRaises(ValidationError):
            observability.FrontendPerformanceSample(
                route_group="/pacientes",
                navigation_type="client",
                outcome="ready",
                shell_ms=10,
                content_ms=20,
            )
        with self.assertRaises(ValidationError):
            observability.FrontendPerformanceSample(
                route_group="/dashboard",
                navigation_type="client",
                outcome="ready",
                shell_ms=10,
                content_ms=20,
                patient_id=42,
            )

    def test_endpoint_queues_best_effort_persistence_for_authenticated_user(self) -> None:
        tasks = BackgroundTasks()
        response = observability.registrar_desempenho_frontend(
            payload=observability.FrontendPerformanceSample(
                route_group="/configuracoes",
                navigation_type="initial",
                outcome="ready",
                shell_ms=150,
                content_ms=450,
            ),
            background_tasks=tasks,
            current_user=_FakeUser(),
        )
        self.assertEqual(response, {"accepted": True})
        self.assertEqual(len(tasks.tasks), 1)
        route = next(
            route
            for route in observability.router.routes
            if getattr(route, "path", "") == "/frontend-performance"
        )
        self.assertTrue(route.dependant.dependencies)


if __name__ == "__main__":
    unittest.main()
