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
os.environ.setdefault("SECRET_KEY", "tutor-busca-ativo-legado-secret-key-1234567890")

from app.api.v1.endpoints import tutores
from app.models.paciente import Paciente
from app.models.tutor import Tutor


class TutorBuscaComAtivoLegadoTest(unittest.TestCase):
    """Regressao: tutor com `ativo` NULL (registro legado) precisa continuar
    aparecendo na listagem/busca de /tutores, assim como ja aparece via join
    a partir da busca de pacientes."""

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "tutor-busca-ativo-legado.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Tutor.__table__.create(engine, checkfirst=True)
        Paciente.__table__.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_listar_tutores_inclui_tutor_com_ativo_nulo(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Genival Filho", ativo=None)
            db.add(tutor)
            db.commit()
            db.refresh(tutor)

            db.add(Paciente(nome="Maya", tutor_id=tutor.id, especie="Canina", raca="American Bully", ativo=1))
            db.commit()

            resultado = tutores.listar_tutores(
                busca="genival",
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            nomes = [item["nome"] for item in resultado["items"]]
            self.assertIn("Genival Filho", nomes)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_panorama_tutor_funciona_com_ativo_nulo(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Genival Filho", ativo=None)
            db.add(tutor)
            db.commit()
            db.refresh(tutor)

            response = tutores.obter_panorama_tutor(
                tutor.id,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(response["tutor"]["id"], tutor.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
