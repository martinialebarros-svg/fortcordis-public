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

MIGRATION_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260513_36_critical_composite_indexes.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260513_36", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class CriticalCompositeIndexesMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "critical-composite-indexes.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def _create_tables(self, engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE agendamentos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        data TEXT,
                        inicio DATETIME,
                        status TEXT,
                        clinica_id INTEGER,
                        servico_id INTEGER,
                        criado_por_id INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE atendimentos_clinicos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        clinica_id INTEGER,
                        agendamento_id INTEGER,
                        status TEXT,
                        data_atendimento DATETIME
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE ordens_servico (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agendamento_id INTEGER,
                        clinica_id INTEGER,
                        servico_id INTEGER,
                        criado_por_id INTEGER,
                        status TEXT,
                        data_atendimento DATETIME
                    )
                    """
                )
            )

    def _index_names(self, engine, table_name: str) -> set[str]:
        with engine.connect() as conn:
            rows = conn.execute(text(f"PRAGMA index_list('{table_name}')")).fetchall()
        return {str(row[1]) for row in rows}

    def test_upgrade_creates_expected_composite_indexes(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            self._create_tables(engine)

            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")

            agendamentos_indexes = self._index_names(engine, "agendamentos")
            atendimentos_indexes = self._index_names(engine, "atendimentos_clinicos")
            ordens_indexes = self._index_names(engine, "ordens_servico")

            self.assertTrue(
                {
                    "ix_agendamentos_data_inicio_id",
                    "ix_agendamentos_data_status_inicio_id",
                    "ix_agendamentos_data_clinica_inicio_id",
                    "ix_agendamentos_data_servico_inicio_id",
                    "ix_agendamentos_data_criado_por_inicio_id",
                }.issubset(agendamentos_indexes)
            )

            self.assertTrue(
                {
                    "ix_atendimentos_clinicos_data_atendimento_id",
                    "ix_atendimentos_clinicos_clinica_data_id",
                    "ix_atendimentos_clinicos_status_data_id",
                    "ix_atendimentos_clinicos_agendamento_data_id",
                }.issubset(atendimentos_indexes)
            )

            self.assertTrue(
                {
                    "ix_ordens_servico_status_data_atendimento_id",
                    "ix_ordens_servico_clinica_status_data_id",
                    "ix_ordens_servico_servico_status_data_id",
                    "ix_ordens_servico_criado_por_status_data_id",
                    "ix_ordens_servico_agendamento_status_id",
                }.issubset(ordens_indexes)
            )
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
