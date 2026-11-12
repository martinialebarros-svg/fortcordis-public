import importlib.util
import unittest
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PATH = Path(__file__).resolve().parents[1] / "migrations/versions/20261005_95_laudo_eletro_ordem_servico.py"
SPEC = importlib.util.spec_from_file_location("laudo_eletro_os_migration", PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class LaudoEletroOrdemMigrationTest(unittest.TestCase):
    def test_upgrade_idempotente_preserva_dados_indices_trigger_e_restricoes(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("""CREATE TABLE ordens_servico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_os VARCHAR(50) NOT NULL UNIQUE,
                agendamento_id INTEGER NOT NULL,
                status VARCHAR(50) DEFAULT 'Pendente',
                futuro TEXT DEFAULT 'preservado'
            )"""))
            connection.execute(text("CREATE TABLE audit_test (os_id INTEGER)"))
            connection.execute(text("CREATE UNIQUE INDEX ux_ordens_servico_agendamento_ativa ON ordens_servico(agendamento_id) WHERE COALESCE(status, '') <> 'Cancelado'"))
            connection.execute(text("CREATE INDEX indice_extra ON ordens_servico(futuro)"))
            connection.execute(text("CREATE TRIGGER trigger_extra AFTER INSERT ON ordens_servico BEGIN INSERT INTO audit_test(os_id) VALUES (NEW.id); END"))
            connection.execute(text("INSERT INTO ordens_servico(numero_os,agendamento_id) VALUES ('ANTIGA',10)"))
            MIGRATION.upgrade(connection, "sqlite")
            MIGRATION.upgrade(connection, "sqlite")
            row = connection.execute(text("SELECT numero_os,agendamento_id,futuro,laudo_id,idempotency_key FROM ordens_servico WHERE id=1")).one()
            self.assertEqual(tuple(row), ("ANTIGA", 10, "preservado", None, None))
            columns = {column['name']: column for column in inspect(connection).get_columns("ordens_servico")}
            self.assertTrue(columns['agendamento_id']['nullable'])
            indexes = {item['name'] for item in inspect(connection).get_indexes("ordens_servico")}
            self.assertTrue({'indice_extra', 'ux_ordens_servico_agendamento_ativa', 'ux_ordens_servico_laudo_ativa', 'ux_ordens_servico_idempotency_key'}.issubset(indexes))
            connection.execute(text("INSERT INTO ordens_servico(numero_os,agendamento_id,laudo_id,idempotency_key) VALUES ('LAUDO1',NULL,1,'chave1'), ('LAUDO2',NULL,2,'chave2')"))
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM audit_test")).scalar(), 3)
            for sql in (
                "INSERT INTO ordens_servico(numero_os,agendamento_id) VALUES ('ANTIGA',NULL)",
                "INSERT INTO ordens_servico(numero_os,agendamento_id) VALUES ('DUPAG',10)",
                "INSERT INTO ordens_servico(numero_os,agendamento_id,laudo_id) VALUES ('DUPLAUDO',NULL,1)",
                "INSERT INTO ordens_servico(numero_os,agendamento_id,idempotency_key) VALUES ('DUPKEY',NULL,'chave1')",
            ):
                with self.subTest(sql=sql), self.assertRaises(IntegrityError):
                    connection.execute(text(sql))
            # Cancelar permite nova OS para o mesmo laudo, mas nunca reutilizar chave.
            connection.execute(text("UPDATE ordens_servico SET status='Cancelado' WHERE laudo_id=1"))
            connection.execute(text("INSERT INTO ordens_servico(numero_os,agendamento_id,laudo_id,idempotency_key) VALUES ('LAUDO3',NULL,1,'chave3')"))
            with self.assertRaises(IntegrityError):
                connection.execute(text("INSERT INTO ordens_servico(numero_os,agendamento_id,idempotency_key) VALUES ('RETRY',NULL,'chave1')"))
        engine.dispose()

    def test_schema_ausente_nao_fabrica_ordens(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            MIGRATION.upgrade(connection, "sqlite")
            self.assertEqual(inspect(connection).get_table_names(), [])
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
