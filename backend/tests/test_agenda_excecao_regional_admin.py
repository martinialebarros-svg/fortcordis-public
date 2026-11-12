"""Regression: regional validation must honor the same audited admin exception."""
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi import HTTPException, Request

from tests import test_agenda_excecao_deslocamento_persistente as fixtures
from tests.test_agenda_excecao_deslocamento_persistente import ADMIN, SECRETARIA, INICIO_ALVO
from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento


class AgendaExcecaoRegionalAdminTest(unittest.TestCase):
    _build_session = fixtures.AgendaExcecaoDeslocamentoPersistenteTest._build_session
    _seed = fixtures.AgendaExcecaoDeslocamentoPersistenteTest._seed
    _criar_alvo = fixtures.AgendaExcecaoDeslocamentoPersistenteTest._criar_alvo

    def setUp(self):
        self.tmpdir, self.db, self.engine = self._build_session()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.ctx = self._seed(self.db)
        rules = agenda._obter_regras_rota_agenda(self.db)
        rules['route_policy'].update(
            regional_transition_enabled=True,
            regional_transition_max_travel_min=50,
            regional_transition_margin_min=15,
            regional_transition_max_legs_per_day=1,
        )
        for mock in (
            patch.object(agenda, '_obter_regras_rota_agenda', return_value=rules),
            patch.object(agenda, '_obter_duracao_deslocamento_operacional', return_value=(75, 'manual')),
            patch.object(agenda, 'registrar_auditoria'),
            patch.object(agenda, '_notificar_agenda_update'),
        ):
            started = mock.start()
            self.addCleanup(mock.stop)
            if mock.attribute == 'registrar_auditoria':
                self.audit = started

    def payload(self, **changes):
        return agenda.AgendamentoCreate(**{
            'paciente_id': self.ctx.paciente.id, 'tutor_id': self.ctx.tutor.id,
            'clinica_id': self.ctx.clinica_alvo.id, 'servico_id': self.ctx.servico.id,
            'inicio': INICIO_ALVO, 'fim': INICIO_ALVO + timedelta(minutes=30),
            **changes,
        })

    def create(self, payload, user=ADMIN):
        return agenda.criar_agendamento(payload, Request({'type': 'http'}), self.db, user)

    def test_creation_conflict_then_admin_retry_persists_and_audits_exception(self):
        with self.assertRaises(HTTPException) as raised:
            self.create(self.payload())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail['codigo'], 'CONFLITO_DESLOCAMENTO')
        reason = raised.exception.detail['motivo_regional']
        self.assertEqual(reason, 'TRANSICAO_REGIONAL_LIMITE_EXCEDIDO')
        self.assertEqual(self.db.query(Agendamento).count(), 1)

        result = self.create(self.payload(confirmar_conflito_deslocamento=True,
            motivo_excecao_deslocamento='Viagem revisada pelo administrador'))
        self.assertTrue(result['excecao_deslocamento_ativa'])
        self.assertEqual(self.db.query(Agendamento).count(), 2)
        saved = self.db.get(Agendamento, result['id'])
        self.assertEqual(saved.excecao_deslocamento_concedida_por_id, ADMIN.id)
        self.assertEqual(saved.excecao_deslocamento_motivo, 'Viagem revisada pelo administrador')
        event = next(call.kwargs for call in self.audit.call_args_list
            if call.kwargs.get('acao') == 'AGENDA_EXCECAO_DESLOCAMENTO_CONCEDIDA')
        self.assertEqual(event['detalhes']['bloqueio_ignorado'], reason)

    def test_non_admin_cannot_confirm_regional_conflict(self):
        with self.assertRaises(HTTPException) as raised:
            self.create(self.payload(confirmar_conflito_deslocamento=True), SECRETARIA)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(self.db.query(Agendamento).count(), 1)

    def test_persisted_exception_reused_and_invalidated_on_route_change(self):
        result = self.create(self.payload(confirmar_conflito_deslocamento=True))
        saved = self.db.get(Agendamento, result['id'])
        baseline = agenda._listar_agendamentos_ativos_do_dia(
            self.db, saved.data, agendamento_id_excluir=saved.id)
        bypass = agenda._validar_deslocamento_agendamento(self.db, saved,
            agendamento_id_excluir=saved.id, baseline_regional=baseline)
        self.assertEqual(bypass, {'origem': 'excecao_persistida',
            'bloqueio': 'TRANSICAO_REGIONAL_LIMITE_EXCEDIDO'})
        saved.inicio += timedelta(minutes=15)
        saved.fim += timedelta(minutes=15)
        with self.assertRaises(HTTPException) as raised:
            agenda._validar_deslocamento_agendamento(self.db, saved, agendamento_id_excluir=saved.id)
        self.assertEqual(raised.exception.status_code, 409)

    def test_admin_route_exception_does_not_bypass_slot_overlap(self):
        self._criar_alvo(self.db, self.ctx, status='Agendado')
        with self.assertRaises(HTTPException) as raised:
            self.create(self.payload(confirmar_conflito_deslocamento=True))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.db.query(Agendamento).count(), 2)
        self.assertFalse(any(call.kwargs.get('acao') == 'AGENDA_EXCECAO_DESLOCAMENTO_CONCEDIDA'
            for call in self.audit.call_args_list))
