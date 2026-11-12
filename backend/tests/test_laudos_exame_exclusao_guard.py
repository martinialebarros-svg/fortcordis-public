import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "laudos-exame-exclusao-guard-test-secret-key-1234567890")

from app.api.v1.endpoints import laudos
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AnexoAtendimento
from app.models.laudo import Exame, Laudo


def _fake_request(method: str = "DELETE") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/exames/1",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


class LaudosExameExclusaoGuardTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudos-exame-exclusao-guard.db"
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (Exame.__table__, Laudo.__table__, AnexoAtendimento.__table__):
            table.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return tmpdir, session_factory(), engine

    def _user(self):
        return SimpleNamespace(id=1, nome="Dr Teste")

    def test_deletar_exame_com_laudo_vinculado_e_bloqueado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = Laudo(paciente_id=100, veterinario_id=1, tipo="exame", titulo="Laudo", status="Liberado")
            db.add(laudo)
            db.commit()
            exame = Exame(paciente_id=100, tipo_exame="Ecocardiograma", status="Solicitado", laudo_id=laudo.id)
            db.add(exame)
            db.commit()

            with self.assertRaises(HTTPException) as ctx:
                laudos.deletar_exame(
                    exame_id=exame.id, request=_fake_request(), db=db, current_user=self._user()
                )
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIsNotNone(db.query(Exame).filter(Exame.id == exame.id).first())
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_deletar_exame_liberado_no_portal_e_bloqueado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = Exame(paciente_id=100, tipo_exame="Ecocardiograma", status=PORTAL_RELEASED_STATUS)
            db.add(exame)
            db.commit()

            with self.assertRaises(HTTPException) as ctx:
                laudos.deletar_exame(
                    exame_id=exame.id, request=_fake_request(), db=db, current_user=self._user()
                )
            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_deletar_exame_com_anexos_e_bloqueado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = Exame(paciente_id=100, tipo_exame="Ecocardiograma", status="Solicitado")
            db.add(exame)
            db.commit()
            anexo = AnexoAtendimento(
                atendimento_id=1, exame_id=exame.id, tipo="resultado", url="/x.pdf", origem="upload"
            )
            db.add(anexo)
            db.commit()

            with self.assertRaises(HTTPException) as ctx:
                laudos.deletar_exame(
                    exame_id=exame.id, request=_fake_request(), db=db, current_user=self._user()
                )
            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_deletar_exame_sem_bloqueios_exclui_e_audita(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = Exame(paciente_id=100, tipo_exame="Hemograma", status="Concluido")
            db.add(exame)
            db.commit()
            exame_id = exame.id

            with patch.object(laudos, "registrar_auditoria") as auditoria_mock:
                resposta = laudos.deletar_exame(
                    exame_id=exame_id, request=_fake_request(), db=db, current_user=self._user()
                )

            self.assertEqual(resposta["message"], "Exame removido com sucesso")
            self.assertIsNone(db.query(Exame).filter(Exame.id == exame_id).first())
            self.assertEqual(auditoria_mock.call_count, 1)
            self.assertEqual(auditoria_mock.call_args.kwargs["acao"], "EXAME_EXCLUIDO")
            self.assertEqual(auditoria_mock.call_args.kwargs["entidade_id"], exame_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_atualizar_exame_ignora_atendimento_id(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = Exame(paciente_id=100, tipo_exame="Hemograma", status="Solicitado", atendimento_id=None)
            db.add(exame)
            db.commit()

            with patch.object(laudos, "registrar_auditoria"):
                atualizado = laudos.atualizar_exame(
                    exame_id=exame.id,
                    exame_data={"atendimento_id": 999, "resultado": "Normal"},
                    request=_fake_request("PUT"),
                    db=db,
                    current_user=self._user(),
                )

            self.assertIsNone(atualizado.atendimento_id)
            self.assertEqual(atualizado.resultado, "Normal")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_atualizar_exame_ignora_liberacao_direta_no_portal(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = Exame(paciente_id=100, tipo_exame="Hemograma", status="Solicitado")
            db.add(exame)
            db.commit()

            with patch.object(laudos, "registrar_auditoria"):
                atualizado = laudos.atualizar_exame(
                    exame_id=exame.id,
                    exame_data={"status": PORTAL_RELEASED_STATUS},
                    request=_fake_request("PUT"),
                    db=db,
                    current_user=self._user(),
                )

            self.assertEqual(atualizado.status, "Solicitado")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_atualizar_exame_permite_outras_transicoes_de_status_e_audita(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = Exame(paciente_id=100, tipo_exame="Hemograma", status="Solicitado")
            db.add(exame)
            db.commit()

            with patch.object(laudos, "registrar_auditoria") as auditoria_mock:
                atualizado = laudos.atualizar_exame(
                    exame_id=exame.id,
                    exame_data={"status": "Concluido"},
                    request=_fake_request("PUT"),
                    db=db,
                    current_user=self._user(),
                )

            self.assertEqual(atualizado.status, "Concluido")
            self.assertEqual(auditoria_mock.call_count, 1)
            self.assertEqual(auditoria_mock.call_args.kwargs["acao"], "EXAME_ATUALIZADO")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
