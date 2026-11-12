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
    BACKEND_DIR
    / "migrations"
    / "versions"
    / "20260816_70_laudo_finalizado_em_exame_urgente.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260816_70", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class LaudoFinalizadoEmExameUrgenteMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-finalizado-em-exame-urgente.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_adiciona_as_colunas(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE laudos (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            paciente_id INTEGER NOT NULL,
                            status TEXT
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE exames (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            paciente_id INTEGER NOT NULL,
                            tipo_exame TEXT NOT NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text("INSERT INTO exames (paciente_id, tipo_exame) VALUES (1, 'Ecocardiograma')")
                )

                MIGRATION.upgrade(conn, "sqlite")
                # idempotencia
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            laudo_columns = {c["name"] for c in inspector.get_columns("laudos")}
            exame_columns = {c["name"] for c in inspector.get_columns("exames")}
            self.assertIn("finalizado_em", laudo_columns)
            self.assertIn("urgente_laudo", exame_columns)

            with engine.connect() as conn:
                value = conn.execute(
                    text("SELECT urgente_laudo FROM exames WHERE id = 1")
                ).scalar()
            self.assertEqual(value, 0)
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_e_no_op_se_tabelas_nao_existirem(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
            inspector = inspect(engine)
            self.assertEqual(inspector.get_table_names(), [])
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
