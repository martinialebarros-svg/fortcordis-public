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
    BACKEND_DIR / "migrations" / "versions" / "20260514_37_people_datetime_normalization.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260514_37", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class PeopleDatetimeNormalizationMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "people-datetime-normalization.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def _create_legacy_tables(self, engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE tutores (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE pacientes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO tutores (nome, created_at, updated_at)
                    VALUES
                        ('Tutor A', NULL, NULL),
                        ('Tutor B', '2026-05-14T10:11:12.999Z', '  ')
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO pacientes (nome, created_at, updated_at)
                    VALUES
                        ('Paciente A', '', '2026-05-14T13:14:15'),
                        ('Paciente B', '2026-05-14 16:17:18', NULL)
                    """
                )
            )

    def test_upgrade_normalizes_legacy_people_timestamps(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            self._create_legacy_tables(engine)

            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                # idempotencia basica
                MIGRATION.upgrade(conn, "sqlite")

            with engine.connect() as conn:
                tutor_rows = conn.execute(
                    text("SELECT created_at, updated_at FROM tutores ORDER BY id")
                ).fetchall()
                paciente_rows = conn.execute(
                    text("SELECT created_at, updated_at FROM pacientes ORDER BY id")
                ).fetchall()

            # created_at deve estar sempre preenchido
            self.assertIsNotNone(tutor_rows[0][0])
            self.assertIsNotNone(tutor_rows[1][0])
            self.assertIsNotNone(paciente_rows[0][0])
            self.assertIsNotNone(paciente_rows[1][0])

            # formato textual normalizado sem "T" para compatibilidade de parse
            self.assertIn(" ", str(tutor_rows[1][0]))
            self.assertNotIn("T", str(tutor_rows[1][0]))
            self.assertIn(" ", str(paciente_rows[0][1]))
            self.assertNotIn("T", str(paciente_rows[0][1]))

            # blank string vira NULL em updated_at
            self.assertIsNone(tutor_rows[1][1])
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
