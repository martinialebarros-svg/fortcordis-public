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
    BACKEND_DIR / "migrations" / "versions" / "20260816_68_exame_created_at_timestamp_fix.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260816_68", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class ExameCreatedAtTimestampMigrationTest(unittest.TestCase):
    def test_upgrade_ignora_dialetos_diferentes_de_postgres(self) -> None:
        connection = MagicMock()

        MIGRATION.upgrade(connection, "sqlite")

        connection.execute.assert_not_called()

    def test_upgrade_ignora_quando_tabela_nao_existe(self) -> None:
        connection = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = []

        with patch.object(MIGRATION, "inspect", return_value=inspector):
            MIGRATION.upgrade(connection, "postgresql")

        connection.execute.assert_not_called()

    def test_upgrade_ignora_quando_coluna_ja_e_timestamp(self) -> None:
        connection = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["exames"]
        inspector.get_columns.return_value = [
            {"name": "created_at", "type": "TIMESTAMP"},
        ]

        with patch.object(MIGRATION, "inspect", return_value=inspector):
            MIGRATION.upgrade(connection, "postgresql")

        connection.execute.assert_not_called()

    def test_upgrade_converte_coluna_texto_para_timestamp_no_postgres(self) -> None:
        connection = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["exames"]
        inspector.get_columns.return_value = [
            {"name": "created_at", "type": "TEXT"},
        ]

        with patch.object(MIGRATION, "inspect", return_value=inspector):
            MIGRATION.upgrade(connection, "postgresql")

        executed_sql = [call.args[0].text for call in connection.execute.call_args_list]
        self.assertTrue(any("DROP DEFAULT" in sql for sql in executed_sql))
        self.assertTrue(any("ALTER COLUMN created_at TYPE TIMESTAMP" in sql for sql in executed_sql))
        self.assertTrue(any("SET DEFAULT NOW()" in sql for sql in executed_sql))

    def test_upgrade_e_idempotente(self) -> None:
        connection = MagicMock()
        inspector_first = MagicMock()
        inspector_first.get_table_names.return_value = ["exames"]
        inspector_first.get_columns.return_value = [
            {"name": "created_at", "type": "TEXT"},
        ]
        inspector_second = MagicMock()
        inspector_second.get_table_names.return_value = ["exames"]
        inspector_second.get_columns.return_value = [
            {"name": "created_at", "type": "TIMESTAMP"},
        ]

        with patch.object(
            MIGRATION,
            "inspect",
            side_effect=[inspector_first, inspector_first, inspector_second, inspector_second],
        ):
            MIGRATION.upgrade(connection, "postgresql")
            call_count_after_first = connection.execute.call_count
            MIGRATION.upgrade(connection, "postgresql")

        self.assertEqual(connection.execute.call_count, call_count_after_first)


if __name__ == "__main__":
    unittest.main()
