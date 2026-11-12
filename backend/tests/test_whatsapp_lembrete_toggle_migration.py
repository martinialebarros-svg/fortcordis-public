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
    / "20260818_73_whatsapp_lembrete_toggle_config.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260818_73", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class WhatsAppLembreteToggleMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "whatsapp-lembrete-toggle-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_adiciona_coluna_e_e_idempotente(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE configuracoes (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
                conn.execute(text("INSERT INTO configuracoes DEFAULT VALUES"))

                MIGRATION.upgrade(conn, "sqlite")
                # idempotencia
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            columns = {c["name"] for c in inspector.get_columns("configuracoes")}
            self.assertIn("whatsapp_lembrete_automatico_habilitado", columns)

            with engine.connect() as conn:
                value = conn.execute(
                    text("SELECT whatsapp_lembrete_automatico_habilitado FROM configuracoes")
                ).scalar()
            self.assertEqual(value, 0)
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_e_no_op_se_tabela_nao_existir(self) -> None:
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
