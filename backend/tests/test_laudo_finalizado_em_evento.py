import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "laudo-finalizado-em-evento-test-secret-key-1234567890")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.laudo import Laudo


class LaudoFinalizadoEmEventoTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-finalizado-em-evento.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Laudo.__table__.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine)
        return tmpdir, engine, session_factory()

    def test_criacao_ja_finalizado_preenche_na_hora(self) -> None:
        tmpdir, engine, db = self._build_session()
        try:
            laudo = Laudo(
                paciente_id=1,
                veterinario_id=1,
                tipo="eletrocardiograma",
                titulo="Laudo teste",
                status="Finalizado",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)

            self.assertIsNotNone(laudo.finalizado_em)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criacao_como_rascunho_nao_preenche(self) -> None:
        tmpdir, engine, db = self._build_session()
        try:
            laudo = Laudo(
                paciente_id=1,
                veterinario_id=1,
                tipo="ecocardiograma",
                titulo="Laudo teste",
                status="Rascunho",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)

            self.assertIsNone(laudo.finalizado_em)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_transicao_rascunho_para_finalizado_preenche_uma_vez(self) -> None:
        tmpdir, engine, db = self._build_session()
        try:
            laudo = Laudo(
                paciente_id=1,
                veterinario_id=1,
                tipo="ecocardiograma",
                titulo="Laudo teste",
                status="Rascunho",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)
            self.assertIsNone(laudo.finalizado_em)

            laudo.status = "Finalizado"
            db.commit()
            db.refresh(laudo)
            primeiro_valor = laudo.finalizado_em
            self.assertIsNotNone(primeiro_valor)

            # Editar de novo (ainda Finalizado) nao deve mudar o valor.
            laudo.descricao = "Correcao de texto"
            db.commit()
            db.refresh(laudo)
            self.assertEqual(laudo.finalizado_em, primeiro_valor)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
