import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "relatorios-agregacao-memoria-test-secret-key-1234567890")

from app.api.v1.endpoints import relatorios
from app.models.agendamento import Agendamento


class RelatoriosAgregacaoMemoriaTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "relatorios-agregacao-memoria.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Agendamento.__table__.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_carrega_apenas_colunas_necessarias_de_agendamento(self) -> None:
        tmpdir, db, engine = self._build_session()
        statements = []

        def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", _capture_sql)
        try:
            inicio = datetime(2026, 5, 1, 10, 0)
            db.add(
                Agendamento(
                    paciente_id=123,
                    clinica_id=7,
                    servico_id=11,
                    inicio=inicio,
                    fim=inicio,
                    data="2026-05-01",
                    hora="10:00",
                    status="Agendado",
                    observacoes="campo pesado que nao deve entrar na agregacao",
                    paciente="Paciente legado",
                    tutor="Tutor legado",
                    telefone="85999990001",
                    servico="Servico legado",
                    clinica="Clinica legado",
                )
            )
            db.commit()
            statements.clear()

            query = db.query(Agendamento).filter(Agendamento.data >= "2026-05-01", Agendamento.data <= "2026-05-31")
            itens = relatorios._carregar_agendamentos_periodo_enxuto(query)
        finally:
            event.remove(engine, "before_cursor_execute", _capture_sql)

        try:
            self.assertEqual(len(itens), 1)
            self.assertEqual(itens[0].clinica_id, 7)
            self.assertEqual(itens[0].servico_id, 11)
            self.assertEqual(itens[0].status, "Agendado")

            select_agendamento = next(
                (sql for sql in statements if "select" in sql and "from agendamentos" in sql),
                "",
            )
            self.assertTrue(select_agendamento)
            self.assertIn("agendamentos.id", select_agendamento)
            self.assertIn("agendamentos.clinica_id", select_agendamento)
            self.assertIn("agendamentos.servico_id", select_agendamento)
            self.assertIn("agendamentos.status", select_agendamento)
            self.assertIn("agendamentos.inicio", select_agendamento)
            self.assertIn("agendamentos.fim", select_agendamento)
            self.assertIn("agendamentos.created_at", select_agendamento)
            self.assertNotIn("agendamentos.observacoes", select_agendamento)
            self.assertNotIn("agendamentos.paciente", select_agendamento)
            self.assertNotIn("agendamentos.tutor", select_agendamento)
            self.assertNotIn("agendamentos.telefone", select_agendamento)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
