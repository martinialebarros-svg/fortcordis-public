import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-schema-preflight-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda  # noqa: E402


class AgendaSchemaPreflightTest(unittest.TestCase):
    def test_preflight_adds_legacy_columns_and_is_idempotent(self) -> None:
        expected_columns = {
            "tutor_id",
            "origem_atendimento",
            "reserva_expira_em",
            "excecao_deslocamento_concedida_em",
            "excecao_deslocamento_concedida_por_id",
            "excecao_deslocamento_concedida_por_nome",
            "excecao_deslocamento_motivo",
            "excecao_deslocamento_escopo",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_engine(f"sqlite:///{Path(tmpdir) / 'agenda-legacy.db'}")
            session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "CREATE TABLE agendamentos ("
                            "id INTEGER PRIMARY KEY, "
                            "descricao VARCHAR(255)"
                            ")"
                        )
                    )
                    connection.execute(
                        text("INSERT INTO agendamentos (id, descricao) VALUES (1, 'legado')")
                    )

                first_session = session_factory()
                try:
                    agenda._ensure_agendamento_workflow_columns(first_session)
                    agenda._ensure_agendamento_workflow_columns(first_session)
                finally:
                    first_session.close()

                columns = {column["name"] for column in inspect(engine).get_columns("agendamentos")}
                self.assertTrue(expected_columns.issubset(columns))

                second_session = session_factory()
                try:
                    agenda._ensure_agendamento_workflow_columns(second_session)
                    origem = second_session.execute(
                        text("SELECT origem_atendimento FROM agendamentos WHERE id = 1")
                    ).scalar_one()
                finally:
                    second_session.close()

                self.assertEqual(origem, "clinica_parceira")
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
