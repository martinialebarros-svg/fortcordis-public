import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-concorrencia-slot-test-secret-key-1234567890")

from fastapi import HTTPException

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.servico import Servico


class AgendaConcorrenciaSlotTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "agenda-concorrencia-slot.db"
        self._engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        for table in (
            Configuracao.__table__,
            Clinica.__table__,
            Servico.__table__,
            Agendamento.__table__,
        ):
            table.create(self._engine, checkfirst=True)
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)

        with self._session_factory() as db:
            clinica = Clinica(
                nome="Casa Pet",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            servico = Servico(nome="Consulta", duracao_minutos=30, ativo=True)
            db.add_all([clinica, servico])
            db.commit()
            db.refresh(clinica)
            db.refresh(servico)
            self.clinica_id = int(clinica.id)
            self.servico_id = int(servico.id)

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _payload(self) -> agenda.AgendamentoCreate:
        inicio = datetime(2099, 5, 27, 10, 0, 0)
        return agenda.AgendamentoCreate(
            paciente_id=None,
            clinica_id=self.clinica_id,
            servico_id=self.servico_id,
            inicio=inicio,
            fim=inicio + timedelta(minutes=30),
            status="Reservado",
            observacoes="teste concorrencia",
        )

    def _criar_em_thread(self, barrier: threading.Barrier, resultado: dict[int, tuple], idx: int) -> None:
        db = self._session_factory()
        try:
            barrier.wait(timeout=5)
            resposta = agenda.criar_agendamento(
                agendamento=self._payload(),
                request=SimpleNamespace(),
                db=db,
                current_user=SimpleNamespace(id=idx + 1, nome=f"User {idx + 1}", tem_papel=lambda _: False),
            )
            resultado[idx] = ("ok", int(resposta["id"]))
        except HTTPException as exc:
            resultado[idx] = ("http", int(exc.status_code), str(exc.detail))
        except Exception as exc:
            resultado[idx] = ("err", str(exc))
        finally:
            db.close()

    def test_criacao_concorrente_no_mesmo_slot_cria_apenas_um_agendamento(self) -> None:
        resultado: dict[int, tuple] = {}
        barrier = threading.Barrier(2)

        with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
            agenda, "_notificar_agenda_update", return_value=None
        ), patch.object(
            agenda, "_validar_deslocamento_agendamento", return_value=None
        ):
            threads = [
                threading.Thread(target=self._criar_em_thread, args=(barrier, resultado, 0), daemon=True),
                threading.Thread(target=self._criar_em_thread, args=(barrier, resultado, 1), daemon=True),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertEqual(len(resultado), 2)
        self.assertFalse(any(item[0] == "err" for item in resultado.values()), msg=str(resultado))

        sucessos = [item for item in resultado.values() if item[0] == "ok"]
        falhas_http = [item for item in resultado.values() if item[0] == "http"]

        self.assertEqual(len(sucessos), 1, msg=str(resultado))
        self.assertEqual(len(falhas_http), 1, msg=str(resultado))
        self.assertEqual(falhas_http[0][1], 409, msg=str(resultado))

        with self._session_factory() as db:
            total = db.query(Agendamento).count()
        self.assertEqual(total, 1)

    def test_remarcacao_sincroniza_hora_antes_de_validar_slot(self) -> None:
        inicio_ocupado = datetime(2099, 5, 27, 10, 0, 0)
        inicio_original = inicio_ocupado + timedelta(hours=1)
        usuario = SimpleNamespace(id=1, nome="User 1", tem_papel=lambda _: False)

        with self._session_factory() as db, patch.object(
            agenda, "registrar_auditoria", return_value=None
        ), patch.object(
            agenda, "_notificar_agenda_update", return_value=None
        ), patch.object(
            agenda, "_validar_deslocamento_agendamento", return_value=None
        ):
            ocupado = agenda.criar_agendamento(
                agendamento=self._payload(),
                request=SimpleNamespace(),
                db=db,
                current_user=usuario,
            )
            candidato = agenda.criar_agendamento(
                agendamento=agenda.AgendamentoCreate(
                    paciente_id=None,
                    clinica_id=self.clinica_id,
                    servico_id=self.servico_id,
                    inicio=inicio_original,
                    fim=inicio_original + timedelta(minutes=30),
                    status="Reservado",
                    observacoes="teste remarcacao",
                ),
                request=SimpleNamespace(),
                db=db,
                current_user=usuario,
            )

            with self.assertRaises(HTTPException) as contexto:
                agenda.atualizar_agendamento(
                    agendamento_id=int(candidato["id"]),
                    agendamento=agenda.AgendamentoUpdate(
                        inicio=inicio_ocupado,
                        fim=inicio_ocupado + timedelta(minutes=30),
                    ),
                    request=SimpleNamespace(),
                    db=db,
                    current_user=usuario,
                )

            self.assertEqual(contexto.exception.status_code, 409)
            db.rollback()

            candidato_persistido = (
                db.query(Agendamento)
                .filter(Agendamento.id == int(candidato["id"]))
                .one()
            )
            self.assertEqual(candidato_persistido.hora, "11:00")
            self.assertEqual(
                db.query(Agendamento)
                .filter(Agendamento.id == int(ocupado["id"]))
                .count(),
                1,
            )

    def test_confirmacao_revalida_slot_e_bloqueia_conflito_legado(self) -> None:
        inicio = datetime(2099, 5, 27, 10, 0, 0)
        usuario = SimpleNamespace(id=1, nome="User 1", tem_papel=lambda _: False)

        with self._session_factory() as db:
            reservado = Agendamento(
                paciente_id=None,
                clinica_id=self.clinica_id,
                servico_id=self.servico_id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                data="2099-05-27",
                hora="10:00",
                status="Reservado",
            )
            conflito_legado = Agendamento(
                paciente_id=None,
                clinica_id=self.clinica_id,
                servico_id=self.servico_id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                data="2099-05-27",
                hora="10:00",
                status="Agendado",
            )
            db.add_all([reservado, conflito_legado])
            db.commit()
            db.refresh(reservado)

            with patch.object(
                agenda, "_validar_paciente_tutor_para_status", return_value=None
            ), self.assertRaises(HTTPException) as contexto:
                agenda.atualizar_status(
                    agendamento_id=int(reservado.id),
                    request=SimpleNamespace(),
                    status="Confirmado",
                    db=db,
                    current_user=usuario,
                )

            self.assertEqual(contexto.exception.status_code, 409)
            db.rollback()
            db.refresh(reservado)
            self.assertEqual(reservado.status, "Reservado")

    def test_reserva_sem_paciente_pode_ser_cancelada(self) -> None:
        usuario = SimpleNamespace(id=1, nome="User 1", tem_papel=lambda _: False)

        with self._session_factory() as db, patch.object(
            agenda, "registrar_auditoria", return_value=None
        ), patch.object(
            agenda, "_notificar_agenda_update", return_value=None
        ), patch.object(
            agenda, "_validar_deslocamento_agendamento", return_value=None
        ):
            reservado = agenda.criar_agendamento(
                agendamento=self._payload(),
                request=SimpleNamespace(),
                db=db,
                current_user=usuario,
            )

            resposta = agenda.atualizar_status(
                agendamento_id=int(reservado["id"]),
                request=SimpleNamespace(),
                status="Cancelado",
                db=db,
                current_user=usuario,
            )

            self.assertEqual(resposta["status"], "Cancelado")
            persistido = (
                db.query(Agendamento)
                .filter(Agendamento.id == int(reservado["id"]))
                .one()
            )
            db.refresh(persistido)
            self.assertEqual(persistido.status, "Cancelado")

    def test_violacao_da_constraint_de_slot_retorna_http_409(self) -> None:
        db = MagicMock()
        erro = SQLAlchemyError("exclusion violation")
        erro.orig = SimpleNamespace(sqlstate="23P01")
        db.commit.side_effect = erro

        with self.assertRaises(HTTPException) as contexto:
            agenda._commit_agenda_write(db)

        self.assertEqual(contexto.exception.status_code, 409)
        db.rollback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
