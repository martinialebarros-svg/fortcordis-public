import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-exclusao-anexo-guard-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.laudo import Exame


class AtendimentoExclusaoAnexoGuardTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "atendimento-exclusao-anexo-guard.db"
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (AtendimentoClinico.__table__, Exame.__table__, AnexoAtendimento.__table__):
            table.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return tmpdir, session_factory(), engine

    def _seed(self, db, *, status_exame, anexos):
        atendimento_item = AtendimentoClinico(
            paciente_id=182,
            tutor_id=44,
            clinica_id=8,
            veterinario_id=77,
            especie="Canina",
            data_atendimento=datetime(2026, 7, 5, 9, 30),
            status="Concluido",
            criado_por_id=77,
            criado_por_nome="Vet Teste",
        )
        db.add(atendimento_item)
        db.flush()

        exame = Exame(
            atendimento_id=atendimento_item.id,
            paciente_id=atendimento_item.paciente_id,
            tipo_exame="Eletrocardiograma",
            categoria_exame="Cardiologia",
            prioridade="Rotina",
            status=status_exame,
            data_solicitacao=datetime(2026, 7, 5, 9, 30),
        )
        db.add(exame)
        db.flush()

        criados = []
        for nome, mime in anexos:
            anexo = AnexoAtendimento(
                atendimento_id=atendimento_item.id,
                exame_id=exame.id,
                tipo="resultado_exame",
                url=f"/api/v1/atendimentos/anexos/{nome}/arquivo",
                nome_original=nome,
                tamanho=1024,
                mime_type=mime,
                caminho_arquivo=f"/tmp/{nome}",
                origem="upload",
            )
            db.add(anexo)
            criados.append(anexo)
        db.commit()
        return exame, criados

    def test_bloqueia_exclusao_do_unico_pdf_de_exame_liberado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame, anexos = self._seed(
                db, status_exame=PORTAL_RELEASED_STATUS, anexos=[("ecg.pdf", "application/pdf")]
            )
            anexo_id = anexos[0].id

            with self.assertRaises(HTTPException) as ctx:
                atendimento.excluir_anexo(
                    anexo_id=anexo_id, db=db, current_user=SimpleNamespace(id=1, nome="Dr Teste")
                )

            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual(db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo_id).count(), 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_permite_exclusao_quando_ha_outro_pdf_no_mesmo_exame(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame, anexos = self._seed(
                db,
                status_exame=PORTAL_RELEASED_STATUS,
                anexos=[("ecg-v1.pdf", "application/pdf"), ("ecg-v2.pdf", "application/pdf")],
            )
            anexo_id = anexos[0].id

            resultado = atendimento.excluir_anexo(
                anexo_id=anexo_id, db=db, current_user=SimpleNamespace(id=1, nome="Dr Teste")
            )

            self.assertEqual(resultado["id"], anexo_id)
            self.assertEqual(db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo_id).count(), 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_permite_exclusao_de_pdf_de_exame_nao_liberado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame, anexos = self._seed(
                db, status_exame="Concluido", anexos=[("ecg.pdf", "application/pdf")]
            )
            anexo_id = anexos[0].id

            resultado = atendimento.excluir_anexo(
                anexo_id=anexo_id, db=db, current_user=SimpleNamespace(id=1, nome="Dr Teste")
            )

            self.assertEqual(resultado["id"], anexo_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
