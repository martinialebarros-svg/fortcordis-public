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

MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "20260811_66_whatsapp_agenda_respostas.py"
SPEC = importlib.util.spec_from_file_location("migration_20260811_66", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class WhatsAppAgendaMigrationTest(unittest.TestCase):
    def test_upgrade_is_idempotent_and_provider_message_is_unique(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'migration.db'}")
        try:
            with engine.begin() as connection:
                MIGRATION.upgrade(connection, "sqlite")
                MIGRATION.upgrade(connection, "sqlite")
                connection.execute(text("""
                    INSERT INTO whatsapp_agenda_respostas (
                        provider_message_id, agendamento_id, action, from_phone, result
                    ) VALUES ('wamid.unique', 10, 'confirmar', '5585999999999', 'confirmado')
                """))

            inspector = inspect(engine)
            self.assertIn("whatsapp_agenda_respostas", inspector.get_table_names())
            columns = {item["name"] for item in inspector.get_columns("whatsapp_agenda_respostas")}
            self.assertIn("provider_message_id", columns)
            self.assertIn("result_json", columns)

            with self.assertRaises(Exception):
                with engine.begin() as connection:
                    connection.execute(text("""
                        INSERT INTO whatsapp_agenda_respostas (
                            provider_message_id, agendamento_id, action, from_phone, result
                        ) VALUES ('wamid.unique', 10, 'confirmar', '5585999999999', 'confirmado')
                    """))
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
