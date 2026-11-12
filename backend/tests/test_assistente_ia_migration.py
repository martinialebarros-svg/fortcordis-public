import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "20260720_52_assistente_ia_admin.py"
SPEC = importlib.util.spec_from_file_location("migration_20260720_52", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class AssistenteIAMigrationTest(unittest.TestCase):
    def test_upgrade_cria_tabelas_e_indices_de_forma_idempotente(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'assistente-ia-migration.db'}")
        try:
            with engine.begin() as connection:
                MIGRATION.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")

            inspector = inspect(engine)
            expected_tables = {
                "assistente_ia_conversas",
                "assistente_ia_mensagens",
                "assistente_ia_acoes_pendentes",
            }
            self.assertTrue(expected_tables.issubset(set(inspector.get_table_names())))
            action_columns = {
                column["name"]
                for column in inspector.get_columns("assistente_ia_acoes_pendentes")
            }
            self.assertTrue(
                {"tipo_acao", "alvo_snapshot_json", "status", "expires_at", "executed_at"}.issubset(
                    action_columns
                )
            )
            action_indexes = {
                index["name"]
                for index in inspector.get_indexes("assistente_ia_acoes_pendentes")
            }
            self.assertIn("ix_assistente_ia_acoes_usuario_status", action_indexes)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
