import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

MIGRATION_PATH = (
    BACKEND_DIR
    / "migrations"
    / "versions"
    / "20260715_49_agendamentos_slot_overlap_guard.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260715_49", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class AgendamentosSlotOverlapMigrationTest(unittest.TestCase):
    def test_upgrade_ignora_dialetos_sem_exclusion_constraint(self) -> None:
        connection = MagicMock()

        MIGRATION.upgrade(connection, "sqlite")

        connection.execute.assert_not_called()

    def test_upgrade_normaliza_valida_e_cria_constraint_no_postgres(self) -> None:
        connection = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["agendamentos"]

        with patch.object(MIGRATION, "inspect", return_value=inspector), patch.object(
            MIGRATION, "_normalize_postgres_datetime_columns"
        ) as normalize, patch.object(
            MIGRATION, "_active_overlap_count", return_value=0
        ) as overlap_count, patch.object(
            MIGRATION, "_constraint_exists", return_value=False
        ) as constraint_exists, patch.object(
            MIGRATION, "_create_exclusion_constraint"
        ) as create_constraint:
            MIGRATION.upgrade(connection, "postgresql")

        normalize.assert_called_once_with(connection)
        overlap_count.assert_called_once_with(connection)
        constraint_exists.assert_called_once_with(connection)
        create_constraint.assert_called_once_with(connection)

    def test_upgrade_falha_antes_da_constraint_quando_ha_sobreposicao(self) -> None:
        connection = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["agendamentos"]

        with patch.object(MIGRATION, "inspect", return_value=inspector), patch.object(
            MIGRATION, "_normalize_postgres_datetime_columns"
        ), patch.object(
            MIGRATION, "_active_overlap_count", return_value=2
        ), patch.object(
            MIGRATION, "_create_exclusion_constraint"
        ) as create_constraint:
            with self.assertRaisesRegex(RuntimeError, "2 sobreposicao"):
                MIGRATION.upgrade(connection, "postgresql")

        create_constraint.assert_not_called()

    def test_constraint_cobre_todos_os_status_que_bloqueiam_slot(self) -> None:
        connection = MagicMock()

        MIGRATION._create_exclusion_constraint(connection)

        sql = str(connection.execute.call_args.args[0])
        self.assertIn("EXCLUDE USING gist", sql)
        self.assertIn("tstzrange", sql)
        for status in MIGRATION.BLOCKING_STATUSES:
            self.assertIn(status, sql)


if __name__ == "__main__":
    unittest.main()
