import json
from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from tests import test_agenda_concorrencia_slot as fixture
from app.api.v1.endpoints import agenda
from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.agendamento import Agendamento
from app.models.servico import Servico


class AgendaSobreposicaoAdminTest(fixture.AgendaConcorrenciaSlotTest):
    def setUp(self):
        super().setUp()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for nome in ('registrar_auditoria', '_notificar_agenda_update', '_validar_deslocamento_agendamento'):
            mock = self.stack.enter_context(patch.object(agenda, nome, return_value=None))
            if nome == 'registrar_auditoria':
                self.auditoria = mock
        self.admin = SimpleNamespace(id=91, nome='Admin Sintetico', tem_papel=lambda p: p == 'admin')
        self.secretaria = SimpleNamespace(id=92, nome='Secretaria Sintetica', tem_papel=lambda _: False)

    def criar(self, db, payload, usuario=None):
        return agenda.criar_agendamento(payload, SimpleNamespace(), db, usuario or self.admin)

    def preparar(self, db):
        db.query(Servico).filter(Servico.id == self.servico_id).update({'duracao_minutos': 45})
        db.commit()
        ocupado = self._payload().model_copy(update={'inicio': datetime(2099, 5, 27, 8, 30)})
        self.criar(db, ocupado)
        candidato = self._payload().model_copy(update={'inicio': datetime(2099, 5, 27, 8), 'fim': datetime(2099, 5, 27, 8, 30)})
        with self.assertRaises(HTTPException) as erro:
            self.criar(db, candidato)
        self.assertEqual(erro.exception.status_code, 409)
        detalhe = erro.exception.detail
        self.assertEqual(detalhe['codigo'], 'CONFLITO_SOBREPOSICAO_AGENDA')
        return candidato, detalhe['escopo']

    def confirmado(self, payload, token, **campos):
        return payload.model_copy(update={
            'confirmar_sobreposicao': True,
            'escopo_sobreposicao_confirmado': token,
            'motivo_excecao_sobreposicao': 'Admin autorizou os 15 minutos de sobreposicao.',
            **campos,
        })

    def test_admin_autoriza_15_minutos_sem_reduzir_duracao_e_persiste_auditoria(self):
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            resposta = self.criar(db, self.confirmado(payload, token))
            self.assertTrue(resposta['fim'].endswith('08:45:00'))
            concessao = resposta['excecao_sobreposicao']
            self.assertEqual(concessao['concedida_por_id'], self.admin.id)
            self.assertEqual(concessao['confirmacao'], token)
            self.assertTrue(concessao['concedida_em'])
            self.assertEqual(len(concessao['intervalos_conflitantes']), 1)
            self.assertTrue(concessao['intervalos_conflitantes'][0]['inicio'].endswith('08:30:00'))
            gravado = db.get(Agendamento, resposta['id'])
            self.assertEqual(json.loads(gravado.excecao_sobreposicao), concessao)
            eventos = [c.kwargs for c in self.auditoria.call_args_list if c.kwargs['acao'] == 'AGENDAMENTO_CRIADO']
            self.assertEqual(eventos[-1]['detalhes']['excecao_sobreposicao'], concessao)
            self.assertEqual(db.query(Agendamento).count(), 2)

    def test_nao_admin_nao_autoriza_mesmo_com_token_correto(self):
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            with self.assertRaises(HTTPException) as erro:
                self.criar(db, self.confirmado(payload, token), self.secretaria)
            self.assertEqual(erro.exception.status_code, 403)
            self.assertEqual(db.query(Agendamento).count(), 1)

    def test_motivo_vazio_e_token_obsoleto_nao_salvam(self):
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            with self.assertRaises(HTTPException) as erro:
                self.criar(db, self.confirmado(payload, token, motivo_excecao_sobreposicao='  '))
            self.assertEqual(erro.exception.status_code, 422)
            with self.assertRaises(HTTPException) as erro:
                self.criar(db, self.confirmado(payload, '0' * 64))
            self.assertEqual(erro.exception.status_code, 409)
            self.assertEqual(erro.exception.detail['escopo'], token)
            self.assertEqual(db.query(Agendamento).count(), 1)

    def test_flag_de_rota_nao_libera_sobreposicao(self):
        with self._session_factory() as db:
            payload, _ = self.preparar(db)
            with self.assertRaises(HTTPException) as erro:
                self.criar(db, payload.model_copy(update={'confirmar_conflito_deslocamento': True}))
            self.assertEqual(erro.exception.status_code, 409)

    def test_novo_conflito_entre_revisao_e_salvamento_invalida_token(self):
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            novo = Agendamento(inicio=datetime(2099, 5, 27, 8, 10), fim=datetime(2099, 5, 27, 8, 20), status='Agendado')
            db.add(novo)
            db.commit()
            with self.assertRaises(HTTPException) as erro:
                self.criar(db, self.confirmado(payload, token))
            self.assertNotEqual(erro.exception.detail['escopo'], token)
            self.assertEqual(len(erro.exception.detail['conflitos']), 2)

    def test_concessao_persiste_em_edicao_e_revalidacao_de_status(self):
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            resposta = self.criar(db, self.confirmado(payload, token))
            atualizado = agenda.atualizar_agendamento(resposta['id'], agenda.AgendamentoUpdate(observacoes='Revisado'), SimpleNamespace(), db, self.secretaria)
            self.assertEqual(atualizado['excecao_sobreposicao'], resposta['excecao_sobreposicao'])
            item = db.get(Agendamento, resposta['id'])
            item.status = 'Confirmado'
            agenda._validar_slot_disponivel(db, item, agendamento_id_excluir=item.id)
            self.assertTrue(item.excecao_sobreposicao)

    def test_slot_autorizado_continua_ocupado_para_solicitacao_comum(self):
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            self.criar(db, self.confirmado(payload, token))
            # Serviço de 15 minutos às 08:00 conflita apenas com o autorizado.
            curto = Servico(nome='Servico curto sintetico', duracao_minutos=15, ativo=True)
            db.add(curto)
            db.commit()
            terceiro = payload.model_copy(update={'servico_id': curto.id})
            with self.assertRaises(HTTPException) as erro:
                self.criar(db, terceiro)
            self.assertEqual(erro.exception.detail['codigo'], 'CONFLITO_SOBREPOSICAO_AGENDA')

    def test_atendimento_original_pode_ser_confirmado_mas_nao_movido_sem_revisao(self):
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            original = db.query(Agendamento).one()
            self.criar(db, self.confirmado(payload, token))
            with patch.object(agenda, '_validar_paciente_tutor_para_status'):
                resposta = agenda.atualizar_status(
                    original.id, SimpleNamespace(), 'Confirmado', db=db, current_user=self.secretaria,
                )
            self.assertEqual(resposta['status'], 'Confirmado')
            self.assertIsNone(original.excecao_sobreposicao)
            with self.assertRaises(HTTPException) as erro:
                agenda.atualizar_agendamento(
                    original.id, agenda.AgendamentoUpdate(inicio=datetime(2099, 5, 27, 8, 35)),
                    SimpleNamespace(), db, self.secretaria,
                )
            self.assertEqual(erro.exception.detail['codigo'], 'CONFLITO_SOBREPOSICAO_AGENDA')

    def test_slot_autorizado_bloqueia_nova_ocupacao_apos_meia_noite(self):
        with self._session_factory() as db:
            db.add(Agendamento(
                inicio=datetime(2099, 5, 27, 23, 45), fim=datetime(2099, 5, 28, 0, 30),
                data='2099-05-27', hora='23:45', status='Agendado',
                excecao_sobreposicao='{"escopo":"concessao_sintetica"}',
            ))
            db.commit()
            novo = Agendamento(
                inicio=datetime(2099, 5, 28, 0, 15), fim=datetime(2099, 5, 28, 0, 45),
                status='Agendado',
            )
            with self.assertRaises(HTTPException) as erro:
                agenda._validar_slot_disponivel(db, novo, detalhar_sobreposicao=True)
            self.assertEqual(erro.exception.detail['codigo'], 'CONFLITO_SOBREPOSICAO_AGENDA')

    def test_mudar_horario_exige_nova_revisao_e_nao_admin_nao_pode_confirmar_put(self):
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            resposta = self.criar(db, self.confirmado(payload, token))
            for usuario, confirmar, esperado in [(self.admin, False, 409), (self.secretaria, True, 403)]:
                with self.assertRaises(HTTPException) as erro:
                    agenda.atualizar_agendamento(resposta['id'], agenda.AgendamentoUpdate(
                        inicio=datetime(2099, 5, 27, 8, 5), confirmar_sobreposicao=confirmar,
                        escopo_sobreposicao_confirmado=token, motivo_excecao_sobreposicao='Confirmacao antiga',
                    ), SimpleNamespace(), db, usuario)
                self.assertEqual(erro.exception.status_code, esperado)
                db.rollback()
            db.refresh(db.get(Agendamento, resposta['id']))
            self.assertEqual(db.get(Agendamento, resposta['id']).hora, '08:00')

    def test_put_autoriza_conflito_revisado(self):
        with self._session_factory() as db:
            payload, _ = self.preparar(db)
            separado = self.criar(db, payload.model_copy(update={'inicio': datetime(2099, 5, 27, 10)}))
            mudanca = agenda.AgendamentoUpdate(inicio=payload.inicio)
            with self.assertRaises(HTTPException) as erro:
                agenda.atualizar_agendamento(separado['id'], mudanca, SimpleNamespace(), db, self.admin)
            token = erro.exception.detail['escopo']
            db.rollback()
            resposta = agenda.atualizar_agendamento(separado['id'], self.confirmado(mudanca, token), SimpleNamespace(), db, self.admin)
            self.assertTrue(resposta['excecao_sobreposicao'])

    def test_bloqueio_administrativo_nao_e_sobreposto(self):
        AgendaBloqueio.__table__.create(self._engine, checkfirst=True)
        with self._session_factory() as db:
            payload, token = self.preparar(db)
            db.add(AgendaBloqueio(id='bloqueio-sintetico', criado_por_id=self.admin.id, inicio=payload.inicio, fim=payload.inicio+timedelta(hours=1), ativo=True, motivo='Bloqueio sintetico'))
            db.commit()
            with self.assertRaises(HTTPException) as erro:
                self.criar(db, self.confirmado(payload, token))
            self.assertIn('slot esta bloqueado', erro.exception.detail)
