import importlib.util
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


PATH = Path(__file__).resolve().parents[1] / "migrations/versions/20261116_111_os_responsavel_pagamento.py"
SPEC = importlib.util.spec_from_file_location("os_responsavel_pagamento_migration", PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class OrdemServicoResponsavelPagamentoMigrationTest(unittest.TestCase):
    def test_upgrade_idempotente_preserva_os_e_assume_clinica_nas_antigas(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("""CREATE TABLE ordens_servico (
                id INTEGER PRIMARY KEY,
                clinica_id INTEGER NULL,
                status VARCHAR(50) DEFAULT 'Pendente'
            )"""))
            connection.execute(text("INSERT INTO ordens_servico(id, clinica_id) VALUES (1, 31), (2, NULL)"))

            MIGRATION.upgrade(connection, "sqlite")
            MIGRATION.upgrade(connection, "sqlite")

            columns = {column["name"]: column for column in inspect(connection).get_columns("ordens_servico")}
            self.assertFalse(columns["responsavel_pagamento_tipo"]["nullable"])
            self.assertEqual(
                connection.execute(text(
                    "SELECT id, clinica_id, responsavel_pagamento_tipo, responsavel_pagamento_id "
                    "FROM ordens_servico ORDER BY id"
                )).all(),
                [(1, 31, "clinica", None), (2, None, "clinica", None)],
            )
            indexes = {item["name"] for item in inspect(connection).get_indexes("ordens_servico")}
            self.assertIn("ix_ordens_servico_responsavel_pagamento", indexes)
        engine.dispose()

    def test_schema_ausente_nao_cria_tabela(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            MIGRATION.upgrade(connection, "sqlite")
            self.assertEqual(inspect(connection).get_table_names(), [])
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
