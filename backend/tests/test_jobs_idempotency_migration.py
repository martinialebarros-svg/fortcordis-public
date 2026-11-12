import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

MIGRATION_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260516_38_jobs_idempotency_unique_active.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260516_38", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class JobsIdempotencyMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "jobs-idempotency-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def _index_exists(self, engine, table: str, index_name: str) -> bool:
        with engine.connect() as conn:
            rows = conn.execute(text(f"PRAGMA index_list('{table}')")).fetchall()
        return any(str(row[1]) == index_name for row in rows)

    def test_upgrade_normalizes_duplicates_and_creates_partial_unique_indexes(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE laudo_pdf_jobs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            laudo_id INTEGER NOT NULL,
                            requested_by_id INTEGER NOT NULL,
                            status TEXT NOT NULL,
                            cache_key TEXT,
                            erro TEXT,
                            finished_at DATETIME
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE xml_import_jobs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            requested_by_id INTEGER NOT NULL,
                            status TEXT NOT NULL,
                            conteudo_hash TEXT,
                            erro TEXT,
                            finished_at DATETIME
                        )
                        """
                    )
                )

                conn.execute(
                    text(
                        """
                        INSERT INTO laudo_pdf_jobs (laudo_id, requested_by_id, status, cache_key)
                        VALUES
                            (10, 5, 'pending', 'abc123'),
                            (10, 5, 'processing', 'abc123'),
                            (10, 5, 'completed', 'abc123')
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO xml_import_jobs (requested_by_id, status, conteudo_hash)
                        VALUES
                            (8, 'pending', 'hash-x'),
                            (8, 'processing', 'hash-x'),
                            (8, 'failed', 'hash-x')
                        """
                    )
                )

            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")

            self.assertTrue(
                self._index_exists(engine, "laudo_pdf_jobs", "uq_laudo_pdf_jobs_active_dedupe")
            )
            self.assertTrue(
                self._index_exists(engine, "xml_import_jobs", "uq_xml_import_jobs_active_dedupe")
            )

            with engine.connect() as conn:
                laudo_pending_count = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM laudo_pdf_jobs
                        WHERE laudo_id = 10
                          AND requested_by_id = 5
                          AND cache_key = 'abc123'
                          AND status IN ('pending','processing')
                        """
                    )
                ).scalar_one()
                laudo_failed_count = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM laudo_pdf_jobs
                        WHERE laudo_id = 10
                          AND requested_by_id = 5
                          AND cache_key = 'abc123'
                          AND status = 'failed'
                        """
                    )
                ).scalar_one()

                xml_pending_count = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM xml_import_jobs
                        WHERE requested_by_id = 8
                          AND conteudo_hash = 'hash-x'
                          AND status IN ('pending','processing')
                        """
                    )
                ).scalar_one()
                xml_failed_count = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM xml_import_jobs
                        WHERE requested_by_id = 8
                          AND conteudo_hash = 'hash-x'
                          AND status = 'failed'
                        """
                    )
                ).scalar_one()

            self.assertEqual(laudo_pending_count, 1)
            self.assertEqual(laudo_failed_count, 1)
            self.assertEqual(xml_pending_count, 1)
            self.assertEqual(xml_failed_count, 2)
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_adds_xml_hash_column_when_missing(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE xml_import_jobs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            requested_by_id INTEGER NOT NULL,
                            status TEXT NOT NULL,
                            arquivo_nome TEXT,
                            erro TEXT,
                            finished_at DATETIME
                        )
                        """
                    )
                )

            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")

            with engine.connect() as conn:
                columns = conn.execute(text("PRAGMA table_info('xml_import_jobs')")).fetchall()
                names = {str(row[1]) for row in columns}

            self.assertIn("conteudo_hash", names)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
