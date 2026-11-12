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


BASE_MIGRATION = _load("20260720_52_assistente_ia_admin.py", "migration_20260720_52_base")
MIGRATION = _load("20260721_53_assistente_ia_copiloto.py", "migration_20260721_53")


class AssistenteIACopilotoMigrationTest(unittest.TestCase):
    def test_upgrade_expande_schema_de_forma_idempotente(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'assistente-ia-copiloto.db'}")
        try:
            with engine.begin() as connection:
                BASE_MIGRATION.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")

            inspector = inspect(engine)
            self.assertTrue({
                "assistente_ia_memorias",
                "assistente_ia_conhecimento_documentos",
                "assistente_ia_feedbacks",
                "assistente_ia_rascunhos_clinicos",
                "agenda_bloqueios",
            }.issubset(set(inspector.get_table_names())))
            message_columns = {column["name"] for column in inspector.get_columns("assistente_ia_mensagens")}
            self.assertTrue({
                "provider_response_id",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "latency_ms",
                "provider_status",
            }.issubset(message_columns))
            block_indexes = {index["name"] for index in inspector.get_indexes("agenda_bloqueios")}
            self.assertIn("ix_agenda_bloqueios_ativo_inicio_fim", block_indexes)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
