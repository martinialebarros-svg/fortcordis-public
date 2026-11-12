import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-reabilitar-reserva-expirada-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from fastapi import HTTPException
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor

INICIO_RESERVA = datetime(2099, 5, 25, 11, 0, 0)


class AgendaReabilitarReservaExpiradaTest(unittest.TestCase):
    def setUp(self):
        # Estes cenarios testam o ciclo da reserva, com primeira viagem
        # deterministica desde a base residencial configurada por endereco.
        regras_originais = agenda._obter_regras_rota_agenda

        def regras_com_base_sintetica(db):
            regras = regras_originais(db)
            return {**regras, "base": {
                **regras.get("base", {}),
                "address": "Rua Sintetica, 100, Fortaleza - CE",
                "zip_code": "60000-000",
            }}

        agenda._geocodificar_base_primeira_saida.cache_clear()
        geocode = SimpleNamespace(
            latitude=-3.7319, longitude=-38.5267, place_id="base-reserva-teste",
            cidade="Fortaleza", estado="CE",
        )
        for patcher in (
            patch.object(agenda.settings, "GOOGLE_MAPS_API_KEY", "chave-sintetica"),
            patch.object(agenda.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", True),
            patch.object(agenda, "geocodificar_endereco_google", return_value=geocode),
            patch.object(agenda, "estimar_deslocamento", return_value=(2.0, 5, "google_distance_matrix_traffic")),
            patch.object(agenda, "_obter_regras_rota_agenda", side_effect=regras_com_base_sintetica),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(agenda._geocodificar_base_primeira_saida.cache_clear)

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "agenda-reabilitar-reserva-expirada.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            Clinica.__table__,
            Servico.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Agendamento.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _criar_clinica_servico(self, db):
        clinica = Clinica(
            nome="Clinica Reabilitacao",
            ativo=True,
            latitude=-3.7319,
            longitude=-38.5267,
        )
        servico = Servico(nome="Ecocardiograma", duracao_minutos=30, ativo=True)
        db.add_all([clinica, servico])
        db.commit()
        db.refresh(clinica)
        db.refresh(servico)
        return clinica, servico

    def _criar_reserva_expirada(self, db, clinica, servico, *, inicio=INICIO_RESERVA):
        agora_local = datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None)
        reserva = Agendamento(
            paciente_id=None,
            tutor_id=None,
            clinica_id=clinica.id,
            servico_id=servico.id,
            inicio=inicio,
            fim=inicio + timedelta(minutes=30),
            data=inicio.strftime("%Y-%m-%d"),
            hora=inicio.strftime("%H:%M"),
            status="Reservado",
            reserva_expira_em=agora_local - timedelta(hours=1),
        )
        db.add(reserva)
        db.commit()
        db.refresh(reserva)
        return reserva

    def _reabilitar(self, db, agendamento_id, **payload_kwargs):
        payload = agenda.ReabilitarReservaPayload(**payload_kwargs)
        with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
            agenda, "_notificar_agenda_update", return_value=None
        ):
            return agenda.reabilitar_reserva_expirada(
                agendamento_id=agendamento_id,
                payload=payload,
                request=SimpleNamespace(),
                db=db,
                current_user=SimpleNamespace(id=1, nome="Recepcao"),
            )

    def _criar_reserva_em_agenda_fechada(self, db, *, status, escopo_aprovado=True):
        clinica, servico = self._criar_clinica_servico(db)
        db.add(Configuracao(agenda_excecoes='[{"data":"2099-05-25","ativo":false,"motivo":"Feriado local"}]'))
        db.commit()
        inicio = INICIO_RESERVA + (timedelta(minutes=15) if not escopo_aprovado else timedelta())
        reserva = Agendamento(
            clinica_id=clinica.id,
            servico_id=servico.id,
            inicio=inicio,
            fim=inicio + timedelta(minutes=30),
            data=inicio.strftime("%Y-%m-%d"),
            hora=inicio.strftime("%H:%M"),
            status=status,
            reserva_expira_em=(
                datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None) - timedelta(hours=1)
                if status == "Expirado" else None
            ),
        )
        # Simula a concessao anterior do admin para 11:00-11:30. Um horario
        # posteriormente alterado nao pode herdar essa autorizacao.
        reserva.excecao_agenda_fechada_escopo = (
            f"{INICIO_RESERVA.isoformat()}|{(INICIO_RESERVA + timedelta(minutes=30)).isoformat()}"
        )
        db.add(reserva)
        db.commit()
        db.refresh(reserva)
        return reserva

    def test_status_reativa_agenda_fechada_apenas_no_intervalo_aprovado(self) -> None:
        for escopo_aprovado in (True, False):
            with self.subTest(escopo_aprovado=escopo_aprovado):
                tmpdir, db, engine = self._build_session()
                try:
                    reserva = self._criar_reserva_em_agenda_fechada(
                        db, status="Cancelado", escopo_aprovado=escopo_aprovado
                    )
                    with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
                        agenda, "_notificar_agenda_update", return_value=None
                    ):
                        if escopo_aprovado:
                            resposta = agenda.atualizar_status(
                                agendamento_id=reserva.id,
                                request=SimpleNamespace(),
                                status="Reservado",
                                db=db,
                                current_user=SimpleNamespace(id=1, nome="Recepcao"),
                            )
                            self.assertEqual(resposta["status"], "Reservado")
                        else:
                            with self.assertRaises(HTTPException) as erro:
                                agenda.atualizar_status(
                                    agendamento_id=reserva.id,
                                    request=SimpleNamespace(),
                                    status="Reservado",
                                    db=db,
                                    current_user=SimpleNamespace(id=1, nome="Recepcao"),
                                )
                            self.assertEqual(erro.exception.status_code, 422)
                            self.assertIn("Agenda fechada", str(erro.exception.detail))
                finally:
                    db.close()
                    engine.dispose()
                    tmpdir.cleanup()

    def test_reabilitar_reserva_em_agenda_fechada_apenas_no_intervalo_aprovado(self) -> None:
        for escopo_aprovado in (True, False):
            with self.subTest(escopo_aprovado=escopo_aprovado):
                tmpdir, db, engine = self._build_session()
                try:
                    reserva = self._criar_reserva_em_agenda_fechada(
                        db, status="Expirado", escopo_aprovado=escopo_aprovado
                    )
                    if escopo_aprovado:
                        resposta = self._reabilitar(db, reserva.id, prazo_confirmacao_horas=6)
                        self.assertEqual(resposta["status"], "Reservado")
                    else:
                        with self.assertRaises(HTTPException) as erro:
                            self._reabilitar(db, reserva.id, prazo_confirmacao_horas=6)
                        self.assertEqual(erro.exception.status_code, 422)
                        self.assertIn("Agenda fechada", str(erro.exception.detail))
                finally:
                    db.close()
                    engine.dispose()
                    tmpdir.cleanup()

    def test_reabilita_reserva_expirada_sem_dados_do_paciente_com_novo_prazo(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica, servico = self._criar_clinica_servico(db)
            reserva = self._criar_reserva_expirada(db, clinica, servico)

            # O worker de expiracao roda no inicio do endpoint: o status ainda
            # esta "Reservado" no banco, mas o prazo ja venceu.
            resposta = self._reabilitar(db, reserva.id, prazo_confirmacao_horas=6)

            db.refresh(reserva)
            self.assertEqual(reserva.status, "Reservado")
            self.assertIsNone(reserva.paciente_id)
            prazo_novo = agenda._to_local_naive(agenda._coerce_datetime(reserva.reserva_expira_em))
            agora_local = datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None)
            self.assertGreater(prazo_novo, agora_local + timedelta(hours=5, minutes=45))
            self.assertLess(prazo_novo, agora_local + timedelta(hours=6, minutes=15))
            self.assertEqual(resposta["status"], "Reservado")
            self.assertFalse(resposta["prazo_encurtado"])
            self.assertIn("Reserva reabilitada", resposta["mensagem"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reabilitacao_usa_prazo_padrao_de_tres_horas_quando_nao_informado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica, servico = self._criar_clinica_servico(db)
            reserva = self._criar_reserva_expirada(db, clinica, servico)

            self._reabilitar(db, reserva.id)

            db.refresh(reserva)
            prazo_novo = agenda._to_local_naive(agenda._coerce_datetime(reserva.reserva_expira_em))
            agora_local = datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None)
            self.assertGreater(prazo_novo, agora_local + timedelta(hours=2, minutes=45))
            self.assertLess(prazo_novo, agora_local + timedelta(hours=3, minutes=15))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reabilitacao_bloqueada_quando_slot_foi_ocupado_por_outro_agendamento(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica, servico = self._criar_clinica_servico(db)
            reserva = self._criar_reserva_expirada(db, clinica, servico)

            ocupante = Agendamento(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=servico.id,
                inicio=INICIO_RESERVA,
                fim=INICIO_RESERVA + timedelta(minutes=30),
                data=INICIO_RESERVA.strftime("%Y-%m-%d"),
                hora=INICIO_RESERVA.strftime("%H:%M"),
                status="Agendado",
                paciente="Mel",
            )
            db.add(ocupante)
            db.commit()

            with self.assertRaises(HTTPException) as ctx:
                self._reabilitar(db, reserva.id)

            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("Horario indisponivel", str(ctx.exception.detail))

            db.rollback()
            db.refresh(reserva)
            # A transacao inteira e desfeita: a reserva segue vencida e sem
            # prazo novo, exatamente como antes da tentativa.
            self.assertEqual(agenda._status_efetivo_agendamento(reserva), "Expirado")
            prazo = agenda._to_local_naive(agenda._coerce_datetime(reserva.reserva_expira_em))
            self.assertLess(prazo, datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reabilitacao_exige_revisao_de_outra_reserva_expirada_sobreposta(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica, servico = self._criar_clinica_servico(db)
            reserva = self._criar_reserva_expirada(db, clinica, servico)
            outra_expirada = self._criar_reserva_expirada(db, clinica, servico)

            with self.assertRaises(HTTPException) as ctx:
                self._reabilitar(db, reserva.id)

            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual(
                ctx.exception.detail["codigo"],
                "CONFIRMACAO_SLOT_RESERVA_EXPIRADA",
            )
            self.assertEqual(
                [item["id"] for item in ctx.exception.detail["reservas_expiradas"]],
                [outra_expirada.id],
            )

            db.rollback()
            resposta = self._reabilitar(
                db,
                reserva.id,
                confirmar_slot_reserva_expirada=True,
            )

            db.refresh(reserva)
            self.assertEqual(reserva.status, "Reservado")
            self.assertEqual(resposta["status"], "Reservado")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reabilitacao_recusa_agendamento_que_nao_esta_expirado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica, servico = self._criar_clinica_servico(db)
            agendado = Agendamento(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=servico.id,
                inicio=INICIO_RESERVA,
                fim=INICIO_RESERVA + timedelta(minutes=30),
                data=INICIO_RESERVA.strftime("%Y-%m-%d"),
                hora=INICIO_RESERVA.strftime("%H:%M"),
                status="Agendado",
            )
            db.add(agendado)
            db.commit()
            db.refresh(agendado)

            with self.assertRaises(HTTPException) as ctx:
                self._reabilitar(db, agendado.id)

            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("Somente reservas expiradas", str(ctx.exception.detail))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_prazo_encurtado_para_terminar_antes_do_horario_reservado(self) -> None:
        agora_local = datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None)
        inicio = (agora_local + timedelta(hours=1)).replace(second=0, microsecond=0)
        reserva = Agendamento(status="Expirado", inicio=inicio, fim=inicio + timedelta(minutes=30))

        prazo, encurtado = agenda._calcular_prazo_reabilitacao_reserva(reserva, horas=3)

        self.assertTrue(encurtado)
        self.assertEqual(
            prazo,
            inicio - timedelta(minutes=agenda.MARGEM_MINIMA_PRAZO_RESERVA_MIN),
        )

    def test_reabilitacao_recusada_quando_horario_esta_proximo_demais(self) -> None:
        agora_local = datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None)
        inicio = agora_local + timedelta(minutes=2)
        reserva = Agendamento(status="Expirado", inicio=inicio, fim=inicio + timedelta(minutes=30))

        with self.assertRaises(HTTPException) as ctx:
            agenda._calcular_prazo_reabilitacao_reserva(reserva, horas=3)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("proximo demais", str(ctx.exception.detail))

    def test_prazo_explicito_invalido_e_recusado_pela_validacao_de_reserva(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica, servico = self._criar_clinica_servico(db)
            reserva = self._criar_reserva_expirada(db, clinica, servico)

            with self.assertRaises(HTTPException) as ctx:
                self._reabilitar(
                    db,
                    reserva.id,
                    reserva_expira_em=INICIO_RESERVA + timedelta(hours=1),
                )

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("anterior ao horario reservado", str(ctx.exception.detail))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
