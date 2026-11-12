import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-observacoes-portal-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico, ExameAjuste
from app.models.laudo import Exame
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.schemas.atendimento import ExameSolicitacaoPayload


class AtendimentoObservacoesPortalPreservadasTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "atendimento-observacoes-portal.db"
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (AtendimentoClinico.__table__, Exame.__table__, AnexoAtendimento.__table__, ExameAjuste.__table__, PortalClinicExamLink.__table__, PortalClinicTrustedDevice.__table__):
            table.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return tmpdir, session_factory(), engine

    def _seed_exam(self, db, observacoes_originais, tmpdir):
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
            tipo_exame="Hemograma",
            categoria_exame="",
            prioridade="Rotina",
            status="Concluido",
            data_solicitacao=datetime(2026, 7, 5, 9, 30),
            data_resultado=datetime(2026, 7, 5, 10, 0),
            observacoes=observacoes_originais,
        )
        db.add(exame)
        db.flush()
        # achado #20 da auditoria: liberar no portal agora exige que o anexo
        # tenha uma fonte de download REAL (attachment_has_download_source) -
        # o arquivo precisa existir de fato no caminho declarado.
        caminho_arquivo = str(Path(tmpdir.name) / "hemograma.pdf")
        Path(caminho_arquivo).write_bytes(b"%PDF-1.4 fake pdf content for test")
        db.add(
            AnexoAtendimento(
                atendimento_id=atendimento_item.id,
                exame_id=exame.id,
                tipo="resultado_exame",
                descricao="PDF do resultado",
                url="/api/v1/atendimentos/anexos/1/arquivo",
                nome_original="hemograma.pdf",
                tamanho=1024,
                mime_type="application/pdf",
                caminho_arquivo=caminho_arquivo,
                origem="upload",
            )
        )
        db.commit()
        return exame

    def test_revogar_restaura_o_texto_original_das_observacoes(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            texto_original = "Coleta dificultada, paciente agitado; repetir se resultado inconsistente."
            exame = self._seed_exam(db, texto_original, tmpdir)
            user = SimpleNamespace(id=99, nome="Dr Teste")

            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.liberar_exame_no_portal(exame_id=exame.id, db=db, current_user=user)

            db.refresh(exame)
            self.assertEqual(exame.observacoes, atendimento.PORTAL_EXAME_RELEASE_MESSAGE)
            self.assertEqual(exame.observacoes_pre_portal, texto_original)

            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.revogar_liberacao_exame_no_portal(exame_id=exame.id, db=db, current_user=user)

            db.refresh(exame)
            self.assertEqual(exame.observacoes, texto_original)
            self.assertIsNone(exame.observacoes_pre_portal)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_revogar_com_observacoes_originais_vazias_restaura_vazio(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            exame = self._seed_exam(db, "", tmpdir)
            user = SimpleNamespace(id=99, nome="Dr Teste")

            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.liberar_exame_no_portal(exame_id=exame.id, db=db, current_user=user)
            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.revogar_liberacao_exame_no_portal(exame_id=exame.id, db=db, current_user=user)

            db.refresh(exame)
            self.assertEqual(exame.observacoes, "")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_autosave_entre_liberar_e_revogar_nao_perde_o_texto_original(self) -> None:
        # Cenario reproduzido pela revisao adversarial: um save/autosave do
        # atendimento (via _sync_exames) enquanto o exame esta liberado no
        # portal nao pode sobrescrever a mensagem fixa nem perder o backup em
        # observacoes_pre_portal.
        tmpdir, db, engine = self._build_session()
        try:
            texto_original = "Coleta dificultada, paciente agitado; repetir se resultado inconsistente."
            exame = self._seed_exam(db, texto_original, tmpdir)
            atendimento_item = db.query(AtendimentoClinico).filter_by(id=exame.atendimento_id).first()
            user = SimpleNamespace(id=99, nome="Dr Teste")

            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.liberar_exame_no_portal(exame_id=exame.id, db=db, current_user=user)
            db.refresh(exame)

            payload = ExameSolicitacaoPayload(
                id=exame.id,
                tipo_exame=exame.tipo_exame,
                resultado="Texto de autosave, diferente do original.",
                observacoes="Observacao digitada durante o autosave.",
            )
            atendimento._sync_exames(db, atendimento_item, [payload], user)
            db.commit()
            db.refresh(exame)

            self.assertEqual(exame.status, atendimento.PORTAL_RELEASED_STATUS)
            self.assertEqual(exame.observacoes, atendimento.PORTAL_EXAME_RELEASE_MESSAGE)
            self.assertEqual(exame.observacoes_pre_portal, texto_original)

            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.revogar_liberacao_exame_no_portal(exame_id=exame.id, db=db, current_user=user)
            db.refresh(exame)

            self.assertEqual(exame.observacoes, texto_original)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_liberar_duas_vezes_seguidas_e_idempotente_e_preserva_o_backup(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            texto_original = "Texto original importante do exame."
            exame = self._seed_exam(db, texto_original, tmpdir)
            user = SimpleNamespace(id=99, nome="Dr Teste")

            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.liberar_exame_no_portal(exame_id=exame.id, db=db, current_user=user)
                atendimento.liberar_exame_no_portal(exame_id=exame.id, db=db, current_user=user)
            db.refresh(exame)

            self.assertEqual(exame.observacoes_pre_portal, texto_original)

            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.revogar_liberacao_exame_no_portal(exame_id=exame.id, db=db, current_user=user)
            db.refresh(exame)

            self.assertEqual(exame.observacoes, texto_original)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
