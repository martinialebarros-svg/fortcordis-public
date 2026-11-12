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
    BACKEND_DIR / "migrations" / "versions" / "20260901_79_laudos_pending_queue_index.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260901_79", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class LaudosPendingQueueIndexMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudos-pending-queue-index.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_creates_idempotent_lookup_index_used_by_pending_query(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE TABLE laudos (
                            id INTEGER PRIMARY KEY,
                            agendamento_id INTEGER,
                            tipo TEXT NOT NULL,
                            status TEXT NOT NULL,
                            created_at DATETIME
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO laudos (id, agendamento_id, tipo, status, created_at)
                        VALUES
                            (1, 10, 'Ecocardiograma', 'Finalizado', '2026-09-01 08:00:00'),
                            (2, 10, 'Ecocardiograma', 'Rascunho', '2026-09-01 09:00:00'),
                            (3, 11, 'Eletrocardiograma', 'Rascunho', '2026-09-01 10:00:00')
                        """
                    )
                )
                MIGRATION.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")

                index_names = {
                    str(row[1])
                    for row in connection.execute(text("PRAGMA index_list('laudos')")).fetchall()
                }
                self.assertIn(MIGRATION.INDEX_NAME, index_names)

                plan = connection.execute(
                    text(
                        """
                        EXPLAIN QUERY PLAN
                        SELECT id, status
                        FROM laudos
                        WHERE agendamento_id = 10
                          AND lower(trim(tipo)) = 'ecocardiograma'
                        ORDER BY created_at DESC, id DESC
                        LIMIT 1
                        """
                    )
                ).fetchall()

            plan_text = " ".join(str(row[-1]) for row in plan)
            self.assertIn(MIGRATION.INDEX_NAME, plan_text)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
