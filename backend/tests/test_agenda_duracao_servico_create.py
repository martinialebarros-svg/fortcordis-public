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
os.environ.setdefault("SECRET_KEY", "agenda-duracao-servico-create-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from fastapi import HTTPException
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.servico import Servico


class AgendaDuracaoServicoCreateTest(unittest.TestCase):
    def setUp(self):
        # Duracao e reserva nao dependem da rede: simule a primeira viagem.
        regras_originais = agenda._obter_regras_rota_agenda

        def regras_com_base_sintetica(db):
            regras = regras_originais(db)
            return {**regras, "base": {
                **regras.get("base", {}),
                "address": "Rua Sintetica, 100, Fortaleza - CE",
                "zip_code": "60000-000",
            }}

        geocode = SimpleNamespace(
            latitude=-3.7319, longitude=-38.5267, place_id="base-duracao-teste",
            cidade="Fortaleza", estado="CE",
        )
        agenda._geocodificar_base_primeira_saida.cache_clear()
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
        db_path = Path(tmpdir.name) / "agenda-duracao-servico-create.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Configuracao.__table__,
            Clinica.__table__,
            Servico.__table__,
            Agendamento.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_criar_agendamento_forca_duracao_do_servico_quando_payload_traz_fim_maior(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(
                nome="Casa Pet",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            servico = Servico(nome="Eletrocardiograma", duracao_minutos=20, ativo=True)
            db.add_all([clinica, servico])
            db.commit()
            db.refresh(clinica)
            db.refresh(servico)

            inicio = datetime(2099, 5, 25, 11, 0, 0)
            fim_payload = inicio + timedelta(minutes=60)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=servico.id,
                inicio=inicio,
                fim=fim_payload,
                status="Reservado",
                observacoes="[Assistente agenda] sugestao aceita",
            )

            with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ):
                resposta = agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste"),
                )

            agendamento_criado = db.query(Agendamento).filter(Agendamento.id == int(resposta["id"])).first()
            self.assertIsNotNone(agendamento_criado)
            self.assertEqual(
                int((agendamento_criado.fim - agendamento_criado.inicio).total_seconds() // 60),
                20,
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_reserva_sem_paciente_persiste_null_em_vez_do_sentinela_zero(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(
                nome="Clinica Reserva",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            servico = Servico(nome="Reserva de horario", duracao_minutos=30, ativo=True)
            db.add_all([clinica, servico])
            db.commit()
            db.refresh(clinica)
            db.refresh(servico)

            inicio = datetime(2099, 5, 25, 11, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                tutor_id=None,
                clinica_id=clinica.id,
                servico_id=servico.id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Reservado",
                observacoes="[Reserva manual] destinatario: clinica",
            )

            with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ):
                resposta = agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste"),
                )

            agendamento_criado = db.query(Agendamento).filter(Agendamento.id == int(resposta["id"])).first()
            self.assertIsNotNone(agendamento_criado)
            self.assertIsNone(agendamento_criado.paciente_id)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reserva_vencida_exige_revisao_antes_de_liberar_novo_agendamento(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(
                nome="Clinica Expiracao",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            servico = Servico(nome="Consulta", duracao_minutos=30, ativo=True)
            db.add_all([clinica, servico])
            db.commit()
            db.refresh(clinica)
            db.refresh(servico)

            inicio = datetime(2099, 5, 25, 11, 0, 0)
            agora_local = datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None)
            reserva_vencida = Agendamento(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=servico.id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                data="2099-05-25",
                hora="11:00",
                status="Reservado",
                reserva_expira_em=agora_local - timedelta(minutes=1),
            )
            db.add(reserva_vencida)
            db.commit()
            db.refresh(reserva_vencida)

            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=servico.id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Reservado",
                reserva_expira_em=agora_local + timedelta(hours=3),
            )

            with self.assertRaises(HTTPException) as ctx:
                agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste"),
                )

            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual(
                ctx.exception.detail["codigo"],
                "CONFIRMACAO_SLOT_RESERVA_EXPIRADA",
            )
            self.assertEqual(
                ctx.exception.detail["reservas_expiradas"][0]["id"],
                reserva_vencida.id,
            )

            payload_confirmado = payload.model_copy(
                update={"confirmar_slot_reserva_expirada": True}
            )
            with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ):
                resposta = agenda.criar_agendamento(
                    agendamento=payload_confirmado,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste"),
                )

            db.refresh(reserva_vencida)
            self.assertEqual(reserva_vencida.status, "Expirado")
            self.assertNotEqual(int(resposta["id"]), reserva_vencida.id)

            with self.assertRaises(HTTPException) as conflito_ativo:
                agenda.criar_agendamento(
                    agendamento=payload_confirmado,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste"),
                )
            self.assertEqual(conflito_ativo.exception.status_code, 409)
            self.assertIn("ja existe atendimento", str(conflito_ativo.exception.detail))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_reserva_expirada_pode_ser_agendada_apos_confirmacao_se_slot_livre(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(
                nome="Clinica Confirmacao Tardia",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            servico = Servico(nome="Consulta", duracao_minutos=30, ativo=True)
            db.add_all([clinica, servico])
            db.commit()
            db.refresh(clinica)
            db.refresh(servico)

            inicio = datetime(2099, 5, 25, 11, 0, 0)
            reserva_expirada = Agendamento(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=servico.id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                data="2099-05-25",
                hora="11:00",
                status="Expirado",
                reserva_expira_em=datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None) - timedelta(minutes=5),
            )
            db.add(reserva_expirada)
            db.commit()
            db.refresh(reserva_expirada)

            with self.assertRaises(HTTPException) as confirmacao:
                agenda.atualizar_status(
                    agendamento_id=reserva_expirada.id,
                    request=SimpleNamespace(),
                    status="Agendado",
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste"),
                )
            self.assertEqual(confirmacao.exception.status_code, 409)
            self.assertEqual(
                confirmacao.exception.detail["codigo"],
                "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA",
            )

            with patch.object(
                agenda, "_validar_paciente_tutor_para_status", return_value=None
            ), patch.object(
                agenda, "_validar_deslocamento_agendamento", return_value=None
            ), patch.object(
                agenda, "registrar_auditoria", return_value=None
            ), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ):
                agenda.atualizar_status(
                    agendamento_id=reserva_expirada.id,
                    request=SimpleNamespace(),
                    status="Agendado",
                    confirmar_slot_reserva_expirada=True,
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Teste"),
                )

            db.refresh(reserva_expirada)
            self.assertEqual(reserva_expirada.status, "Agendado")

            outra_expirada = Agendamento(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=servico.id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                data="2099-05-25",
                hora="11:00",
                status="Expirado",
                reserva_expira_em=datetime.now(agenda.LOCAL_TZ).replace(tzinfo=None) - timedelta(minutes=1),
            )
            db.add(outra_expirada)
            db.commit()
            db.refresh(outra_expirada)

            with patch.object(
                agenda, "_validar_paciente_tutor_para_status", return_value=None
            ), patch.object(
                agenda, "_validar_deslocamento_agendamento", return_value=None
            ):
                with self.assertRaises(HTTPException) as conflito:
                    agenda.atualizar_status(
                        agendamento_id=outra_expirada.id,
                        request=SimpleNamespace(),
                        status="Agendado",
                        confirmar_slot_reserva_expirada=True,
                        db=db,
                        current_user=SimpleNamespace(id=1, nome="Teste"),
                    )
            self.assertEqual(conflito.exception.status_code, 409)
            self.assertIn("ja existe atendimento", str(conflito.exception.detail))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_bloqueia_override_conflito_para_nao_admin(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            inicio = datetime(2099, 5, 25, 11, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=1,
                servico_id=None,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Agendado",
                observacoes="teste",
                confirmar_conflito_deslocamento=True,
            )

            with self.assertRaises(HTTPException) as ctx:
                agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=10, nome="Sem Admin"),
                )

            self.assertEqual(int(ctx.exception.status_code), 403)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_repasse_override_conflito_quando_admin(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(
                nome="Clinica Admin",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            db.add(clinica)
            db.commit()
            db.refresh(clinica)

            inicio = datetime(2099, 5, 25, 11, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=None,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Reservado",
                observacoes="teste override admin",
                confirmar_conflito_deslocamento=True,
            )

            def _validar_deslocamento_mock(*args, **kwargs):
                self.assertTrue(bool(kwargs.get("confirmar_conflito_deslocamento")))

            usuario_admin = SimpleNamespace(
                id=99,
                nome="Admin",
                tem_papel=lambda papel: papel == "admin",
            )

            with patch.object(agenda, "_validar_deslocamento_agendamento", side_effect=_validar_deslocamento_mock), patch.object(
                agenda, "registrar_auditoria", return_value=None
            ), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ):
                resposta = agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=usuario_admin,
                )

            self.assertIsNotNone(resposta)
            self.assertTrue(int(resposta.get("id") or 0) > 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_bloqueia_excecao_operacional_para_nao_admin(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            inicio = datetime(2099, 5, 25, 11, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=1,
                servico_id=None,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Agendado",
                observacoes="teste",
                excecao_operacional_concedida=True,
                motivo_excecao_operacional="Cliente so tem essa janela disponivel.",
            )

            with self.assertRaises(HTTPException) as ctx:
                agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=10, nome="Sem Admin", tem_papel=lambda _: False),
                )

            self.assertEqual(int(ctx.exception.status_code), 403)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_admin_registra_evento_excecao_operacional(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(
                nome="Clinica Admin Excecao",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            db.add(clinica)
            db.commit()
            db.refresh(clinica)

            inicio = datetime(2099, 5, 25, 11, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=clinica.id,
                servico_id=None,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Reservado",
                observacoes="teste excecao admin",
                excecao_operacional_concedida=True,
                motivo_excecao_operacional="Cliente sem alternativa nas opcoes ofertadas.",
            )

            usuario_admin = SimpleNamespace(
                id=99,
                nome="Admin",
                tem_papel=lambda papel: papel == "admin",
            )

            with patch.object(agenda, "registrar_auditoria", return_value=None) as mocked_auditoria, patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ), patch.object(
                agenda, "_validar_deslocamento_agendamento", return_value=None
            ):
                resposta = agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=usuario_admin,
                )

            self.assertIsNotNone(resposta)
            chamadas = mocked_auditoria.call_args_list
            self.assertGreaterEqual(len(chamadas), 2)
            self.assertTrue(
                any(
                    call.kwargs.get("acao") == "ASSISTENTE_AGENDA_EXCECAO_CONCEDIDA"
                    and call.kwargs.get("detalhes", {}).get("motivo")
                    == "Cliente sem alternativa nas opcoes ofertadas."
                    for call in chamadas
                )
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_fechado_sem_confirmacao_mantem_bloqueio(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(
                nome="Clinica Agenda Fechada",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            config = Configuracao(
                agenda_excecoes='[{"data":"2099-05-25","ativo":false,"motivo":"Feriado local"}]'
            )
            db.add_all([clinica, config])
            db.commit()
            db.refresh(clinica)

            inicio = datetime(2099, 5, 25, 11, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=clinica.id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Reservado",
            )

            with self.assertRaises(HTTPException) as ctx:
                agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=10, nome="Admin", tem_papel=lambda papel: papel == "admin"),
                )

            self.assertEqual(int(ctx.exception.status_code), 422)
            self.assertIn("Agenda fechada por excecao", str(ctx.exception.detail))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_bloqueia_confirmacao_agenda_fechada_para_nao_admin(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            inicio = datetime(2099, 5, 25, 11, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=1,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Agendado",
                confirmar_agenda_fechada=True,
            )

            with self.assertRaises(HTTPException) as ctx:
                agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=SimpleNamespace(id=10, nome="Sem Admin", tem_papel=lambda _: False),
                )

            self.assertEqual(int(ctx.exception.status_code), 403)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_admin_nao_confirma_intervalo_invalido(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            inicio = datetime(2099, 5, 25, 11, 0, 0)
            agendamento_invalido = Agendamento(
                inicio=inicio,
                fim=inicio,
            )

            with self.assertRaises(HTTPException) as ctx:
                agenda._validar_agendamento_no_funcionamento(
                    db=db,
                    agendamento=agendamento_invalido,
                    permitir_excecao_agenda_fechada=True,
                )

            self.assertEqual(int(ctx.exception.status_code), 422)
            self.assertIn("Horario invalido", str(ctx.exception.detail))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_criar_agendamento_admin_confirma_agenda_fechada_e_audita(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(
                nome="Clinica Confirmacao Admin",
                ativo=True,
                latitude=-3.7319,
                longitude=-38.5267,
            )
            config = Configuracao(
                agenda_excecoes='[{"data":"2099-05-25","ativo":false,"motivo":"Feriado local"}]'
            )
            db.add_all([clinica, config])
            db.commit()
            db.refresh(clinica)

            inicio = datetime(2099, 5, 25, 11, 0, 0)
            payload = agenda.AgendamentoCreate(
                paciente_id=None,
                clinica_id=clinica.id,
                inicio=inicio,
                fim=inicio + timedelta(minutes=30),
                status="Reservado",
                confirmar_agenda_fechada=True,
            )
            usuario_admin = SimpleNamespace(
                id=99,
                nome="Admin",
                tem_papel=lambda papel: papel == "admin",
            )

            with patch.object(agenda, "registrar_auditoria", return_value=None) as mocked_auditoria, patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ), patch.object(
                agenda, "_validar_deslocamento_agendamento", return_value=None
            ):
                resposta = agenda.criar_agendamento(
                    agendamento=payload,
                    request=SimpleNamespace(),
                    db=db,
                    current_user=usuario_admin,
                )

            self.assertTrue(int(resposta.get("id") or 0) > 0)
            self.assertTrue(resposta["excecao_agenda_fechada_ativa"])
            reserva = db.query(Agendamento).filter(Agendamento.id == int(resposta["id"])).one()
            self.assertTrue(agenda._excecao_agenda_fechada_ativa(reserva))
            with patch.object(agenda, "registrar_auditoria", return_value=None), patch.object(
                agenda, "_notificar_agenda_update", return_value=None
            ), patch.object(
                agenda, "_validar_deslocamento_agendamento", return_value=None
            ), patch.object(
                agenda, "_validar_paciente_tutor_para_status", return_value=None
            ):
                atualizada = agenda.atualizar_agendamento(
                    agendamento_id=reserva.id,
                    agendamento=agenda.AgendamentoUpdate(
                        inicio=inicio, fim=inicio + timedelta(minutes=30), status="Agendado"
                    ),
                    request=SimpleNamespace(), db=db, current_user=usuario_admin,
                )
            self.assertEqual(atualizada["status"], "Agendado")
            self.assertTrue(atualizada["excecao_agenda_fechada_ativa"])
            reserva.fim = inicio + timedelta(minutes=45)
            self.assertFalse(agenda._excecao_agenda_fechada_ativa(reserva))
            with self.assertRaises(HTTPException) as horario_alterado:
                agenda._validar_agendamento_no_funcionamento(db, reserva)
            self.assertEqual(horario_alterado.exception.status_code, 422)
            self.assertTrue(
                any(
                    call.kwargs.get("acao") == "AGENDAMENTO_AGENDA_FECHADA_CONFIRMADO"
                    and call.kwargs.get("detalhes", {}).get("motivo_validacao")
                    == "Agenda fechada por excecao de data (Feriado local)."
                    for call in mocked_auditoria.call_args_list
                )
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
