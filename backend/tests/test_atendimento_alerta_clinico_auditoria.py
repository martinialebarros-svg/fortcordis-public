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
os.environ.setdefault("SECRET_KEY", "atendimento-alerta-clinico-auditoria-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import AlertaClinico
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.schemas.atendimento import AlertaPayload


def _fake_request(method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/atendimentos/alertas",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


class AtendimentoAlertaClinicoAuditoriaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-alerta-clinico-auditoria.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (Tutor.__table__, Paciente.__table__, AlertaClinico.__table__):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=9, nome="Dr Teste")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _seed_paciente(self) -> Paciente:
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Rex", especie="Canina", tutor_id=None, ativo=1)
        self.db.add_all([tutor, paciente])
        self.db.flush()
        paciente.tutor_id = tutor.id
        self.db.commit()
        return paciente

    def test_criar_alerta_e_auditado(self) -> None:
        paciente = self._seed_paciente()

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            resposta = atendimento.criar_alerta(
                paciente.id,
                AlertaPayload(tipo="alergia", titulo="Alergia a penicilina", gravidade="alta"),
                request=_fake_request(),
                db=self.db,
                current_user=self.user,
            )

        auditoria_mock.assert_called_once()
        kwargs = auditoria_mock.call_args.kwargs
        self.assertEqual(kwargs["acao"], "ALERTA_CLINICO_CRIADO")
        self.assertEqual(kwargs["entidade_id"], resposta["id"])
        self.assertEqual(kwargs["detalhes"]["gravidade"], "alta")

    def test_atualizar_alerta_audita_apenas_campos_alterados(self) -> None:
        paciente = self._seed_paciente()
        alerta = AlertaClinico(
            paciente_id=paciente.id, tipo="alergia", titulo="Alergia a penicilina", gravidade="alta"
        )
        self.db.add(alerta)
        self.db.commit()

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            atendimento.atualizar_alerta(
                alerta.id,
                AlertaPayload(tipo="alergia", titulo="Alergia a penicilina", gravidade="baixa"),
                request=_fake_request("PUT"),
                db=self.db,
                current_user=self.user,
            )

        auditoria_mock.assert_called_once()
        kwargs = auditoria_mock.call_args.kwargs
        self.assertEqual(kwargs["acao"], "ALERTA_CLINICO_ATUALIZADO")
        alteracoes = kwargs["detalhes"]["alteracoes"]
        self.assertEqual(alteracoes, {"gravidade": {"antes": "alta", "depois": "baixa"}})

    def test_atualizar_alerta_sem_mudanca_nao_audita(self) -> None:
        paciente = self._seed_paciente()
        alerta = AlertaClinico(
            paciente_id=paciente.id, tipo="alergia", titulo="Alergia a penicilina", gravidade="alta"
        )
        self.db.add(alerta)
        self.db.commit()

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            atendimento.atualizar_alerta(
                alerta.id,
                AlertaPayload(tipo="alergia", titulo="Alergia a penicilina", gravidade="alta"),
                request=_fake_request("PUT"),
                db=self.db,
                current_user=self.user,
            )

        auditoria_mock.assert_not_called()

    def test_desativar_alerta_e_auditado_com_conteudo_do_alerta(self) -> None:
        paciente = self._seed_paciente()
        alerta = AlertaClinico(
            paciente_id=paciente.id, tipo="alergia", titulo="Alergia a penicilina", gravidade="alta"
        )
        self.db.add(alerta)
        self.db.commit()
        alerta_id = alerta.id

        with patch.object(atendimento, "registrar_auditoria") as auditoria_mock:
            resposta = atendimento.desativar_alerta(
                alerta_id, request=_fake_request("DELETE"), db=self.db, current_user=self.user
            )

        self.assertEqual(resposta["id"], alerta_id)
        auditoria_mock.assert_called_once()
        kwargs = auditoria_mock.call_args.kwargs
        self.assertEqual(kwargs["acao"], "ALERTA_CLINICO_DESATIVADO")
        self.assertEqual(kwargs["detalhes"]["titulo"], "Alergia a penicilina")
        self.assertEqual(kwargs["detalhes"]["gravidade"], "alta")

        self.db.refresh(alerta)
        self.assertEqual(alerta.ativo, 0)


if __name__ == "__main__":
    unittest.main()
