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

MIGRATION_PATH = (
    BACKEND_DIR
    / "migrations"
    / "versions"
    / "20260725_56_ai_echo_voice_assistant.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("ai_echo_migration_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class AIEchoMigrationTest(unittest.TestCase):
    def test_upgrade_is_idempotent_and_downgrade_removes_only_module_tables(self) -> None:
        migration = load_migration()
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_engine(f"sqlite:///{Path(tmpdir) / 'migration.db'}")
            try:
                with engine.begin() as connection:
                    migration.upgrade(connection, "sqlite")
                    migration.upgrade(connection, "sqlite")
                tables = set(inspect(engine).get_table_names())
                expected = {
                    "ai_echo_sessions",
                    "ai_echo_audio_assets",
                    "ai_echo_transcripts",
                    "ai_echo_field_suggestions",
                    "ai_echo_measurements",
                    "ai_echo_clinical_warnings",
                    "ai_echo_feedback",
                    "ai_echo_vocabulary",
                    "ai_echo_phrase_preferences",
                    "ai_echo_applications",
                }
                self.assertTrue(expected.issubset(tables))
                with engine.begin() as connection:
                    migration.downgrade(connection, "sqlite")
                self.assertTrue(expected.isdisjoint(set(inspect(engine).get_table_names())))
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
