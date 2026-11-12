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
    / "20260816_69_portal_clinic_account_must_change_password.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260816_69", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class PortalClinicAccountMustChangePasswordMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-clinic-account-must-change-password.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_adiciona_a_coluna_com_default_false(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE portal_clinic_accounts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            clinica_id INTEGER NOT NULL,
                            email_normalized TEXT NOT NULL,
                            password_hash TEXT NOT NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO portal_clinic_accounts (clinica_id, email_normalized, password_hash)"
                        " VALUES (1, 'teste@example.com', 'hash')"
                    )
                )

                MIGRATION.upgrade(conn, "sqlite")
                # idempotencia
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            columns = {column["name"] for column in inspector.get_columns("portal_clinic_accounts")}
            self.assertIn("must_change_password", columns)

            with engine.connect() as conn:
                value = conn.execute(
                    text("SELECT must_change_password FROM portal_clinic_accounts WHERE id = 1")
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
            self.assertNotIn("portal_clinic_accounts", inspector.get_table_names())
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
