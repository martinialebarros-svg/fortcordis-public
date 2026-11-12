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
    / "20260824_76_whatsapp_bot_piloto_clinica.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260824_76", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)

MIGRATION_77_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260824_77_whatsapp_bot_resposta_clinica.py"
)
SPEC_77 = importlib.util.spec_from_file_location("migration_20260824_77", MIGRATION_77_PATH)
if SPEC_77 is None or SPEC_77.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_77_PATH}")
MIGRATION_77 = importlib.util.module_from_spec(SPEC_77)
SPEC_77.loader.exec_module(MIGRATION_77)


class WhatsAppBotPilotoMigrationTest(unittest.TestCase):
    """P1.2: schema do piloto por clinica (CA-P07, NFR-P01, NFR-P03)."""

    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "whatsapp-bot-piloto-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE clinicas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT)")
            )
        return tmpdir, engine

    def test_upgrade_cria_tabela_e_e_idempotente(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

            inspector = inspect(engine)
            self.assertIn("whatsapp_bot_clinica_estado", inspector.get_table_names())
            colunas = {c["name"] for c in inspector.get_columns("whatsapp_bot_clinica_estado")}
            self.assertEqual(
                colunas,
                {
                    "id",
                    "clinica_id",
                    "modo",
                    "observacao",
                    "habilitado_por_id",
                    "created_at",
                    "updated_at",
                },
            )
            indices = {i["name"] for i in inspector.get_indexes("whatsapp_bot_clinica_estado")}
            self.assertIn("ix_whatsapp_bot_clinica_estado_clinica_id", indices)
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_clinica_id_e_unico(self) -> None:
        """Uma clinica tem um estado de participacao, nao varios."""
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                conn.execute(text("INSERT INTO clinicas (id, nome) VALUES (1, 'Parceira')"))
                conn.execute(
                    text("INSERT INTO whatsapp_bot_clinica_estado (clinica_id, modo) VALUES (1, 'suggest')")
                )
            with self.assertRaises(IntegrityError):
                with engine.begin() as conn:
                    conn.execute(
                        text("INSERT INTO whatsapp_bot_clinica_estado (clinica_id, modo) VALUES (1, 'off')")
                    )
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_participacao_nasce_todos_e_preserva_comportamento(self) -> None:
        """NFR-P01: aplicar a migracao nao muda instalacao existente.

        Inclui a linha que ja existia antes da coluna: default de coluna nao
        preenche linha antiga em todo dialeto, entao a migracao faz o UPDATE.
        """
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("CREATE TABLE configuracoes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome_empresa TEXT)")
                )
                conn.execute(text("INSERT INTO configuracoes (nome_empresa) VALUES ('FortCordis')"))
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
                MIGRATION.upgrade(conn, "sqlite")

            colunas = {c["name"] for c in inspect(engine).get_columns("configuracoes")}
            self.assertIn("whatsapp_bot_participacao", colunas)
            with engine.begin() as conn:
                valor = conn.execute(
                    text("SELECT whatsapp_bot_participacao FROM configuracoes")
                ).scalar()
            self.assertEqual(valor, "todos", "linha existente tem que nascer em 'todos'")
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_no_op_sem_configuracoes(self) -> None:
        """Banco sem `configuracoes` nao pode quebrar a migracao."""
        tmpdir, engine = self._build_engine()
        try:
            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")
            self.assertIn("whatsapp_bot_clinica_estado", inspect(engine).get_table_names())
        finally:
            engine.dispose()
            tmpdir.cleanup()


class WhatsAppBotRespostaClinicaMigrationTest(unittest.TestCase):
    """Fase 4: coluna que torna a metrica do piloto atribuivel."""

    def _engine_com_respostas(self, tmpdir: str):
        db_path = Path(tmpdir) / "resposta-clinica.db"
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE whatsapp_bot_respostas ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, wa_identity TEXT, decisao TEXT)"
                )
            )
        return engine

    def test_adiciona_coluna_e_indice_e_e_idempotente(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_com_respostas(tmpdir)
            try:
                with engine.begin() as conn:
                    MIGRATION_77.upgrade(conn, "sqlite")
                    MIGRATION_77.upgrade(conn, "sqlite")
                inspector = inspect(engine)
                colunas = {c["name"] for c in inspector.get_columns("whatsapp_bot_respostas")}
                self.assertIn("clinica_id", colunas)
                indices = {i["name"] for i in inspector.get_indexes("whatsapp_bot_respostas")}
                self.assertIn("ix_whatsapp_bot_respostas_clinica_id", indices)
            finally:
                engine.dispose()

    def test_no_op_sem_a_tabela_de_respostas(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "vazio.db"
            engine = create_engine(f"sqlite:///{db_path}")
            try:
                with engine.begin() as conn:
                    MIGRATION_77.upgrade(conn, "sqlite")
                self.assertNotIn("whatsapp_bot_respostas", inspect(engine).get_table_names())
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
