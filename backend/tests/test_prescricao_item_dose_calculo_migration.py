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
    BACKEND_DIR / "migrations" / "versions" / "20260804_61_prescricao_item_dose_calculo.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260804_61", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class PrescricaoItemDoseCalculoMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "prescricao-item-dose-calculo-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_adds_os_4_campos_de_dose(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE prescricoes_itens (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            prescricao_id INTEGER NOT NULL,
                            medicamento_nome TEXT NOT NULL,
                            dose TEXT,
                            ordem INTEGER NOT NULL DEFAULT 0
                        )
                        """
                    )
                )

                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            columns = {column["name"] for column in inspector.get_columns("prescricoes_itens")}

            for coluna in (
                "dose_mg_kg",
                "peso_referencia_kg",
                "unidade_dose_calculo",
                "concentracao_personalizada",
            ):
                self.assertIn(coluna, columns)
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_e_no_op_se_tabela_nao_existir(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
            inspector = inspect(engine)
            self.assertNotIn("prescricoes_itens", inspector.get_table_names())
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
