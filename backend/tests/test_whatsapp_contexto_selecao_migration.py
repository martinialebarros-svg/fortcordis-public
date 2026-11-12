import importlib.util
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PATH = Path(__file__).resolve().parents[1] / "migrations/versions/20261011_96_whatsapp_contexto_selecao.py"
SPEC = importlib.util.spec_from_file_location("migration_whatsapp_contexto_selecao", PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class WhatsAppContextoSelecaoMigrationTest(unittest.TestCase):
    def test_upgrade_idempotent_preserves_legacy_data_and_has_no_default_choice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_engine(f"sqlite:///{tmpdir}/migration.db")
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE TABLE whatsapp_bot_respostas (id INTEGER PRIMARY KEY, texto_gerado TEXT)"))
                    conn.execute(text("INSERT INTO whatsapp_bot_respostas VALUES (1, 'rascunho legado')"))
                    MIGRATION.upgrade(conn, "sqlite")
                    MIGRATION.upgrade(conn, "sqlite")
                    row = conn.execute(text("SELECT texto_gerado, contexto_chave FROM whatsapp_bot_respostas")).one()
                    self.assertEqual(row, ("rascunho legado", None))
                    self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM whatsapp_bot_contexto_selecao")).scalar(), 0)
                columns = {column["name"] for column in inspect(engine).get_columns("whatsapp_bot_contexto_selecao")}
                self.assertEqual(columns, {"wa_identity", "match_type", "cadastro_id", "versao", "atualizado_por_id", "updated_at"})
            finally:
                engine.dispose()

    def test_empty_database_and_unique_canonical_identity(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                self.assertNotIn("whatsapp_bot_respostas", inspect(conn).get_table_names())
                conn.execute(text("INSERT INTO whatsapp_bot_contexto_selecao (wa_identity) VALUES ('558599990001')"))
            with self.assertRaises(IntegrityError), engine.begin() as conn:
                conn.execute(text("INSERT INTO whatsapp_bot_contexto_selecao (wa_identity) VALUES ('558599990001')"))
            with self.assertRaises(IntegrityError), engine.begin() as conn:
                conn.execute(text("INSERT INTO whatsapp_bot_contexto_selecao (wa_identity,match_type) VALUES ('558599990002','clinica')"))
            with self.assertRaises(IntegrityError), engine.begin() as conn:
                conn.execute(text("INSERT INTO whatsapp_bot_contexto_selecao (wa_identity,cadastro_id) VALUES ('558599990003',1)"))
        finally:
            engine.dispose()
