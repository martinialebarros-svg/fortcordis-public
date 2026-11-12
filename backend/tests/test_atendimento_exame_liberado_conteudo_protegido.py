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
os.environ.setdefault("SECRET_KEY", "atendimento-exame-liberado-conteudo-protegido-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico, ExameAjuste
from app.models.laudo import Exame
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.schemas.atendimento import ExameSolicitacaoPayload


class AtendimentoExameLiberadoConteudoProtegidoTest(unittest.TestCase):
    """Achado #25 da auditoria: _derivar_status_exame preserva o status
    'Liberado no portal' durante o save, mas resultado/valor_referencia/
    unidade do MESMO exame continuavam sendo sobrescritos incondicionalmente
    a cada PUT - o conteudo que a clinica parceira/tutor ja visualizou podia
    mudar silenciosamente, sem nova notificacao nem trilha de quem alterou."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-exame-liberado-conteudo.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (AtendimentoClinico.__table__, Exame.__table__, AnexoAtendimento.__table__, ExameAjuste.__table__, PortalClinicExamLink.__table__, PortalClinicTrustedDevice.__table__):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=1, nome="Dr Teste")

        self.atendimento = AtendimentoClinico(
            paciente_id=100,
            veterinario_id=1,
            especie="Canina",
            data_atendimento=datetime(2026, 7, 5, 9, 30),
            status="Concluido",
        )
        self.db.add(self.atendimento)
        self.db.flush()

        self.exame = Exame(
            atendimento_id=self.atendimento.id,
            paciente_id=100,
            tipo_exame="Ecocardiograma",
            status=PORTAL_RELEASED_STATUS,
            resultado="FE 55%, sem alteracoes significativas.",
            valor_referencia="FE normal: 50-65%",
            unidade="%",
        )
        self.db.add(self.exame)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def test_autosave_com_exame_liberado_nao_sobrescreve_resultado(self) -> None:
        payload = ExameSolicitacaoPayload(
            id=self.exame.id,
            tipo_exame="Ecocardiograma",
            resultado="FE 30%, disfuncao severa.",
            valor_referencia="outro valor",
            unidade="mL",
        )
        atendimento._sync_exames(self.db, self.atendimento, [payload], self.user)
        self.db.commit()
        self.db.refresh(self.exame)

        self.assertEqual(self.exame.resultado, "FE 55%, sem alteracoes significativas.")
        self.assertEqual(self.exame.valor_referencia, "FE normal: 50-65%")
        self.assertEqual(self.exame.unidade, "%")
        self.assertEqual(self.exame.status, PORTAL_RELEASED_STATUS)

    def test_exame_nao_liberado_continua_aceitando_edicao_normal(self) -> None:
        exame_comum = Exame(
            atendimento_id=self.atendimento.id,
            paciente_id=100,
            tipo_exame="Hemograma",
            status="Concluido",
            resultado="Leucocitose leve.",
        )
        self.db.add(exame_comum)
        self.db.commit()

        payload = ExameSolicitacaoPayload(
            id=exame_comum.id,
            tipo_exame="Hemograma",
            resultado="Leucocitose leve, revisado.",
        )
        atendimento._sync_exames(self.db, self.atendimento, [payload], self.user)
        self.db.commit()
        self.db.refresh(exame_comum)

        self.assertEqual(exame_comum.resultado, "Leucocitose leve, revisado.")

    def test_apos_revogar_liberacao_conteudo_volta_a_ser_editavel(self) -> None:
        from unittest.mock import patch

        with patch.object(atendimento, "_auditar_transicao_exame_portal"):
            atendimento.revogar_liberacao_exame_no_portal(
                exame_id=self.exame.id, db=self.db, current_user=self.user
            )
        self.db.refresh(self.exame)
        self.assertNotEqual(self.exame.status, PORTAL_RELEASED_STATUS)

        payload = ExameSolicitacaoPayload(
            id=self.exame.id,
            tipo_exame="Ecocardiograma",
            resultado="FE 30%, disfuncao severa (revisado apos revogar).",
        )
        atendimento._sync_exames(self.db, self.atendimento, [payload], self.user)
        self.db.commit()
        self.db.refresh(self.exame)

        self.assertEqual(self.exame.resultado, "FE 30%, disfuncao severa (revisado apos revogar).")


if __name__ == "__main__":
    unittest.main()
