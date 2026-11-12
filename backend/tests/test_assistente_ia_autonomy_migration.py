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


def _load(filename: str, module_name: str):
    path = BACKEND_DIR / "migrations" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nao foi possivel carregar migracao: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load("20260720_52_assistente_ia_admin.py", "migration_20260720_52_autonomy")
COPILOT = _load("20260721_53_assistente_ia_copiloto.py", "migration_20260721_53_autonomy")
MIGRATION = _load("20260721_54_assistente_ia_autonomia.py", "migration_20260721_54")


class AssistenteIAAutonomyMigrationTest(unittest.TestCase):
    def test_upgrade_cria_fila_missoes_e_indice_semantico_de_forma_idempotente(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'assistente-ia-autonomy.db'}")
        try:
            with engine.begin() as connection:
                BASE.upgrade(connection, "sqlite")
                COPILOT.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")

            inspector = inspect(engine)
            self.assertTrue({
                "assistente_ia_conhecimento_trechos",
                "assistente_ia_missoes",
                "assistente_ia_execucoes",
            }.issubset(set(inspector.get_table_names())))
            document_columns = {
                column["name"]
                for column in inspector.get_columns("assistente_ia_conhecimento_documentos")
            }
            self.assertTrue({
                "semantic_enabled",
                "semantic_status",
                "embedding_model",
                "semantic_error",
                "indexed_at",
            }.issubset(document_columns))
            mission_indexes = {
                index["name"] for index in inspector.get_indexes("assistente_ia_missoes")
            }
            self.assertIn("ix_assistente_ia_missoes_enabled_next_run", mission_indexes)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
