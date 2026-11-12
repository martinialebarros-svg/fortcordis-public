import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis-test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-recepcao-agenda-permission")

MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "20260714_50_recepcao_excluir_agendamento.py"
SPEC = importlib.util.spec_from_file_location("migration_20260714_50", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)

from app.core.security import _user_has_matrix_permission


class RecepcaoAgendaPermissionMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "recepcao-agenda-permission.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    @staticmethod
    def _create_schema(connection) -> None:
        connection.execute(text("CREATE TABLE papeis (id INTEGER PRIMARY KEY, nome TEXT NOT NULL)"))
        connection.execute(text("""
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

    def test_upgrade_updates_real_recepcao_role(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                self._create_schema(conn)
                conn.execute(text("INSERT INTO papeis (id, nome) VALUES (2, 'recepcao')"))
                conn.execute(text("""
                    INSERT INTO papeis_permissoes
                    (papel_id, modulo, visualizar, editar, excluir)
                    VALUES (2, 'agenda', 1, 1, 0)
                """))

                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

                excluir = conn.execute(text("""
                    SELECT excluir FROM papeis_permissoes
                    WHERE papel_id = 2 AND modulo = 'agenda'
                """)).scalar_one()

            self.assertEqual(excluir, 1)

            with Session(engine) as session:
                usuario_recepcao = SimpleNamespace(
                    papeis=[SimpleNamespace(id=2)],
                )
                self.assertTrue(
                    _user_has_matrix_permission(
                        session,
                        usuario_recepcao,
                        "agenda",
                        "excluir",
                    )
                )
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_covers_secretaria_and_accented_aliases(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                self._create_schema(conn)
                conn.execute(text("""
                    INSERT INTO papeis (id, nome) VALUES
                    (1, 'secretaria'),
                    (2, 'Secretária'),
                    (3, 'recepcao'),
                    (4, 'Recepção')
                """))

                MIGRATION.upgrade(conn, "sqlite")

                rows = conn.execute(text("""
                    SELECT p.nome, pp.visualizar, pp.editar, pp.excluir
                    FROM papeis p
                    JOIN papeis_permissoes pp ON pp.papel_id = p.id
                    WHERE pp.modulo = 'agenda'
                    ORDER BY p.id
                """)).all()

            self.assertEqual(
                rows,
                [
                    ("secretaria", 1, 1, 1),
                    ("Secretária", 1, 1, 1),
                    ("recepcao", 1, 1, 1),
                    ("Recepção", 1, 1, 1),
                ],
            )
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_does_not_grant_other_roles(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                self._create_schema(conn)
                conn.execute(text("INSERT INTO papeis (id, nome) VALUES (7, 'veterinario')"))
                conn.execute(text("""
                    INSERT INTO papeis_permissoes
                    (papel_id, modulo, visualizar, editar, excluir)
                    VALUES (7, 'agenda', 1, 1, 0)
                """))

                MIGRATION.upgrade(conn, "sqlite")

                excluir = conn.execute(text("""
                    SELECT excluir FROM papeis_permissoes
                    WHERE papel_id = 7 AND modulo = 'agenda'
                """)).scalar_one()

            self.assertEqual(excluir, 0)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
