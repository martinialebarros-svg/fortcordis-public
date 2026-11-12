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
    / "20260730_59_atendimento_agenda_transactional_finalization.py"
)
SPEC = importlib.util.spec_from_file_location("atendimento_finalization_migration", MIGRATION_PATH)
assert SPEC and SPEC.loader
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)

from migrations.exceptions import MigrationDeferred  # noqa: E402


class AtendimentoTransactionalFinalizationMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "migration.db"
        self.engine = create_engine(f"sqlite:///{db_path}")

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmpdir.cleanup()

    @staticmethod
    def _create_tables(connection) -> None:
        connection.execute(
            text(
                """
                CREATE TABLE atendimentos_clinicos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agendamento_id INTEGER NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ordens_servico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agendamento_id INTEGER NOT NULL,
                    status TEXT NULL
                )
                """
            )
        )

    def test_upgrade_cria_restricoes_parciais_em_base_integra(self) -> None:
        with self.engine.begin() as connection:
            self._create_tables(connection)
            connection.execute(
                text(
                    "INSERT INTO atendimentos_clinicos (agendamento_id) VALUES "
                    "(10), (NULL), (NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ordens_servico (agendamento_id, status) VALUES "
                    "(10, 'Cancelado'), (10, 'Pendente'), (11, 'Pago')"
                )
            )
            MIGRATION.upgrade(connection)

        inspector = inspect(self.engine)
        atendimento_indexes = {
            item["name"] for item in inspector.get_indexes("atendimentos_clinicos")
        }
        os_indexes = {item["name"] for item in inspector.get_indexes("ordens_servico")}
        self.assertIn(
            "ux_atendimentos_clinicos_agendamento_unico",
            atendimento_indexes,
        )
        self.assertIn("ux_ordens_servico_agendamento_ativa", os_indexes)

        with self.engine.begin() as connection:
            with self.assertRaises(Exception):
                connection.execute(
                    text(
                        "INSERT INTO atendimentos_clinicos (agendamento_id) VALUES (10)"
                    )
                )

    def test_upgrade_adia_sem_apagar_atendimentos_duplicados(self) -> None:
        with self.engine.begin() as connection:
            self._create_tables(connection)
            connection.execute(
                text(
                    "INSERT INTO atendimentos_clinicos (agendamento_id) VALUES (10), (10)"
                )
            )
            with self.assertRaises(MigrationDeferred) as ctx:
                MIGRATION.upgrade(connection)
            total = connection.execute(
                text(
                    "SELECT COUNT(*) FROM atendimentos_clinicos WHERE agendamento_id = 10"
                )
            ).scalar_one()

        self.assertIn("agendamento 10", str(ctx.exception))
        self.assertIn("ids 1,2", str(ctx.exception))
        self.assertEqual(total, 2)

    def test_upgrade_adia_sem_cancelar_os_ativas_duplicadas(self) -> None:
        with self.engine.begin() as connection:
            self._create_tables(connection)
            connection.execute(
                text(
                    "INSERT INTO ordens_servico (agendamento_id, status) VALUES "
                    "(22, 'Pendente'), (22, 'Pago')"
                )
            )
            with self.assertRaises(MigrationDeferred) as ctx:
                MIGRATION.upgrade(connection)
            statuses = list(
                connection.execute(
                    text(
                        "SELECT status FROM ordens_servico "
                        "WHERE agendamento_id = 22 ORDER BY id"
                    )
                ).scalars()
            )

        self.assertIn("agendamento 22", str(ctx.exception))
        self.assertEqual(statuses, ["Pendente", "Pago"])

    def test_upgrade_relata_as_duas_pendencias_de_uma_vez(self) -> None:
        """Evita o ciclo de conciliar uma duplicidade e so no proximo deploy
        descobrir a outra."""
        with self.engine.begin() as connection:
            self._create_tables(connection)
            connection.execute(
                text(
                    "INSERT INTO atendimentos_clinicos (agendamento_id) VALUES (10), (10)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ordens_servico (agendamento_id, status) VALUES "
                    "(22, 'Pendente'), (22, 'Pago')"
                )
            )
            with self.assertRaises(MigrationDeferred) as ctx:
                MIGRATION.upgrade(connection)

        mensagem = str(ctx.exception)
        self.assertIn("um atendimento por agendamento", mensagem)
        self.assertIn("uma OS ativa por agendamento", mensagem)
        self.assertIn("agendamento 10", mensagem)
        self.assertIn("agendamento 22", mensagem)

    def test_migration_deferred_e_runtime_error(self) -> None:
        """Compatibilidade: quem captura RuntimeError continua funcionando."""
        self.assertTrue(issubclass(MigrationDeferred, RuntimeError))


if __name__ == "__main__":
    unittest.main()
