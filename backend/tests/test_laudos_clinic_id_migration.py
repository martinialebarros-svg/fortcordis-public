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
    BACKEND_DIR / "migrations" / "versions" / "20260704_44_laudos_clinic_id_alignment.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260704_44", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class LaudosClinicIdMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudos-clinic-id-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_adds_clinic_id_to_legacy_laudos_table(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE laudos (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            paciente_id INTEGER NOT NULL,
                            veterinario_id INTEGER NOT NULL,
                            tipo TEXT NOT NULL,
                            titulo TEXT NOT NULL
                        )
                        """
                    )
                )

                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            columns = {column["name"] for column in inspector.get_columns("laudos")}
            indexes = {index["name"] for index in inspector.get_indexes("laudos")}

            self.assertIn("clinic_id", columns)
            self.assertIn("ix_laudos_clinic_id", indexes)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
