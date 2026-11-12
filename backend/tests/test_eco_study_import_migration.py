import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

MIGRATION_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260712_48_eco_study_import_jobs.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260712_48", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class EcoStudyImportMigrationTest(unittest.TestCase):
    def test_upgrade_is_idempotent_and_enforces_active_dedupe(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(temp_dir.name) / 'eco-study.db'}")
        try:
            with engine.begin() as connection:
                MIGRATION.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")

            inspector = inspect(engine)
            self.assertIn("eco_study_import_jobs", inspector.get_table_names())
            indexes = {index["name"] for index in inspector.get_indexes("eco_study_import_jobs")}
            self.assertIn("uq_eco_study_import_jobs_active_dedupe", indexes)

            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO eco_study_import_jobs
                            (requested_by_id, status, conteudo_hash)
                        VALUES (7, 'pending', 'same-hash')
                        """
                    )
                )
                with self.assertRaises(Exception):
                    connection.execute(
                        text(
                            """
                            INSERT INTO eco_study_import_jobs
                                (requested_by_id, status, conteudo_hash)
                            VALUES (7, 'processing', 'same-hash')
                            """
                        )
                    )
        finally:
            engine.dispose()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
