import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-origem-domiciliar-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.configuracao import ConfiguracaoUsuario
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor


class AgendaOrigemDomiciliarTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-origem-domiciliar.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            ConfiguracaoUsuario.__table__,
            Clinica.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Servico.__table__,
            Agendamento.__table__,
            OrdemServico.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_criar_agendamento_domiciliar_exige_tutor_georreferenciado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Maria Silva",
                telefone="85999990000",
                endereco="Rua das Flores",
                numero="123",
                cidade="Fortaleza",
                estado="CE",
                ativo=1,
            )
            db.add(tutor)
            db.commit()
            db.refresh(tutor)

            inicio = datetime(2099, 6, 2, 9, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                tutor_id=tutor.id,
                clinica_id=None,
                servico_id=None,
                origem_atendimento="domiciliar",
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Reservado",
                observacoes="teste domiciliar sem georef",
            )

            with self.assertRaises(HTTPException) as ctx:
                agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste", tem_papel=lambda _: False),
                )

            self.assertEqual(int(ctx.exception.status_code), 422)
            self.assertIn("tutor selecionado", str(ctx.exception.detail).lower())
            self.assertIn("georreferenciado", str(ctx.exception.detail).lower())
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_domiciliar_rejeita_tutor_com_coordenadas_zero_sem_endereco(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Teste georef",
                telefone="85999990000",
                latitude=0.0,
                longitude=0.0,
                ativo=1,
            )
            db.add(tutor)
            db.commit()
            db.refresh(tutor)

            inicio = datetime(2099, 6, 2, 9, 30, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                tutor_id=tutor.id,
                clinica_id=None,
                servico_id=None,
                origem_atendimento="domiciliar",
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Reservado",
                observacoes="teste domiciliar com coordenada invalida",
            )

            with self.assertRaises(HTTPException) as ctx:
                agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste", tem_papel=lambda _: False),
                )

            self.assertEqual(int(ctx.exception.status_code), 422)
            self.assertIn("georreferenciado", str(ctx.exception.detail).lower())
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_domiciliar_persiste_origem_e_rotulo_operacional(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Joao Pereira",
                telefone="85988887777",
                endereco="Av. Central",
                numero="456",
                cidade="Fortaleza",
                estado="CE",
                latitude=-3.7319,
                longitude=-38.5267,
                ativo=1,
            )
            db.add(tutor)
            db.commit()
            db.refresh(tutor)

            inicio = datetime(2099, 6, 2, 10, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                tutor_id=tutor.id,
                clinica_id=999,
                servico_id=None,
                origem_atendimento="domiciliar",
                inicio=inicio,
                fim=inicio + timedelta(minutes=45),
                status="Reservado",
                observacoes="teste domiciliar com georef",
            )

            with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ), patch.object(
                agenda, "_validar_deslocamento_agendamento", return_value=None
            ):
                resposta = agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste", tem_papel=lambda _: False),
                )

            self.assertEqual(resposta["origem_atendimento"], "domiciliar")
            self.assertEqual(resposta["tutor_id"], tutor.id)
            self.assertIsNone(resposta["clinica_id"])
            self.assertEqual(resposta["clinica"], "Atendimento domiciliar")

            agendamento_criado = db.query(Agendamento).filter(Agendamento.id == int(resposta["id"])).first()
            self.assertIsNotNone(agendamento_criado)
            self.assertEqual(agendamento_criado.origem_atendimento, "domiciliar")
            self.assertEqual(int(agendamento_criado.tutor_id or 0), tutor.id)
            self.assertIsNone(agendamento_criado.clinica_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_realizado_domiciliar_gera_os_com_preco_do_servico(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Ana Souza",
                telefone="85977776666",
                endereco="Rua B",
                numero="50",
                cidade="Fortaleza",
                estado="CE",
                latitude=-3.7325,
                longitude=-38.5271,
                ativo=1,
            )
            db.add(tutor)
            db.commit()
            db.refresh(tutor)

            paciente = Paciente(
                nome="Thor",
                tutor_id=tutor.id,
                especie="Canina",
                ativo=1,
            )
            db.add(paciente)
            db.commit()
            db.refresh(paciente)

            servico = Servico(
                nome="Ecocardiograma domiciliar",
                duracao_minutos=30,
                preco_domiciliar_comercial=Decimal("210.00"),
                preco_domiciliar_plantao=Decimal("260.00"),
                ativo=True,
            )
            db.add(servico)
            db.commit()
            db.refresh(servico)

            inicio = datetime(2099, 6, 2, 11, 0, 0)
            agendamento = Agendamento(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=None,
                servico_id=servico.id,
                origem_atendimento="domiciliar",
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Em atendimento",
                observacoes="domiciliar em execucao",
            )
            db.add(agendamento)
            db.commit()
            db.refresh(agendamento)

            with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ), patch.object(
                agenda, "send_financeiro_push_notification", return_value={"sent": 0, "failed": 0}
            ), patch.object(
                agenda, "schedule_pending_os_payment_reminder", return_value=None
            ):
                resposta = agenda.atualizar_status(
                    agendamento_id=agendamento.id,
                    request=SimpleNamespace(),
                    status="Realizado",
                    tipo_horario="comercial",
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste", tem_papel=lambda _: False),
                )

            self.assertEqual(resposta["status"], "Realizado")
            self.assertEqual(resposta["clinica"], "Atendimento domiciliar")
            self.assertIn("os_gerada", resposta)
            self.assertTrue(int(resposta["os_gerada"]["id"]) > 0)

            os_gerada = db.query(OrdemServico).filter(OrdemServico.agendamento_id == agendamento.id).first()
            self.assertIsNotNone(os_gerada)
            self.assertIsNone(os_gerada.clinica_id)
            self.assertEqual(os_gerada.origem_atendimento, "domiciliar")
            self.assertEqual(float(os_gerada.valor_servico or 0), 210.0)
            self.assertEqual(float(os_gerada.valor_final or 0), 210.0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_legado_resolve_tutor_id_pelo_paciente_na_lista_e_no_detalhe(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Clara Nogueira",
                telefone="85970001111",
                endereco="Rua das Acacias",
                numero="90",
                cidade="Fortaleza",
                estado="CE",
                ativo=1,
            )
            db.add(tutor)
            db.commit()
            db.refresh(tutor)

            paciente = Paciente(
                nome="Mel",
                tutor_id=tutor.id,
                especie="Canina",
                ativo=1,
            )
            db.add(paciente)
            db.commit()
            db.refresh(paciente)

            inicio = datetime(2099, 6, 3, 14, 0, 0)
            agendamento = Agendamento(
                paciente_id=paciente.id,
                tutor_id=None,
                clinica_id=None,
                servico_id=None,
                origem_atendimento="domiciliar",
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                data=inicio.strftime("%Y-%m-%d"),
                status="Agendado",
                observacoes="legado sem tutor_id persistido",
            )
            db.add(agendamento)
            db.commit()
            db.refresh(agendamento)

            lista = agenda.listar_agendamentos(
                data_inicio="2099-06-03",
                data_fim="2099-06-03",
                db=db,
                current_user=SimpleNamespace(id=1),
            )
            self.assertEqual(lista["total"], 1)
            self.assertEqual(lista["items"][0]["tutor_id"], tutor.id)
            self.assertEqual(lista["items"][0]["tutor"], tutor.nome)

            detalhe = agenda.obter_agendamento(
                agendamento_id=agendamento.id,
                db=db,
                current_user=SimpleNamespace(id=1),
            )
            self.assertEqual(detalhe["tutor_id"], tutor.id)
            self.assertEqual(detalhe["tutor"], tutor.nome)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
