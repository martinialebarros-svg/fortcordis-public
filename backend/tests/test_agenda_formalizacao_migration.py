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
    / "20260820_74_agenda_formalizacao_invites.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260820_74", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class AgendaFormalizacaoMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-formalizacao-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_cria_tabela_e_indices_e_e_idempotente(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                # idempotencia
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            self.assertIn("agenda_formalizacao_invites", inspector.get_table_names())
            columns = {c["name"] for c in inspector.get_columns("agenda_formalizacao_invites")}
            self.assertEqual(
                columns,
                {
                    "id",
                    "agendamento_id",
                    "token_hash",
                    "status",
                    "expires_at",
                    "used_at",
                    "revoked_at",
                    "created_at",
                },
            )
            index_names = {idx["name"] for idx in inspector.get_indexes("agenda_formalizacao_invites")}
            self.assertIn("ix_agenda_formalizacao_invites_agendamento_id", index_names)
            self.assertIn("ix_agenda_formalizacao_invites_token_hash", index_names)
            self.assertIn("ix_agenda_formalizacao_invites_status", index_names)
            self.assertIn("ix_agenda_formalizacao_invites_expires_at", index_names)

            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO agenda_formalizacao_invites "
                        "(agendamento_id, token_hash, expires_at) VALUES (1, 'abc123', '2026-08-20 00:00:00')"
                    )
                )
                status = conn.execute(
                    text("SELECT status FROM agenda_formalizacao_invites WHERE agendamento_id = 1")
                ).scalar()
            self.assertEqual(status, "pending")
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
