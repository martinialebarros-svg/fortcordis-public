"""Excecao de admin para primeira saida preserva permissao, escopo e auditoria."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException, Request

from tests import test_agenda_excecao_deslocamento_persistente as fixtures
from tests.test_agenda_excecao_deslocamento_persistente import ADMIN, SECRETARIA
from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento


class AgendaExcecaoPrimeiraSaidaAdminTest(unittest.TestCase):
    _build_session = fixtures.AgendaExcecaoDeslocamentoPersistenteTest._build_session
    _seed = fixtures.AgendaExcecaoDeslocamentoPersistenteTest._seed

    def setUp(self):
        self.tmpdir, self.db, self.engine = self._build_session()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.ctx = self._seed(self.db)
        self.db.query(Agendamento).delete()
        self.db.commit()
        self.inicio = datetime(2099, 5, 25, 8, 30)
        for patcher in (
            patch.object(agenda, "_obter_deslocamento_primeira_saida", return_value=(45, "google_distance_matrix_traffic")),
            patch.object(agenda, "registrar_auditoria"),
            patch.object(agenda, "_notificar_agenda_update"),
        ):
            started = patcher.start()
            self.addCleanup(patcher.stop)
            if patcher.attribute == "registrar_auditoria":
                self.audit = started

    def payload(self, **changes):
        return agenda.AgendamentoCreate(**{
            "paciente_id": self.ctx.paciente.id,
            "tutor_id": self.ctx.tutor.id,
            "clinica_id": self.ctx.clinica_alvo.id,
            "servico_id": self.ctx.servico.id,
            "inicio": self.inicio,
            "fim": self.inicio + timedelta(minutes=30),
            **changes,
        })

    def create(self, user=ADMIN, **changes):
        return agenda.criar_agendamento(self.payload(**changes), Request({"type": "http"}), self.db, user)

    def test_admin_without_explicit_exception_is_blocked_then_can_confirm(self):
        with self.assertRaises(HTTPException) as raised:
            self.create()
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")
        self.assertTrue(raised.exception.detail["confirmavel"])
        self.assertEqual(self.db.query(Agendamento).count(), 0)
        result = self.create(
            confirmar_conflito_deslocamento=True,
            excecao_operacional_concedida=True,
            motivo_excecao_operacional="Admin ja esta no local do atendimento.",
        )
        saved = self.db.get(Agendamento, result["id"])
        self.assertEqual(saved.inicio, self.inicio)
        self.assertEqual(saved.fim, self.inicio + timedelta(minutes=30))
        self.assertTrue(result["excecao_deslocamento_ativa"])
        self.assertEqual(saved.excecao_deslocamento_concedida_por_id, ADMIN.id)
        self.assertIsNotNone(saved.excecao_deslocamento_concedida_em)
        self.assertEqual(saved.excecao_deslocamento_motivo, "Admin ja esta no local do atendimento.")
        event = next(call.kwargs for call in self.audit.call_args_list
                     if call.kwargs.get("acao") == "AGENDA_EXCECAO_DESLOCAMENTO_CONCEDIDA")
        self.assertEqual(event["detalhes"]["bloqueio_ignorado"], "PRIMEIRA_SAIDA_INVIAVEL")
        self.assertTrue(any(call.kwargs.get("acao") == "ASSISTENTE_AGENDA_EXCECAO_CONCEDIDA"
                            for call in self.audit.call_args_list))

    def test_non_admin_cannot_send_either_exception_flag(self):
        for flag in ("confirmar_conflito_deslocamento", "excecao_operacional_concedida"):
            with self.subTest(flag=flag), self.assertRaises(HTTPException) as raised:
                self.create(user=SECRETARIA, **{flag: True}, motivo_excecao_operacional="Motivo informado")
            self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(self.db.query(Agendamento).count(), 0)
        self.audit.assert_not_called()

    def test_operational_exception_requires_useful_reason(self):
        with self.assertRaises(HTTPException) as raised:
            self.create(confirmar_conflito_deslocamento=True,
                        excecao_operacional_concedida=True, motivo_excecao_operacional="   ")
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(self.db.query(Agendamento).count(), 0)
        self.audit.assert_not_called()

    def test_persisted_exception_is_reused_only_for_same_route(self):
        result = self.create(confirmar_conflito_deslocamento=True)
        saved = self.db.get(Agendamento, result["id"])
        self.assertEqual(agenda._validar_deslocamento_agendamento(
            self.db, saved, agendamento_id_excluir=saved.id),
            {"origem": "excecao_persistida", "bloqueio": "PRIMEIRA_SAIDA_INVIAVEL"})
        saved.inicio += timedelta(minutes=1)
        saved.fim += timedelta(minutes=1)
        with self.assertRaises(HTTPException) as raised:
            agenda._validar_deslocamento_agendamento(self.db, saved, agendamento_id_excluir=saved.id)
        self.assertEqual(raised.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")

    def test_missing_route_stays_blocked_until_admin_confirmation(self):
        with patch.object(agenda, "_obter_deslocamento_primeira_saida", return_value=(None, "rota_indisponivel")):
            with self.assertRaises(HTTPException) as raised:
                self.create()
            self.assertEqual(raised.exception.detail["codigo"], "PRIMEIRA_SAIDA_INVIAVEL")
            result = self.create(confirmar_conflito_deslocamento=True,
                                 motivo_excecao_deslocamento="Administrador conferiu o trajeto presencialmente.")
        self.assertTrue(result["excecao_deslocamento_ativa"])

    def test_confirmed_exception_does_not_bypass_occupied_slot(self):
        self.create(confirmar_conflito_deslocamento=True)
        self.audit.reset_mock()
        with self.assertRaises(HTTPException) as raised:
            self.create(confirmar_conflito_deslocamento=True)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("indisponivel", str(raised.exception.detail).lower())
        self.assertEqual(self.db.query(Agendamento).count(), 1)
        self.audit.assert_not_called()
