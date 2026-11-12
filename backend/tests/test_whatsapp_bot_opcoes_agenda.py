import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-opcoes-agenda-1234567890")
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.servico import Servico
from app.models.whatsapp_bot import WhatsAppBotResposta as Resposta, WhatsAppBotSolicitacao as Pedido
from app.models.alerta_interno import AlertaInterno
from app.services import whatsapp_bot_opcoes_agenda as op
from app.services.whatsapp_bot_fila import registrar
from app.services.whatsapp_bot_continuidade import registrar_complemento


class OpcoesTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        for model in (Servico, Resposta, Pedido, AlertaInterno): model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.now = datetime(2099, 5, 20, 7, tzinfo=op.TZ)
        self.service = Servico(id=1,nome='Ecocardiograma',ativo=True,duracao_minutos=30)
        self.db.add(self.service); self.db.commit()
        self.coleta = {'clinica_id':9,'status':'encaminhada','dados':{'exame':'eco','paciente':'Teste','tutor':'Tutor teste','preferencia':'qualquer dia pela manhã'}}
        self.items = [{'inicio':f'2099-05-20 {hour}:00','fim':f'2099-05-20 {hour}:30','risco':0,'paciente':'NÃO EXPOR'} for hour in ('08','09','10','11')]

    def seed(self, decisao='sent'):
        with patch.object(op,'consultar_dia',return_value=self.items):
            text, data = op.oferecer(self.db,9,self.coleta,now=self.now)
        self.r=Resposta(job_id=1,wa_identity='test',conversation_id='49',clinica_id=9,decisao=decisao,
            texto_gerado=text,texto_enviado=text,tools_usadas=json.dumps({'solicitacao_agendamento':self.coleta,op.KEY:data}))
        self.db.add(self.r);self.db.commit()
        if decisao == 'sent':
            registrar(self.db,self.r,self.coleta);self.db.commit()
            self.p=self.db.query(Pedido).one()
        return text,data

    def choose(self, message='2', **kwargs):
        return op.responder(self.db,self.p,self.coleta,message,'test','49',now=kwargs.get('now',self.now))

    def test_offer_exact_duration_scope_limit_and_no_private_context(self):
        with patch.object(op,'consultar_dia',return_value=self.items) as query:
            text,data=op.oferecer(self.db,9,self.coleta,now=self.now)
        self.assertEqual(len(data['slots']),3)
        self.assertEqual(query.call_args.args[1],9)
        self.assertEqual(query.call_args.args[2].id,1)
        self.assertNotIn('NÃO EXPOR',text)
        self.assertTrue(op.validar_renderizado(text,{op.KEY:data}))
        self.assertEqual(self.db.query(Pedido).count(),0)
        self.assertFalse(self.db.new)

    def test_choice_requeries_and_records_preference_without_changing_summary(self):
        self.seed()
        with patch.object(op,'consultar_dia',return_value=self.items) as query:
            text,audit=self.choose()
        query.assert_called_once()
        self.assertIn('09:00',text)
        before=self.p.resumo
        response=Resposta(job_id=2,wa_identity='test',conversation_id='49',clinica_id=9,decisao='draft',tools_usadas=json.dumps(audit))
        self.db.add(response);self.db.flush()
        registrar_complemento(self.db,response);registrar_complemento(self.db,response)
        events=json.loads(self.p.historico)
        self.assertEqual(len([e for e in events if e['acao']=='complemento_cliente']),1)
        self.assertEqual(events[-1]['horario_preferido'],'2099-05-20T09:00:00-03:00')
        self.assertEqual(self.p.resumo,before)
        self.assertIsNone(self.p.agendamento_id)
        self.assertEqual(self.db.query(Pedido).count(),1)

    def test_unavailable_or_changed_service_does_not_accept_choice(self):
        self.seed()
        with patch.object(op,'consultar_dia',return_value=[]):
            text,audit=self.choose()
        self.assertIn('Não consegui revalidar',text)
        self.assertNotIn('continuidade_pedido',audit)
        self.service.duracao_minutos=60
        with patch.object(op,'consultar_dia') as query:
            self.choose()
        query.assert_not_called()

    def test_expiration_wrong_number_scope_and_negation(self):
        self.seed()
        with patch.object(op,'consultar_dia') as query:
            self.assertIn('expirou',self.choose(now=self.now+timedelta(minutes=16))[0])
            self.assertIn('opção não',self.choose('9')[0])
            self.assertIsNone(self.choose('Não quero a opção 2'))
            self.assertIsNone(op.responder(self.db,self.p,self.coleta,'2','test','other',now=self.now))
        query.assert_not_called()

    def test_draft_or_edited_offer_cannot_be_selected(self):
        self.seed();self.r.decisao='draft';self.db.commit()
        with patch.object(op,'consultar_dia') as query:
            self.assertIn('nova lista',self.choose()[0])
        query.assert_not_called()
        self.r.decisao='sent';self.r.texto_enviado='Texto editado';self.db.commit()
        self.assertIsNone(op.ultima_oferta(self.db,self.p,'test','49'))

    def test_human_or_closed_request_and_corrections_prevent_offer(self):
        self.seed();self.p.responsavel_id=3
        with patch.object(op,'consultar_dia') as query:
            self.assertIn('equipe',self.choose()[0])
        query.assert_not_called()
        self.p.responsavel_id=None;self.p.historico=json.dumps([{'acao':'complemento_cliente','observacao':'Mudou o exame'}])
        with patch.object(op,'consultar_dia') as query:
            self.assertIn('atualização',self.choose('ver horários')[0])
        query.assert_not_called()

    def test_unknown_preference_ambiguous_service_and_risk_fail_closed(self):
        self.coleta['dados']['preferencia']='depois do almoço, exceto terça'
        with patch.object(op,'consultar_dia') as query:
            self.assertEqual(op.oferecer(self.db,9,self.coleta,now=self.now)[1]['estado'],'indisponivel')
        query.assert_not_called()
        self.coleta['dados']['preferencia']='sem preferência'
        self.db.add(Servico(nome='Eco',ativo=True,duracao_minutos=30));self.db.commit()
        # Nome exato só é aceito quando único; composição com dois candidatos é ambígua.
        self.coleta['dados']['exame']='ecodopplercardiograma'
        with patch.object(op,'consultar_dia') as query:
            self.assertEqual(op.oferecer(self.db,9,self.coleta,now=self.now)[1]['estado'],'indisponivel')
        query.assert_not_called()
        self.assertEqual(op.slots_seguros([dict(self.items[0],risco=1)],self.service,self.now.date(),self.now),[])

    def test_relative_preference_anchored_to_original_message(self):
        dates,turno=op.periodo('amanhã',self.now.isoformat(),self.now)
        self.assertEqual(dates,[self.now.date()+timedelta(days=1)])
        self.assertIsNone(turno)
        with self.assertRaises(ValueError): op.periodo('amanhã',self.now.isoformat(),self.now+timedelta(days=3))

    def test_week_preferences_use_fortaleza_message_date_and_keep_original_week(self):
        # Já é segunda em UTC, mas a mensagem ainda foi recebida no domingo local.
        recebida = '2026-10-05T01:00:00Z'
        now = datetime(2026, 10, 5, 7, tzinfo=op.TZ)
        for text, turno in (('na próxima semana à tarde', 'tarde'),
                            ('semana que vem pela manhã', 'manha')):
            criteria = op.interpretar_preferencia(text, recebida, now)
            self.assertEqual(criteria, {'data_inicio': '2026-10-05', 'data_fim': '2026-10-11', 'turno': turno})
            dates, parsed_turno = op.periodo(text, recebida, now)
            self.assertEqual(len(dates), 7)
            self.assertEqual(parsed_turno, turno)
            with self.assertRaises(ValueError):
                op.periodo(text, recebida, now + timedelta(days=7))
        dates, turno = op.periodo('esta semana pela manhã', '2026-10-02T10:00:00-03:00', now - timedelta(days=1))
        self.assertEqual([day.isoformat() for day in dates], ['2026-10-04'])
        self.assertEqual(turno, 'manha')

    def test_unknown_or_conflicting_week_preferences_fail_closed(self):
        for text in ('próxima semana menos terça', 'manhã ou tarde', 'não pela manhã',
                     'na próxima semana à tarde depois das 15h'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                op.interpretar_preferencia(text, self.now.isoformat(), self.now)

    def test_relative_preference_without_message_date_is_not_reanchored(self):
        for text in ('amanhã', 'esta semana', 'próxima semana pela manhã', 'sexta-feira'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                op.interpretar_preferencia(text, now=self.now)
        self.assertEqual(op.interpretar_preferencia('pela manhã', now=self.now), {'turno': 'manha'})
        self.assertEqual(op.interpretar_preferencia('20/05/2099 à tarde', now=self.now),
            {'data_inicio': '2099-05-20', 'data_fim': '2099-05-20', 'turno': 'tarde'})

    def test_turno_is_sent_to_engine_before_its_ranking(self):
        from app.api.v1.endpoints import agenda
        criteria = {'turno': 'tarde'}
        with patch.object(agenda, 'sugerir_horarios_agenda', return_value={'ok': True, 'items': []}) as engine:
            op.consultar_dia(self.db, 9, self.service, self.now.date(), preferencia=criteria)
        payload = engine.call_args.kwargs['payload']
        self.assertEqual(payload.preferencia.turno, 'tarde')
        self.assertEqual(payload.intervalo_minutos, 15)

    def test_choice_revalidation_preserves_original_preference(self):
        _text, offer = self.seed()
        self.coleta['dados']['preferencia'] = 'pela tarde'
        with patch.object(op, 'consultar_dia', return_value=self.items) as query:
            text, audit = self.choose()
        self.assertIn('Recebi sua escolha', text)
        self.assertEqual(query.call_args.kwargs['preferencia'], offer['preferencia_agenda'])
        self.assertEqual(query.call_args.kwargs['preferencia']['turno'], 'manha')
        self.assertIsNone(self.p.agendamento_id)

    def test_whole_service_must_fit_turno_and_explicit_hours(self):
        items = [
            {'inicio': '2099-05-20T11:45:00-03:00', 'fim': '2099-05-20T12:15:00-03:00', 'risco': 0},
            {'inicio': '2099-05-20T13:00:00-03:00', 'fim': '2099-05-20T13:30:00-03:00', 'risco': 0},
            {'inicio': '2099-05-20T17:45:00-03:00', 'fim': '2099-05-20T18:15:00-03:00', 'risco': 0},
        ]
        self.assertEqual(op.slots_seguros(items, self.service, self.now.date(), self.now, 'manha'), [])
        accepted = op.slots_seguros(items, self.service, self.now.date(), self.now,
                                    preferencia={'turno': 'tarde', 'hora_inicio': '13:00', 'hora_fim': '14:00'})
        self.assertEqual(accepted, [{k: items[1][k] for k in ('inicio', 'fim')}])

    def test_generation_offers_after_confirmation_and_keeps_simulation_readonly(self):
        from app.services.whatsapp_bot_generation import gerar_resposta
        initial = dict(self.coleta, status='aguardando_confirmacao')
        self.db.add(Resposta(job_id=1,wa_identity='test',conversation_id='49',clinica_id=9,decisao='sent',tools_usadas=json.dumps({'solicitacao_agendamento':initial})))
        self.db.commit()
        context={'resolution':'matched','match_type':'clinica','clinicas':[{'id':9,'nome':'Teste'}]}
        provider=Mock()
        with patch('app.services.whatsapp_bot_generation._resolver_contexto',return_value=context), patch('app.services.whatsapp_bot_generation.resolve_modo_efetivo',return_value=('auto',None)), patch.object(op,'consultar_dia',return_value=self.items), patch.object(op,'datetime',wraps=datetime) as clock:
            clock.now.return_value=self.now
            result=gerar_resposta(self.db,wa_identity='test',conversation_id='49',corpo_mensagem='Confirmo os dados',modo='auto',provider=provider)
        provider.generate.assert_not_called()
        self.assertTrue(result.auto_elegivel,result.motivo)
        self.assertEqual(json.loads(result.tools_usadas)[op.KEY]['estado'],'oferta')
        self.assertIn('Ainda não há reserva',result.texto_gerado)
        self.assertEqual(self.db.query(Pedido).count(),0)

    def test_concurrent_update_keeps_choice_for_review_without_accepted_highlight(self):
        self.seed()
        with patch.object(op,'consultar_dia',return_value=self.items):
            text,audit=self.choose()
        self.p.versao += 1
        self.db.commit()
        response=Resposta(job_id=2,wa_identity='test',conversation_id='49',clinica_id=9,decisao='draft',texto_gerado=text,tools_usadas=json.dumps(audit))
        self.db.add(response);self.db.flush()
        registrar_complemento(self.db,response)
        self.assertIn('mudou durante',response.texto_gerado)
        self.assertIsNone(json.loads(self.p.historico)[-1]['horario_preferido'])
        self.assertEqual(json.loads(response.tools_usadas)[op.KEY]['estado'],'equipe')

    def test_revision_and_delivery_expiration(self):
        self.seed()
        self.assertTrue(op.envio_vigente(self.r,self.now))
        self.assertFalse(op.envio_vigente(self.r,self.now+timedelta(minutes=16)))
        self.p.versao += 1
        with patch.object(op,'consultar_dia') as query:
            self.assertNotIn('continuidade_pedido',self.choose()[1])
        query.assert_not_called()

    def test_actual_agenda_engine_rechecks_occupied_slot(self):
        from tests.test_agenda_sugestao_janela_operacional import AgendaSugestaoJanelaOperacionalTest
        from app.api.v1.endpoints import agenda
        helper=AgendaSugestaoJanelaOperacionalTest()
        tmp,db,engine=helper._build_session()
        try:
            helper._seed_config(db,excecoes=[])
            clinic,_=helper._seed_clinicas(db)
            service=helper._seed_servico(db,nome='Ecocardiograma',duracao_minutos=30)
            with patch.object(agenda,'_obter_duracao_deslocamento_operacional',return_value=(0,'teste')), patch.object(
                agenda, 'estimar_deslocamento', return_value=(2.0,5,'google_distance_matrix_traffic')
            ):
                before=op.slots_seguros(op.consultar_dia(db,clinic.id,service,self.now.date()),service,self.now.date(),self.now)
                self.assertTrue(before)
                chosen=before[0]
                helper._criar_agendamento(db,clinica_id=clinic.id,data='2099-05-20',hora=op.local(chosen['inicio']).strftime('%H:%M'))
                after=op.slots_seguros(op.consultar_dia(db,clinic.id,service,self.now.date()),service,self.now.date(),self.now)
                self.assertNotIn(chosen,after)
        finally:
            helper.doCleanups()
            db.close();engine.dispose();tmp.cleanup()

    def test_consulta_disponibilidade_sem_modelo_e_sem_duplicar_pedido(self):
        from app.services.whatsapp_bot_generation import gerar_resposta
        context={'resolution':'matched','match_type':'clinica','clinicas':[{'id':9,'nome':'Teste'}]}
        provider=Mock()
        with patch('app.services.whatsapp_bot_generation._resolver_contexto',return_value=context), patch('app.services.whatsapp_bot_generation.resolve_modo_efetivo',return_value=('auto',None)):
            result=gerar_resposta(self.db,wa_identity='test',conversation_id='49',corpo_mensagem='Qual a disponibilidade pra eco?',modo='auto',provider=provider)
            self.assertTrue(result.auto_elegivel)
            self.assertEqual(json.loads(result.tools_usadas)['solicitacao_agendamento']['dados'],{'exame':'eco'})
            self.assertIn('nome do paciente',result.texto_gerado)
            self.assertEqual(self.db.query(Pedido).count(),0)
            self.seed(); self.p.status='cancelado'; self.db.commit()
            result=gerar_resposta(self.db,wa_identity='test',conversation_id='49',corpo_mensagem='Qual a disponibilidade pra eco?',modo='auto',provider=provider)
            self.assertIn('nova solicitação de eco',result.texto_gerado)
            self.assertTrue(result.auto_elegivel)
            result=gerar_resposta(self.db,wa_identity='test',conversation_id='49',corpo_mensagem='Novo pedido',modo='auto',provider=provider)
            self.assertEqual(json.loads(result.tools_usadas)['solicitacao_agendamento']['status'],'coletando')
        provider.generate.assert_not_called()
        self.assertEqual(self.db.query(Pedido).count(),1)

    def test_disponibilidade_nao_captura_mensagem_clinica_ou_mista(self):
        from app.services.whatsapp_bot_agendamento import exame_em_consulta_disponibilidade as extrair
        for text in ('Qual a disponibilidade pra eco?', 'Quais horários disponíveis para ecocardiograma?', 'Tem horário para ECG?'):
            self.assertIsNotNone(extrair(text))
        for text in ('Não quero horário para eco', 'Qual a disponibilidade pra eco? Meu pet está com falta de ar', 'Qual o valor do eco?', 'Qual horário do meu eco?', 'Qual a disponibilidade pra eco amanhã?'):
            self.assertIsNone(extrair(text))
