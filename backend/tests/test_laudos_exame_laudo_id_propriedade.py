import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "laudos-exame-laudo-id-propriedade-test-secret-key-1234567890")

from app.api.v1.endpoints import laudos
from app.models.laudo import Exame, Laudo


def _fake_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/v1/exames/1",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


class LaudosExameLaudoIdPropriedadeTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudos-exame-laudo-id.db"
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (Exame.__table__, Laudo.__table__):
            table.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return tmpdir, session_factory(), engine

    def test_criar_exame_com_laudo_de_outro_paciente_ignora_o_vinculo(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo_paciente_b = Laudo(
                paciente_id=200, veterinario_id=1, tipo="exame", titulo="Laudo B", status="Liberado"
            )
            db.add(laudo_paciente_b)
            db.commit()

            exame = laudos.criar_exame(
                exame_data={
                    "paciente_id": 100,
                    "tipo_exame": "Ecocardiograma",
                    "laudo_id": laudo_paciente_b.id,
                },
                db=db,
                current_user=SimpleNamespace(id=1, nome="Dr Teste"),
            )

            self.assertIsNone(exame.laudo_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_exame_com_laudo_do_mesmo_paciente_e_aceito(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo_paciente_a = Laudo(
                paciente_id=100, veterinario_id=1, tipo="exame", titulo="Laudo A", status="Liberado"
            )
            db.add(laudo_paciente_a)
            db.commit()

            exame = laudos.criar_exame(
                exame_data={
                    "paciente_id": 100,
                    "tipo_exame": "Ecocardiograma",
                    "laudo_id": laudo_paciente_a.id,
                },
                db=db,
                current_user=SimpleNamespace(id=1, nome="Dr Teste"),
            )

            self.assertEqual(exame.laudo_id, laudo_paciente_a.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_atualizar_exame_com_laudo_de_outro_paciente_e_ignorado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = Exame(paciente_id=100, tipo_exame="Ecocardiograma", status="Solicitado")
            laudo_paciente_b = Laudo(
                paciente_id=200, veterinario_id=1, tipo="exame", titulo="Laudo B", status="Liberado"
            )
            db.add_all([exame, laudo_paciente_b])
            db.commit()

            with patch.object(laudos, "registrar_auditoria"):
                atualizado = laudos.atualizar_exame(
                    exame_id=exame.id,
                    exame_data={"laudo_id": laudo_paciente_b.id},
                    request=_fake_request(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Dr Teste"),
                )

            self.assertIsNone(atualizado.laudo_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_atualizar_exame_com_laudo_do_mesmo_paciente_e_aceito(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = Exame(paciente_id=100, tipo_exame="Ecocardiograma", status="Solicitado")
            laudo_paciente_a = Laudo(
                paciente_id=100, veterinario_id=1, tipo="exame", titulo="Laudo A", status="Liberado"
            )
            db.add_all([exame, laudo_paciente_a])
            db.commit()

            with patch.object(laudos, "registrar_auditoria"):
                atualizado = laudos.atualizar_exame(
                    exame_id=exame.id,
                    exame_data={"laudo_id": laudo_paciente_a.id},
                    request=_fake_request(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Dr Teste"),
                )

            self.assertEqual(atualizado.laudo_id, laudo_paciente_a.id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
