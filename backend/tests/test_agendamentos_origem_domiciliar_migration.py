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
    BACKEND_DIR / "migrations" / "versions" / "20260707_46_agendamentos_origem_domiciliar.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260707_46", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class AgendamentosOrigemDomiciliarMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agendamentos-origem-domiciliar-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_adds_columns_and_backfills_tutor_id_from_paciente(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE pacientes (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            nome TEXT,
                            tutor_id INTEGER
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE agendamentos (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            paciente_id INTEGER,
                            inicio TEXT,
                            status TEXT
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO pacientes (id, nome, tutor_id) VALUES
                            (1, 'Mel', 55),
                            (2, 'Luna', NULL)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO agendamentos (id, paciente_id, inicio, status) VALUES
                            (1, 1, '2099-06-03 14:00:00', 'Agendado'),
                            (2, 2, '2099-06-03 15:00:00', 'Agendado')
                        """
                    )
                )

                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

                rows = conn.execute(
                    text(
                        """
                        SELECT id, tutor_id, origem_atendimento
                        FROM agendamentos
                        ORDER BY id
                        """
                    )
                ).fetchall()

            inspector = inspect(engine)
            columns = {column["name"] for column in inspector.get_columns("agendamentos")}

            self.assertIn("tutor_id", columns)
            self.assertIn("origem_atendimento", columns)
            self.assertEqual(rows[0][0], 1)
            self.assertEqual(rows[0][1], 55)
            self.assertEqual(rows[0][2], "clinica_parceira")
            self.assertEqual(rows[1][0], 2)
            self.assertIsNone(rows[1][1])
            self.assertEqual(rows[1][2], "clinica_parceira")
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
