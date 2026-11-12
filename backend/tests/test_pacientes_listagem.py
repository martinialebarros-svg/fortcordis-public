import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "pacientes-listagem-test-secret-key-1234567890")

from app.api.v1.endpoints import pacientes
from app.models.paciente import Paciente
from app.models.tutor import Tutor


class PacientesListagemTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "pacientes-listagem.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Tutor.__table__.create(engine, checkfirst=True)
        Paciente.__table__.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_busca_remota_retorna_paciente_ativo_e_preserva_total_da_carteira(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Rafael Caminha Geronimo", nome_key="rafael caminhha geronimo", ativo=1)
            db.add(tutor)
            db.flush()
            db.add_all(
                [
                    Paciente(nome="Bidu", nome_key="bidu", tutor_id=tutor.id, especie="Canina", ativo=1),
                    Paciente(nome="Rex", nome_key="rex", tutor_id=tutor.id, especie="Canina", ativo=1),
                    Paciente(nome="Rex inativo", nome_key="rex inativo", tutor_id=tutor.id, especie="Canina", ativo=0),
                ]
            )
            db.commit()

            resultado = pacientes.listar_pacientes(
                search="rex",
                limit=100,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(resultado["total_ativos"], 2)
            self.assertEqual(resultado["total"], 1)
            self.assertEqual([item["nome"] for item in resultado["items"]], ["Rex"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_busca_por_identificador_do_pet_ou_tutor_permanece_compativel(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Rafael", nome_key="rafael", ativo=1)
            db.add(tutor)
            db.flush()
            paciente = Paciente(nome="Rex", nome_key="rex", tutor_id=tutor.id, especie="Canina", ativo=1)
            db.add(paciente)
            db.commit()

            por_paciente = pacientes.listar_pacientes(
                search=str(paciente.id),
                limit=100,
                db=db,
                current_user=SimpleNamespace(id=1),
            )
            por_tutor = pacientes.listar_pacientes(
                search=str(tutor.id),
                limit=100,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual([item["id"] for item in por_paciente["items"]], [paciente.id])
            self.assertEqual([item["id"] for item in por_tutor["items"]], [paciente.id])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_filtro_exato_por_tutor_combina_com_busca_e_pagina_nomes_iguais(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            db.add_all(
                [
                    Tutor(id=1, nome="Ana", nome_key="ana", ativo=1),
                    Tutor(id=11, nome="Beatriz", nome_key="beatriz", ativo=1),
                ]
            )
            db.add_all(
                [
                    Paciente(id=20, nome="Rex", nome_key="rex", tutor_id=1, ativo=1),
                    Paciente(id=30, nome="Bidu", nome_key="bidu", tutor_id=1, ativo=1),
                    Paciente(id=40, nome="Rex inativo", nome_key="rex inativo", tutor_id=1, ativo=0),
                    Paciente(id=10, nome="Rex", nome_key="rex", tutor_id=11, ativo=1),
                ]
            )
            db.commit()

            def listar(**params):
                return pacientes.listar_pacientes(
                    db=db,
                    current_user=SimpleNamespace(id=1),
                    **params,
                )

            por_tutor = listar(tutor_id=1)
            self.assertEqual(por_tutor["total_ativos"], 3)
            self.assertEqual(por_tutor["total"], 2)
            self.assertEqual([item["id"] for item in por_tutor["items"]], [30, 20])

            busca_combinada = listar(tutor_id=1, search="rex")
            self.assertEqual(busca_combinada["total_ativos"], 3)
            self.assertEqual(busca_combinada["total"], 1)
            self.assertEqual([item["id"] for item in busca_combinada["items"]], [20])

            primeira_pagina = listar(search="rex", limit=1, skip=0)
            segunda_pagina = listar(search="rex", limit=1, skip=1)
            self.assertEqual(primeira_pagina["total"], 2)
            self.assertEqual([item["id"] for item in primeira_pagina["items"]], [10])
            self.assertEqual([item["id"] for item in segunda_pagina["items"]], [20])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
