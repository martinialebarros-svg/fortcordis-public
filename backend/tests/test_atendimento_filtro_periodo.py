import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-filtro-periodo-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AtendimentoClinico, PrescricaoClinica
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.tutor import Tutor


class AtendimentoFiltroPeriodoTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "atendimento-filtro-periodo.db"
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

        def _novo(data_atendimento):
            return AtendimentoClinico(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=clinica.id,
                veterinario_id=10,
                especie="Canina",
                data_atendimento=data_atendimento,
                status="Realizado",
                criado_por_id=10,
                criado_por_nome="Dr. Teste",
                created_at=data_atendimento,
            )

        dentro_do_periodo = _novo(datetime(2026, 8, 3, 23, 59, 59))
        no_dia_seguinte = _novo(datetime(2026, 8, 4, 0, 0, 1))
        db.add_all([dentro_do_periodo, no_dia_seguinte])
        db.commit()
        return dentro_do_periodo, no_dia_seguinte

    def test_filtro_data_fim_nao_inclui_o_dia_seguinte(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            dentro_do_periodo, no_dia_seguinte = self._seed_data(db)

            resultado = atendimento.listar_atendimentos(
                data_fim="2026-08-03T23:59:59",
                skip=0,
                limit=50,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            ids_retornados = {item["id"] for item in resultado["items"]}
            self.assertIn(dentro_do_periodo.id, ids_retornados)
            self.assertNotIn(no_dia_seguinte.id, ids_retornados)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_filtro_data_fim_inclui_ate_23_59_59_do_proprio_dia(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            dentro_do_periodo, _no_dia_seguinte = self._seed_data(db)

            resultado = atendimento.listar_atendimentos(
                data_inicio="2026-08-03T00:00:00",
                data_fim="2026-08-03T23:59:59",
                skip=0,
                limit=50,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(resultado["total"], 1)
            self.assertEqual(resultado["items"][0]["id"], dentro_do_periodo.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
