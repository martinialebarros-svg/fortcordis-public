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
os.environ.setdefault("SECRET_KEY", "atendimento-conteudo-clinico-auditoria-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import (
    AnexoAtendimento,
    AtendimentoClinico,
    DocumentoAtendimento,
    EvolucaoClinica,
    PrescricaoClinica,
    PrescricaoItem,
)
from app.models.clinica import Clinica
from app.models.laudo import Exame
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.schemas.atendimento import AtendimentoUpdatePayload, DiagnosticoPayload, TriagemPayload


class AtendimentoConteudoClinicoAuditoriaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-conteudo-clinico-auditoria.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Agendamento.__table__,
            AtendimentoClinico.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            PrescricaoClinica.__table__,
            PrescricaoItem.__table__,
            EvolucaoClinica.__table__,
            DocumentoAtendimento.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=17, nome="Dra. Teste")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _seed_atendimento(self, **campos) -> AtendimentoClinico:
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Paciente Teste", especie="Canina", tutor_id=None, ativo=1)
        clinica = Clinica(nome="Clinica Teste")
        self.db.add_all([tutor, paciente, clinica])
        self.db.flush()
        paciente.tutor_id = tutor.id
        item = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=datetime(2026, 7, 29, 14, 30),
            status="Em atendimento",
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
            diagnostico_principal="Suspeita de cardiomiopatia dilatada",
            **campos,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def test_alterar_diagnostico_gera_auditoria_com_antes_e_depois(self) -> None:
        item = self._seed_atendimento()

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            atendimento.atualizar_atendimento(
                item.id,
                AtendimentoUpdatePayload(
                    diagnostico=DiagnosticoPayload(diagnostico_principal="Descartada cardiomiopatia")
                ),
                db=self.db,
                current_user=self.user,
            )

        chamadas = [
            call for call in auditoria_mock.call_args_list
            if call.kwargs["acao"] == "ATENDIMENTO_CONTEUDO_CLINICO_ATUALIZADO"
        ]
        self.assertEqual(len(chamadas), 1)
        alteracoes = chamadas[0].kwargs["detalhes"]["alteracoes"]
        self.assertEqual(
            alteracoes["diagnostico_principal"],
            {"antes": "Suspeita de cardiomiopatia dilatada", "depois": "Descartada cardiomiopatia"},
        )
        self.assertNotIn("queixa_principal", alteracoes)

    def test_alterar_triagem_gera_auditoria(self) -> None:
        item = self._seed_atendimento(peso=10.0)

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            atendimento.atualizar_atendimento(
                item.id,
                AtendimentoUpdatePayload(triagem=TriagemPayload(peso=12.5)),
                db=self.db,
                current_user=self.user,
            )

        chamadas = [
            call for call in auditoria_mock.call_args_list
            if call.kwargs["acao"] == "ATENDIMENTO_CONTEUDO_CLINICO_ATUALIZADO"
        ]
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(chamadas[0].kwargs["detalhes"]["alteracoes"]["peso"], {"antes": 10.0, "depois": 12.5})

    def test_alterar_clinica_tambem_deixa_historico(self) -> None:
        item = self._seed_atendimento()
        outra_clinica = Clinica(nome="Outra Clinica")
        self.db.add(outra_clinica)
        self.db.commit()

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            atendimento.atualizar_atendimento(
                item.id,
                AtendimentoUpdatePayload(clinica_id=outra_clinica.id),
                db=self.db,
                current_user=self.user,
            )

        chamadas = [
            call for call in auditoria_mock.call_args_list
            if call.kwargs["acao"] == "ATENDIMENTO_CONTEUDO_CLINICO_ATUALIZADO"
        ]
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(chamadas[0].kwargs["detalhes"]["alteracoes"]["clinica_id"]["depois"], outra_clinica.id)


if __name__ == "__main__":
    unittest.main()
