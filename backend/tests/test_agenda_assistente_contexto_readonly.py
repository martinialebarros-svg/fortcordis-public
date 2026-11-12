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
os.environ.setdefault("SECRET_KEY", "agenda-assistente-contexto-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.core.config import Settings
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor


class AgendaAssistenteContextoReadOnlyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._token = "agenda-assistente-contexto-token-seguro-123"
        os.environ["ASSISTENTE_AGENDA_TOKEN"] = self._token
        os.environ["ASSISTENTE_AGENDA_MAX_WINDOW_DAYS"] = "14"
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "agenda-assistente-contexto.db"
        self._engine = create_engine(f"sqlite:///{db_path}")
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            Configuracao.__table__,
            Agendamento.__table__,
        ):
            table.create(self._engine, checkfirst=True)

    def tearDown(self) -> None:
        os.environ.pop("ASSISTENTE_AGENDA_TOKEN", None)
        os.environ.pop("ASSISTENTE_AGENDA_MAX_WINDOW_DAYS", None)
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _request(self, token: str | None = None):
        headers = {}
        if token is not None:
            headers["x-assistente-agenda-token"] = token
        return SimpleNamespace(headers=headers)

    def _seed(self, db):
        tutor = Tutor(nome="Maria Oliveira", telefone="85999990001", ativo=1)
        db.add(tutor)
        db.commit()
        db.refresh(tutor)

        paciente = Paciente(tutor_id=tutor.id, nome="Luna Oliveira", especie="Canina", ativo=1)
        clinica = Clinica(
            nome="Cardio Vet",
            cidade="Fortaleza",
            estado="CE",
            regiao_operacional="Fortaleza",
            ativo=True,
        )
        servico = Servico(nome="Ecocardiograma", duracao_minutos=30, ativo=True)
        config = Configuracao(
            agenda_rota_regras='{"offer_policy":{"default_first_offer_days_ahead":[2]}}',
        )
        db.add_all([paciente, clinica, servico, config])
        db.commit()
        db.refresh(paciente)
        db.refresh(clinica)
        db.refresh(servico)

        inicio = datetime.fromisoformat("2026-07-10T09:00:00")
        agendamento = Agendamento(
            paciente_id=paciente.id,
            clinica_id=clinica.id,
            servico_id=servico.id,
            inicio=inicio,
            fim=datetime.fromisoformat("2026-07-10T09:30:00"),
            data="2026-07-10",
            hora="09:00",
            status="Confirmado",
            paciente="Luna Legado",
            tutor="Tutor Legado",
            telefone="85000000000",
            observacoes="Observacao sensivel",
        )
        db.add(agendamento)
        db.commit()
        return agendamento

    def test_rejeita_token_ausente_ou_invalido(self) -> None:
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as sem_token:
                agenda.obter_contexto_assistente_agenda_readonly(
                    request=self._request(),
                    data_inicio="2026-07-10",
                    data_fim="2026-07-10",
                    db=db,
                )
            self.assertEqual(sem_token.exception.status_code, 403)

            with self.assertRaises(HTTPException) as token_invalido:
                agenda.obter_contexto_assistente_agenda_readonly(
                    request=self._request("token-errado"),
                    data_inicio="2026-07-10",
                    data_fim="2026-07-10",
                    db=db,
                )
            self.assertEqual(token_invalido.exception.status_code, 403)

    def test_retorna_contexto_minimo_sem_dados_sensiveis(self) -> None:
        with self._session_factory() as db:
            agendamento = self._seed(db)

            resposta = agenda.obter_contexto_assistente_agenda_readonly(
                request=self._request(self._token),
                data_inicio="2026-07-10",
                data_fim="2026-07-10",
                db=db,
            )

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["agenda"]["total"], 1)
        item = resposta["agenda"]["items"][0]
        self.assertEqual(item["agendamento_id"], agendamento.id)
        self.assertEqual(item["clinica"]["nome"], "Cardio Vet")
        self.assertEqual(item["servico"]["nome"], "Ecocardiograma")
        self.assertNotIn("telefone", item)
        self.assertNotIn("tutor", item)
        self.assertNotIn("observacoes", item)
        self.assertNotIn("paciente", item)

    def test_incluir_paciente_retorna_apenas_primeiro_nome(self) -> None:
        with self._session_factory() as db:
            self._seed(db)

            resposta = agenda.obter_contexto_assistente_agenda_readonly(
                request=self._request(self._token),
                data_inicio="2026-07-10",
                data_fim="2026-07-10",
                incluir_paciente=True,
                db=db,
            )

        item = resposta["agenda"]["items"][0]
        self.assertEqual(item["paciente_primeiro_nome"], "Luna")
        self.assertNotIn("Tutor", str(item))
        self.assertNotIn("859", str(item))

    def test_retorna_contexto_operacional_sanitizado(self) -> None:
        with self._session_factory() as db:
            agendamento = self._seed(db)
            conflito = Agendamento(
                paciente_id=agendamento.paciente_id,
                clinica_id=agendamento.clinica_id,
                servico_id=agendamento.servico_id,
                inicio=datetime.fromisoformat("2026-07-10T09:15:00"),
                fim=datetime.fromisoformat("2026-07-10T09:45:00"),
                data="2026-07-10",
                hora="09:15",
                status="Agendado",
                paciente="Thor Legado",
                tutor="Tutor Conflito",
                telefone="85000000002",
                observacoes="Outra observacao sensivel",
            )
            db.add(conflito)
            db.commit()

            resposta = agenda.obter_contexto_assistente_agenda_readonly(
                request=self._request(self._token),
                data_inicio="2026-07-10",
                data_fim="2026-07-10",
                db=db,
            )

        operacional = resposta["operacional"]
        self.assertEqual(operacional["modo"], "read_only_sanitizado")
        self.assertEqual(operacional["totais"]["agendamentos_ativos"], 2)
        self.assertEqual(operacional["totais"]["conflitos"], 1)
        dia = operacional["dias"][0]
        self.assertEqual(dia["data"], "2026-07-10")
        self.assertEqual(dia["fila_status"]["aguardando"], 2)
        self.assertEqual(dia["pendencias"]["sem_confirmacao"], 1)
        self.assertEqual(dia["conflitos"][0]["tipo"], "sobreposicao")
        self.assertIn({"inicio": "08:00", "fim": "09:00", "duracao_minutos": 60}, dia["vagas_livres"])
        self.assertNotIn("telefone", str(operacional))
        self.assertNotIn("observacao", str(operacional).lower())
        self.assertNotIn("Tutor", str(operacional))

    def test_limita_janela_de_consulta(self) -> None:
        os.environ["ASSISTENTE_AGENDA_MAX_WINDOW_DAYS"] = "2"
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as erro:
                agenda.obter_contexto_assistente_agenda_readonly(
                    request=self._request(self._token),
                    data_inicio="2026-07-10",
                    data_fim="2026-07-12",
                    db=db,
                )
        self.assertEqual(erro.exception.status_code, 422)

    def test_settings_aceita_variaveis_do_assistente_no_env(self) -> None:
        settings = Settings()
        self.assertEqual(settings.ASSISTENTE_AGENDA_TOKEN, self._token)
        self.assertEqual(settings.ASSISTENTE_AGENDA_MAX_WINDOW_DAYS, 14)


if __name__ == "__main__":
    unittest.main()
