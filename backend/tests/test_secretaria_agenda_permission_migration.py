import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "20260714_49_secretaria_excluir_agendamento.py"
SPEC = importlib.util.spec_from_file_location("migration_20260714_49", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class SecretariaAgendaPermissionMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "secretaria-agenda-permission.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def test_upgrade_updates_existing_permission(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE papeis (id INTEGER PRIMARY KEY, nome TEXT NOT NULL)"))
                conn.execute(text("""
                    CREATE TABLE papeis_permissoes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        papel_id INTEGER NOT NULL,
                        modulo TEXT NOT NULL,
                        visualizar INTEGER NOT NULL DEFAULT 1,
                        editar INTEGER NOT NULL DEFAULT 0,
                        excluir INTEGER NOT NULL DEFAULT 0,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (papel_id, modulo)
                    )
                """))
                conn.execute(text("INSERT INTO papeis (id, nome) VALUES (1, 'secretaria')"))
                conn.execute(text("""
                    INSERT INTO papeis_permissoes
                    (papel_id, modulo, visualizar, editar, excluir)
                    VALUES (1, 'agenda', 1, 1, 0)
                """))

                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

                excluir = conn.execute(text("""
                    SELECT excluir FROM papeis_permissoes
                    WHERE papel_id = 1 AND modulo = 'agenda'
                """)).scalar_one()

            self.assertEqual(excluir, 1)
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_creates_missing_permission(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE papeis (id INTEGER PRIMARY KEY, nome TEXT NOT NULL)"))
                conn.execute(text("""
                    CREATE TABLE papeis_permissoes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        papel_id INTEGER NOT NULL,
                        modulo TEXT NOT NULL,
                        visualizar INTEGER NOT NULL DEFAULT 1,
                        editar INTEGER NOT NULL DEFAULT 0,
                        excluir INTEGER NOT NULL DEFAULT 0,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (papel_id, modulo)
                    )
                """))
                conn.execute(text("INSERT INTO papeis (id, nome) VALUES (7, 'Secretaria')"))

                MIGRATION.upgrade(conn, "sqlite")

                row = conn.execute(text("""
                    SELECT visualizar, editar, excluir
                    FROM papeis_permissoes
                    WHERE papel_id = 7 AND modulo = 'agenda'
                """)).one()

            self.assertEqual(tuple(row), (1, 1, 1))
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
