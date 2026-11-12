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

MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "20260805_64_exame_ajustes.py"
SPEC = importlib.util.spec_from_file_location("migration_20260805_64", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class ExameAjustesMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "exame-ajustes-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_cria_a_tabela(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            self.assertIn("exame_ajustes", inspector.get_table_names())
            columns = {column["name"] for column in inspector.get_columns("exame_ajustes")}
            self.assertEqual(
                columns,
                {
                    "id",
                    "exame_id",
                    "atendimento_id",
                    "campo",
                    "valor_anterior",
                    "valor_novo",
                    "motivo",
                    "responsavel_id",
                    "responsavel_nome",
                    "created_at",
                },
            )
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_permite_insercao(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                conn.execute(
                    text(
                        "INSERT INTO exame_ajustes "
                        "(exame_id, atendimento_id, campo, valor_anterior, valor_novo) "
                        "VALUES (1, 1, 'resultado', 'Normal', 'Leucocitose importante')"
                    )
                )
                row = conn.execute(text("SELECT campo, valor_anterior, valor_novo FROM exame_ajustes")).first()
            self.assertEqual(tuple(row), ("resultado", "Normal", "Leucocitose importante"))
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
