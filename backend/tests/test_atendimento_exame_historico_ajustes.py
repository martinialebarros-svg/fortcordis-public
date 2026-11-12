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
os.environ.setdefault("SECRET_KEY", "atendimento-exame-historico-ajustes-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import (
    AnexoAtendimento,
    AtendimentoClinico,
    DocumentoAtendimento,
    EvolucaoClinica,
    ExameAjuste,
    PrescricaoClinica,
    PrescricaoItem,
)
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.schemas.atendimento import AtendimentoCreatePayload, AtendimentoUpdatePayload, ExameSolicitacaoPayload


class AtendimentoExameHistoricoAjustesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-exame-historico-ajustes.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Exame.__table__,
            ExameAjuste.__table__,
            AnexoAtendimento.__table__,
            PrescricaoClinica.__table__,
            PrescricaoItem.__table__,
            EvolucaoClinica.__table__,
            DocumentoAtendimento.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=21, nome="Dra. Teste")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _seed_atendimento_com_exame(self) -> tuple[AtendimentoClinico, int]:
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Paciente Teste", especie="Canina", tutor_id=None, ativo=1)
        self.db.add_all([tutor, paciente])
        self.db.flush()
        paciente.tutor_id = tutor.id
        self.db.commit()

        with patch.object(atendimento, "registrar_auditoria"):
            resposta = atendimento.criar_atendimento(
                AtendimentoCreatePayload(
                    paciente_id=paciente.id,
                    exames=[
                        ExameSolicitacaoPayload(
                            tipo_exame="Hemograma",
                            resultado="Normal",
                            status="Concluido",
                        )
                    ],
                ),
                db=self.db,
                current_user=self.user,
            )

        registro = self.db.query(AtendimentoClinico).filter_by(id=resposta["id"]).first()
        exame_id = resposta["exames"][0]["id"]
        return registro, exame_id

    def test_editar_resultado_de_exame_existente_gera_historico(self) -> None:
        registro, exame_id = self._seed_atendimento_com_exame()

        with patch.object(atendimento, "registrar_auditoria"):
            resposta = atendimento.atualizar_atendimento(
                registro.id,
                AtendimentoUpdatePayload(
                    exames=[
                        ExameSolicitacaoPayload(
                            id=exame_id,
                            tipo_exame="Hemograma",
                            resultado="Leucocitose importante, sugestivo de processo infeccioso",
                            status="Concluido",
                        )
                    ]
                ),
                db=self.db,
                current_user=self.user,
            )

        ajustes = self.db.query(ExameAjuste).filter_by(exame_id=exame_id).all()
        campos_ajustados = {a.campo: (a.valor_anterior, a.valor_novo) for a in ajustes}
        self.assertEqual(
            campos_ajustados["resultado"],
            ("Normal", "Leucocitose importante, sugestivo de processo infeccioso"),
        )
        for ajuste in ajustes:
            self.assertEqual(ajuste.responsavel_id, self.user.id)
            self.assertEqual(ajuste.atendimento_id, registro.id)

        historico_exposto = resposta["exames"][0]["historico_ajustes"]
        self.assertTrue(any(item["campo"] == "resultado" for item in historico_exposto))

    def test_resave_sem_mudanca_nao_gera_historico(self) -> None:
        registro, exame_id = self._seed_atendimento_com_exame()

        with patch.object(atendimento, "registrar_auditoria"):
            atendimento.atualizar_atendimento(
                registro.id,
                AtendimentoUpdatePayload(
                    exames=[
                        ExameSolicitacaoPayload(
                            id=exame_id,
                            tipo_exame="Hemograma",
                            resultado="Normal",
                            status="Concluido",
                        )
                    ]
                ),
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(self.db.query(ExameAjuste).filter_by(exame_id=exame_id).count(), 0)


if __name__ == "__main__":
    unittest.main()
