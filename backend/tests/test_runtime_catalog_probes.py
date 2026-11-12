"""Repeated health/worker probes must not download the full table catalog."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "catalog-probes-test-secret-key-1234567890")

from app.core import runtime_checks
from app.models.assistente_ia import (
    AssistenteIAConhecimentoDocumento,
    AssistenteIAExecucao,
    AssistenteIAMemoria,
    AssistenteIAMissao,
    AssistenteIARegressaoCaso,
)
from app.services import assistente_ia_autonomy
from migrations import runner


class RuntimeCatalogProbesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            poolclass=QueuePool,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.05,
        )
        self.addCleanup(self.engine.dispose)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.versions = Path(self.tmp.name)
        self._migration("001")
        self._migration("002")
        # A large unrelated catalog must not affect probe results or query size.
        with self.engine.begin() as connection:
            for index in range(80):
                connection.execute(text(f"CREATE TABLE unrelated_{index} (id INTEGER)"))
        self.statements = []
        event.listen(self.engine, "before_cursor_execute", self._record_sql)
        self.addCleanup(event.remove, self.engine, "before_cursor_execute", self._record_sql)

    def _record_sql(self, connection, cursor, statement, parameters, context, executemany):
        self.statements.append((statement, parameters))

    def _migration(self, version):
        (self.versions / f"{version}.py").write_text(
            f'VERSION = "{version}"\nDESCRIPTION = "Synthetic {version}"\n'
            'def upgrade(connection, dialect):\n    raise AssertionError("read-only probe")\n'
        )

    def _tracking_table(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)"))

    def _assert_no_catalog_listing(self):
        self.assertFalse(
            any("select name from" in sql.lower() for sql, _ in self.statements),
            self.statements,
        )

    def test_repeated_migration_status_is_targeted_and_observes_live_changes(self):
        self._tracking_table()
        self.statements.clear()
        with patch.object(runner, "engine", self.engine), patch.object(runner, "VERSIONS_DIR", self.versions):
            for _ in range(10):
                status = runner.get_migration_status()
                self.assertTrue(status["tracking_table_exists"])
                self.assertEqual(status["pending_versions"], ["001", "002"])
            # One named-table probe plus the applied versions, on every call.
            self.assertEqual(len(self.statements), 20)
            self.assertEqual(sum("table_info" in sql for sql, _ in self.statements), 10)
            self.assertTrue(all(
                'table_info("schema_migrations")' in sql
                or sql == "SELECT version FROM schema_migrations"
                for sql, _ in self.statements
            ))
            self._assert_no_catalog_listing()

            with self.engine.begin() as connection:
                connection.execute(text("INSERT INTO schema_migrations VALUES ('001'), ('future')"))
            status = runner.get_migration_status()
            self.assertEqual(status["current_version"], "001")
            self.assertEqual(status["pending_versions"], ["002"])
            self.assertEqual(status["unknown_applied_versions"], ["future"])
            self._migration("003")
            self.assertEqual(runner.get_migration_status()["pending_versions"], ["002", "003"])
            with self.engine.begin() as connection:
                connection.execute(text("DROP TABLE schema_migrations"))
            status = runner.get_migration_status()
            self.assertFalse(status["tracking_table_exists"])
            self.assertEqual(status["pending_versions"], ["001", "002", "003"])

    def test_runtime_readiness_fails_closed_and_sees_migration_changes_immediately(self):
        with (
            patch.object(runner, "engine", self.engine),
            patch.object(runner, "VERSIONS_DIR", self.versions),
            patch.object(runtime_checks, "engine", self.engine),
            patch.object(runtime_checks.settings, "APP_ENV", "stage"),
            patch.object(runtime_checks.settings, "REQUIRE_UP_TO_DATE_MIGRATIONS", True),
            patch.object(runtime_checks, "_check_eco_study_ocr", return_value={"available": True}),
            patch.object(runtime_checks, "get_laudo_pdf_storage_dir", return_value=self.tmp.name),
            # Unrelated worker summaries can open their own configured database.
            # The database/migration readiness probes below remain real SQL.
            patch.object(runtime_checks, "get_whatsapp_reminder_scheduler_worker_runtime_state", return_value={}),
            patch.object(runtime_checks, "get_whatsapp_bot_worker_runtime_state", return_value={}),
        ):
            self.assertFalse(runtime_checks.build_runtime_report()["ready"])
            self._tracking_table()
            self.assertFalse(runtime_checks.build_runtime_report()["ready"])
            with self.engine.begin() as connection:
                connection.execute(text("INSERT INTO schema_migrations VALUES ('001'), ('002')"))
            self.assertTrue(runtime_checks.build_runtime_report()["ready"])
            with self.engine.begin() as connection:
                connection.execute(text("DELETE FROM schema_migrations WHERE version = '002'"))
            report = runtime_checks.build_runtime_report()
            self.assertFalse(report["ready"])
            self.assertEqual(report["migrations"]["pending_versions"], ["002"])
        self._assert_no_catalog_listing()

    def test_memory_probes_reuse_occupied_session_connection_without_stale_cache(self):
        for table in (AssistenteIAMemoria.__table__, AssistenteIARegressaoCaso.__table__):
            table.create(self.engine)
        self.statements.clear()
        with Session(self.engine) as db:
            db.execute(text("SELECT 1"))
            self.statements.clear()
            for _ in range(10):
                self.assertEqual(assistente_ia_autonomy._memory_contract_results(db), [])
                self.assertEqual(self.engine.pool.checkedout(), 1)
            # Two named-table probes and one actual regression-case SELECT.
            self.assertEqual(len(self.statements), 30)
            self.assertEqual(sum("table_info" in sql for sql, _ in self.statements), 20)
            self._assert_no_catalog_listing()
            db.execute(text("DROP TABLE assistente_ia_regressao_casos"))
            self.assertEqual(assistente_ia_autonomy._memory_contract_results(db), [])

    def test_scheduler_keeps_polling_with_targeted_probes_and_detects_missing_tables(self):
        factory = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        with patch.object(assistente_ia_autonomy, "SessionLocal", factory):
            self.assertEqual(
                assistente_ia_autonomy.run_assistant_scheduler_due_once(),
                {"scheduled": 0, "processed": 0, "errors": 0},
            )
            for table in (
                AssistenteIAMissao.__table__,
                AssistenteIAExecucao.__table__,
                AssistenteIAConhecimentoDocumento.__table__,
            ):
                table.create(self.engine)
            self.statements.clear()
            for _ in range(10):
                self.assertEqual(
                    assistente_ia_autonomy.run_assistant_scheduler_due_once(),
                    {"scheduled": 0, "processed": 0, "errors": 0},
                )
            self.assertEqual(len(self.statements), 60)
            self.assertEqual(sum("table_info" in sql for sql, _ in self.statements), 20)
            self._assert_no_catalog_listing()
            with self.engine.begin() as connection:
                connection.execute(text("DROP TABLE assistente_ia_missoes"))
            self.assertEqual(
                assistente_ia_autonomy.run_assistant_scheduler_due_once(),
                {"scheduled": 0, "processed": 0, "errors": 0},
            )


if __name__ == "__main__":
    unittest.main()
