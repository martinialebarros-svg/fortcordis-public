import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-n-plus-one-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor


class AgendaNPlusOneTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-n-plus-one.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Agendamento.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            Configuracao.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_data(self, db):
        tutor = Tutor(nome="Maria Oliveira", telefone="85999990001", ativo=1)
        db.add(tutor)
        db.flush()

        paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
        clinica = Clinica(nome="Pet Center", ativo=True)
        servico = Servico(nome="Ecocardiograma", ativo=True)
        db.add_all([paciente, clinica, servico])
        db.flush()

        base_data = datetime(2026, 7, 15)
        for idx in range(5):
            inicio = base_data.replace(hour=9 + idx, minute=0, second=0, microsecond=0)
            db.add(
                Agendamento(
                    paciente_id=paciente.id,
                    clinica_id=clinica.id,
                    servico_id=servico.id,
                    inicio=inicio,
                    fim=inicio,
                    data=inicio.strftime("%Y-%m-%d"),
                    hora=inicio.strftime("%H:%M"),
                    status="Agendado",
                )
            )
        db.commit()

    def test_listar_agendamentos_nao_faz_query_por_item_relacionado(self) -> None:
        tmpdir, db, engine = self._build_session()
        statements = []

        def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", _capture_sql)
        try:
            self._seed_data(db)
            statements.clear()

            with patch.object(agenda, "_ensure_agendamento_workflow_columns") as schema_compat:
                resultado = agenda.listar_agendamentos(
                    data_inicio="2026-07-01",
                    data_fim="2026-07-31",
                    limit=50,
                    skip=0,
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )
            schema_compat.assert_not_called()
        finally:
            event.remove(engine, "before_cursor_execute", _capture_sql)

        try:
            self.assertEqual(resultado["total"], 5)
            self.assertEqual(len(resultado["items"]), 5)

            joined_selects = [
                sql
                for sql in statements
                if "select" in sql
                and "from agendamentos" in sql
                and "join pacientes" in sql
                and "join clinicas" in sql
                and "join servicos" in sql
                and "join tutores" in sql
            ]
            self.assertGreaterEqual(len(joined_selects), 1)

            count_sem_joins = [
                sql
                for sql in statements
                if "select count" in sql
                and "from agendamentos" in sql
                and "join" not in sql
            ]
            self.assertGreaterEqual(
                len(count_sem_joins),
                1,
                msg="COUNT da lista deve ocorrer sem joins para reduzir custo em períodos amplos.",
            )

            select_statements = [
                sql
                for sql in statements
                if "select" in sql
                and "sqlite_master" not in sql
                and not sql.lstrip().startswith("pragma ")
            ]
            self.assertLessEqual(
                len(select_statements),
                4,
                msg=f"Lista da Agenda deve usar no maximo quatro SELECTs, obtido: {len(select_statements)}",
            )

            lazy_related_selects = [
                sql
                for sql in statements
                if "select" in sql
                and (
                    ("from pacientes" in sql)
                    or ("from tutores" in sql)
                    or ("from clinicas" in sql)
                    or ("from servicos" in sql)
                )
                and "join" not in sql
            ]
            self.assertEqual(lazy_related_selects, [])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
