import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "alertas-internos-test-secret-key-1234567890")

from app.api.v1.endpoints import alertas_internos
from app.models.alerta_interno import AlertaInterno
from app.services.alerta_interno_service import criar_alerta_interno


def _fake_user(id_=1, nome="Ana Recepcao"):
    return SimpleNamespace(id=id_, nome=nome)


class AlertasInternosTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "alertas-internos.db"
        engine = create_engine(f"sqlite:///{db_path}")
        AlertaInterno.__table__.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_criar_e_listar_apenas_nao_lidos_por_padrao(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            criar_alerta_interno(
                db,
                tipo="agendamento_cancelado_portal",
                titulo="Cancelamento pelo portal: Clinica X",
                mensagem="A clinica X cancelou o agendamento #1 pelo portal.",
                entidade_tipo="agendamento",
                entidade_id=1,
                clinica_id=10,
            )
            db.commit()

            resposta = alertas_internos.listar_alertas_internos(
                incluir_lidos=False,
                limit=50,
                db=db,
                current_user=_fake_user(),
            )
            self.assertEqual(resposta.total_nao_lidos, 1)
            self.assertEqual(len(resposta.items), 1)
            self.assertEqual(resposta.items[0].titulo, "Cancelamento pelo portal: Clinica X")
            self.assertEqual(resposta.items[0].clinica_id, 10)
            self.assertFalse(resposta.items[0].lido)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_marcar_lido_remove_da_lista_de_nao_lidos(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            alerta = criar_alerta_interno(db, tipo="teste", titulo="Titulo", mensagem="Mensagem")
            db.commit()
            db.refresh(alerta)

            resultado = alertas_internos.marcar_alerta_interno_lido(
                alerta.id,
                db=db,
                current_user=_fake_user(id_=7, nome="Ana Recepcao"),
            )
            self.assertTrue(resultado.lido)
            self.assertEqual(resultado.lido_por_nome, "Ana Recepcao")

            resposta = alertas_internos.listar_alertas_internos(
                incluir_lidos=False, limit=50, db=db, current_user=_fake_user()
            )
            self.assertEqual(resposta.total_nao_lidos, 0)
            self.assertEqual(len(resposta.items), 0)

            resposta_com_lidos = alertas_internos.listar_alertas_internos(
                incluir_lidos=True, limit=50, db=db, current_user=_fake_user()
            )
            self.assertEqual(len(resposta_com_lidos.items), 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_marcar_todos_lidos(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            criar_alerta_interno(db, tipo="teste", titulo="A", mensagem="A")
            criar_alerta_interno(db, tipo="teste", titulo="B", mensagem="B")
            db.commit()

            alertas_internos.marcar_todos_alertas_internos_lidos(db=db, current_user=_fake_user())

            resposta = alertas_internos.listar_alertas_internos(
                incluir_lidos=False, limit=50, db=db, current_user=_fake_user()
            )
            self.assertEqual(resposta.total_nao_lidos, 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_marcar_lido_de_alerta_inexistente_retorna_404(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            with self.assertRaises(HTTPException) as ctx:
                alertas_internos.marcar_alerta_interno_lido(999999, db=db, current_user=_fake_user())
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
