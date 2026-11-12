import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

MIGRATION_PATH = (
    BACKEND_DIR
    / "migrations"
    / "versions"
    / "20260820_75_whatsapp_bot_atendimento.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260820_75", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class WhatsAppBotMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "whatsapp-bot-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_cria_tabelas_e_e_idempotente(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                # idempotencia
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            table_names = inspector.get_table_names()
            self.assertIn("whatsapp_bot_jobs", table_names)
            self.assertIn("whatsapp_bot_respostas", table_names)
            self.assertIn("whatsapp_bot_conversa_estado", table_names)

            jobs_columns = {c["name"] for c in inspector.get_columns("whatsapp_bot_jobs")}
            self.assertEqual(
                jobs_columns,
                {
                    "id",
                    "wa_identity",
                    "conversation_id",
                    "wa_message_id",
                    "status",
                    "scheduled_for",
                    "attempts",
                    "last_error",
                    "created_at",
                    "updated_at",
                },
            )
            jobs_indexes = {idx["name"] for idx in inspector.get_indexes("whatsapp_bot_jobs")}
            self.assertIn("ix_whatsapp_bot_jobs_status_scheduled_for", jobs_indexes)

            respostas_columns = {c["name"] for c in inspector.get_columns("whatsapp_bot_respostas")}
            self.assertEqual(
                respostas_columns,
                {
                    "id",
                    "job_id",
                    "wa_identity",
                    "conversation_id",
                    "decisao",
                    "motivo",
                    "texto_gerado",
                    "texto_enviado",
                    "modelo",
                    "prompt_version",
                    "tools_usadas",
                    "input_tokens",
                    "output_tokens",
                    "latencia_ms",
                    "resolution",
                    "match_type",
                    "feedback",
                    "enviado_por_id",
                    "created_at",
                },
            )

            estado_columns = {c["name"] for c in inspector.get_columns("whatsapp_bot_conversa_estado")}
            self.assertEqual(
                estado_columns,
                {
                    "wa_identity",
                    "modo",
                    "pausado_ate",
                    "handoff_motivo",
                    "atualizado_por_id",
                    "updated_at",
                },
            )
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_wa_message_id_e_unico(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                conn.execute(
                    text(
                        "INSERT INTO whatsapp_bot_jobs "
                        "(wa_identity, conversation_id, wa_message_id, scheduled_for) "
                        "VALUES ('558588018899', 'conv-1', 'wamid.abc', '2026-08-20 00:00:00')"
                    )
                )
                with self.assertRaises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO whatsapp_bot_jobs "
                            "(wa_identity, conversation_id, wa_message_id, scheduled_for) "
                            "VALUES ('558588018899', 'conv-1', 'wamid.abc', '2026-08-20 00:01:00')"
                        )
                    )
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_adiciona_colunas_em_configuracoes_com_default_seguro(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE configuracoes (id INTEGER PRIMARY KEY)"))
                conn.execute(text("INSERT INTO configuracoes (id) VALUES (1)"))

                MIGRATION.upgrade(conn, "sqlite")
                # idempotencia
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            columns = {c["name"] for c in inspector.get_columns("configuracoes")}
            self.assertIn("whatsapp_bot_atendimento_habilitado", columns)
            self.assertIn("whatsapp_bot_modo", columns)

            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT whatsapp_bot_atendimento_habilitado, whatsapp_bot_modo "
                        "FROM configuracoes WHERE id = 1"
                    )
                ).one()
            self.assertEqual(row[0], 0)
            self.assertEqual(row[1], "suggest")
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_e_no_op_se_configuracoes_nao_existir(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
            inspector = inspect(engine)
            self.assertNotIn("configuracoes", inspector.get_table_names())
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
