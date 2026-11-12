import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-list-n-plus-one-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AtendimentoClinico, PrescricaoClinica
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.tutor import Tutor


class AtendimentoListNPlusOneTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "atendimento-list-n-plus-one.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Exame.__table__,
            PrescricaoClinica.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_data(self, db):
        tutor = Tutor(nome="Maria Tutora", telefone="85999990001", ativo=1)
        paciente = Paciente(nome="Luna", especie="Canina", tutor_id=1, ativo=1)
        clinica = Clinica(nome="Clinica Centro", ativo=True)
        db.add_all([tutor, paciente, clinica])
        db.flush()
        paciente.tutor_id = tutor.id

        atendimentos = [
            AtendimentoClinico(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=clinica.id,
                veterinario_id=10,
                especie="Canina",
                data_atendimento=datetime(2026, 5, 10, 9, 0),
                status="Agendado",
                criado_por_id=10,
                criado_por_nome="Dr. Teste",
                created_at=datetime(2026, 5, 10, 9, 0),
            ),
            AtendimentoClinico(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=clinica.id,
                veterinario_id=10,
                especie="Canina",
                data_atendimento=datetime(2026, 5, 11, 9, 0),
                status="Confirmado",
                criado_por_id=10,
                criado_por_nome="Dr. Teste",
                created_at=datetime(2026, 5, 11, 9, 0),
            ),
            AtendimentoClinico(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=clinica.id,
                veterinario_id=10,
                especie="Canina",
                data_atendimento=datetime(2026, 5, 12, 9, 0),
                status="Realizado",
                criado_por_id=10,
                criado_por_nome="Dr. Teste",
                created_at=datetime(2026, 5, 12, 9, 0),
            ),
        ]
        db.add_all(atendimentos)
        db.flush()

        db.add_all(
            [
                Exame(
                    atendimento_id=atendimentos[0].id,
                    paciente_id=paciente.id,
                    tipo_exame="Hemograma",
                    status="Solicitado",
                ),
                Exame(
                    atendimento_id=atendimentos[0].id,
                    paciente_id=paciente.id,
                    tipo_exame="Bioquimica",
                    status="Solicitado",
                ),
                Exame(
                    atendimento_id=atendimentos[1].id,
                    paciente_id=paciente.id,
                    tipo_exame="Raio-X",
                    status="Solicitado",
                ),
            ]
        )
        db.add(PrescricaoClinica(atendimento_id=atendimentos[1].id, orientacoes_gerais="Repouso"))
        db.commit()
        return atendimentos

    def test_listar_atendimentos_carrega_exames_e_prescricao_em_lote(self) -> None:
        tmpdir, db, engine = self._build_session()
        statements = []

        def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", _capture_sql)
        try:
            atendimentos = self._seed_data(db)
            resultado = atendimento.listar_atendimentos(
                skip=0,
                limit=50,
                db=db,
                current_user=SimpleNamespace(id=1),
            )
        finally:
            event.remove(engine, "before_cursor_execute", _capture_sql)

        try:
            self.assertEqual(resultado["total"], 3)
            self.assertEqual(len(resultado["items"]), 3)

            items_por_id = {item["id"]: item for item in resultado["items"]}
            self.assertEqual(items_por_id[atendimentos[0].id]["total_exames"], 2)
            self.assertFalse(items_por_id[atendimentos[0].id]["tem_prescricao"])
            self.assertEqual(items_por_id[atendimentos[1].id]["total_exames"], 1)
            self.assertTrue(items_por_id[atendimentos[1].id]["tem_prescricao"])
            self.assertEqual(items_por_id[atendimentos[2].id]["total_exames"], 0)
            self.assertFalse(items_por_id[atendimentos[2].id]["tem_prescricao"])

            exame_selects = [sql for sql in statements if "exames" in sql and "count(" in sql]
            prescricao_selects = [
                sql for sql in statements if "prescricoes_clinicas" in sql and "distinct" in sql
            ]
            self.assertEqual(len(exame_selects), 1)
            self.assertEqual(len(prescricao_selects), 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
