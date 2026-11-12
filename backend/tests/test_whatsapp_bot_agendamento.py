import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('SECRET_KEY', 'teste-coleta-agendamento-chave-local')
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.whatsapp_bot import WhatsAppBotSolicitacao
from app.models.whatsapp_bot import WhatsAppBotResposta
from app.schemas.whatsapp_bot import WhatsAppBotColetaAgendamento as Update
from app.services.whatsapp_bot_agendamento import preparar, carregar, validar_texto, encaminhar, KEY
import json

class ColetaTests(unittest.TestCase):
    def test_multi_turn_and_explicit_confirmation(self):
        s,t = preparar(None, Update(exame='ecocardiograma'), 'Quero ecocardiograma', 9, {})
        self.assertNotIn('exame solicitado,', t)
        s,t = preparar(s, Update(paciente='Rex', tutor='Maria'), 'Rex da Maria', 9, {})
        self.assertEqual(s['dados']['exame'], 'ecocardiograma')
        s,t = preparar(s, Update(preferencia='amanhã às 14:30'), 'amanhã às 14:30', 9, {})
        self.assertEqual(s['status'], 'aguardando_confirmacao')
        self.assertTrue(validar_texto(s,t).aprovado)
        s2,t = preparar(s, None, 'confirmar dados', 9, {})
        self.assertEqual(s2['status'], 'aguardando_confirmacao') # draft never sent
        s['resumo_enviado'] = True
        done,t = preparar(s, None, 'confirmar dados', 9, {})
        self.assertEqual(done['status'], 'encaminhada')
        self.assertIn('Nenhum horário foi reservado', t)
        self.assertTrue(validar_texto(done, t).aprovado)

    def test_greeting_only_once_per_session(self):
        from app.services.whatsapp_bot_agendamento import saudacao_inicial
        engine = create_engine('sqlite://')
        WhatsAppBotResposta.__table__.create(engine)
        with Session(engine) as db:
            self.assertTrue(saudacao_inicial(db, 'phone', 'Boa noite'))
            self.assertFalse(saudacao_inicial(db, 'phone', 'Obrigado'))
            db.add(WhatsAppBotResposta(job_id=1, wa_identity='phone', conversation_id='1', decisao='sent', created_at=datetime.now(timezone.utc)))
            db.flush()
            self.assertFalse(saudacao_inicial(db, 'phone', 'Boa noite'))
            self.assertTrue(saudacao_inicial(db, 'other', 'Boa noite'))
        engine.dispose()

    def test_natural_confirmation_rejects_negation_and_correction(self):
        state = {'dados': {'exame': 'eco', 'paciente': 'Rex', 'tutor': 'Maria', 'preferencia': 'manhã'}, 'status': 'aguardando_confirmacao', 'resumo_enviado': True}
        for message in ('Confirmo os dados', 'Está correto!', 'Pode seguir', 'Tudo certo'):
            self.assertEqual(preparar(state, None, message, 9, {})[0]['status'], 'encaminhada')
        for message in ('Não confirmo os dados', 'Está correto?', 'Confirmo, mas o tutor é João'):
            self.assertEqual(preparar(state, None, message, 9, {})[0]['status'], 'aguardando_confirmacao')
        changed, _ = preparar(state, Update(tutor='João'), 'Confirmo, mas o tutor é João', 9, {})
        self.assertEqual(changed['status'], 'aguardando_confirmacao')
        self.assertEqual(changed['dados']['tutor'], 'João')

    def test_untrusted_extraction_and_corrections(self):
        s,_ = preparar(None, Update(paciente='Inventado'), 'Quero agendar', 9, {})
        self.assertNotIn('paciente', s['dados'])
        s = {'dados':{'exame':'eco','paciente':'Rex','tutor':'Maria','preferencia':'amanhã'},'origens':{'tutor':'cadastro'},'status':'aguardando_confirmacao','resumo_enviado':True}
        changed,t = preparar(s, Update(paciente='Luna'), 'Na verdade é Luna', 9, {})
        self.assertNotIn('tutor', changed['dados'])
        self.assertEqual(changed['status'], 'coletando')

    def test_reuse_only_unique_selected_patient(self):
        context = {'pets':[{'id':1,'nome':'Rex','tutor_id':2}], 'tutores':[{'id':2,'nome':'Maria'}]}
        s,_ = preparar(None, Update(paciente='Rex'), 'Rex', 9, context)
        self.assertEqual(s['dados']['tutor'], 'Maria')
        context['pets'].append({'id':3,'nome':'Rex','tutor_id':4})
        s,_ = preparar(None, Update(paciente='Rex'), 'Rex', 9, context)
        self.assertNotIn('tutor', s['dados'])

    def test_cancel_and_clinical_guard(self):
        s,t=preparar(None,None,'cancelar solicitação',9,{})
        self.assertEqual(s['status'],'cancelada')
        self.assertTrue(validar_texto(s,t).aprovado)
        self.assertFalse(validar_texto({'dados':{}},'Tomar pimobendan 2 mg').aprovado)
        self.assertFalse(validar_texto({'dados':{}},'x'*901).aprovado)

    def test_persistence_scope_expiry_and_unsent_confirmation(self):
        e=create_engine('sqlite://')
        WhatsAppBotSolicitacao.__table__.create(e)
        WhatsAppBotResposta.__table__.create(e)
        with Session(e) as db:
            state={'clinica_id':9,'status':'coletando','dados':{'exame':'eco'}}
            r=WhatsAppBotResposta(job_id=1,wa_identity='phone',conversation_id='1',clinica_id=9,decisao='sent',tools_usadas=json.dumps({KEY:state}),created_at=datetime.now(timezone.utc))
            db.add(r);db.commit()
            self.assertEqual(carregar(db,'phone',9)['dados']['exame'],'eco')
            self.assertIsNone(carregar(db,'other',9));self.assertIsNone(carregar(db,'phone',16))
            r.created_at=datetime.now(timezone.utc)-timedelta(days=3);db.commit()
            self.assertIsNone(carregar(db,'phone',9))
        e.dispose()

    def test_handoff_once_after_sent(self):
        r=SimpleNamespace(decisao='draft',tools_usadas=json.dumps({KEY:{'status':'encaminhada','dados':{}}}),wa_identity='phone',conversation_id='1')
        with patch('app.services.whatsapp_bot_handoff_service.trigger_active_handoff') as handoff, patch('app.services.whatsapp_bot_fila.registrar'):
            encaminhar(None,r);handoff.assert_not_called()
            r.decisao='sent';encaminhar(None,r);encaminhar(None,r)
            self.assertEqual(handoff.call_count,1)

    def test_central_keeps_summary_during_pause_but_hides_reassigned_identity(self):
        from app.models.configuracao import Configuracao
        from app.models.whatsapp_bot import WhatsAppBotConversaEstado
        from app.api.v1.endpoints.whatsapp_bot import _estado_payload
        engine=create_engine('sqlite://')
        for model in (Configuracao, WhatsAppBotConversaEstado, WhatsAppBotResposta, WhatsAppBotSolicitacao):
            model.__table__.create(engine)
        with Session(engine) as db:
            db.add(WhatsAppBotResposta(job_id=1,wa_identity='phone',conversation_id='1',clinica_id=9,decisao='sent',tools_usadas=json.dumps({KEY:{'clinica_id':9,'status':'encaminhada','dados':{'paciente':'Rex'}}})))
            db.add(WhatsAppBotResposta(job_id=2,wa_identity='phone',conversation_id='1',decisao='suppressed',motivo='pausado'))
            db.commit()
            with patch('app.services.whatsapp_bot_generation._resolver_contexto',return_value={'resolution':'matched','match_type':'clinica','clinicas':[{'id':9}]}):
                self.assertIn('Rex',_estado_payload(db,'phone')['solicitacao_agendamento']['resumo'])
            with patch('app.services.whatsapp_bot_generation._resolver_contexto',return_value={'resolution':'ambiguous'}):
                self.assertIsNone(_estado_payload(db,'phone')['solicitacao_agendamento'])
        engine.dispose()

    def test_unknown_and_new_request(self):
        s,_=preparar(None,Update(tutor='não sei'),'não sei',9,{})
        self.assertNotIn('tutor',s['dados'])
        s,_=preparar({'status':'coletando','dados':{'paciente':'Rex'}},None,'nova solicitação',9,{})
        self.assertEqual(s['dados'],{})

class GenerationIntegrationTests(unittest.TestCase):
    def test_clinic_pipeline_persists_only_via_caller_and_resumes(self):
        from unittest.mock import Mock
        from app.schemas.whatsapp_bot import WhatsAppBotReplyOutput
        from app.services.whatsapp_bot_providers import GeneratedReply
        from app.services.whatsapp_bot_generation import gerar_resposta
        engine = create_engine('sqlite://')
        WhatsAppBotSolicitacao.__table__.create(engine, checkfirst=True)
        WhatsAppBotResposta.__table__.create(engine)
        context = {'resolution':'matched','match_type':'clinica','clinicas':[{'id':9,'nome':'Clinica teste'}]}
        provider=Mock()
        with Session(engine) as db, patch('app.services.whatsapp_bot_generation._resolver_contexto',return_value=context), patch('app.services.whatsapp_bot_generation.resolve_modo_efetivo',return_value=('auto',None)):
            for i,(message,update) in enumerate([
                ('Quero ecocardiograma',Update(exame='ecocardiograma')),
                ('Rex da Maria',Update(paciente='Rex',tutor='Maria')),
                ('amanhã às 14:30',Update(preferencia='amanhã às 14:30')),
                ('confirmar dados',None),
            ],1):
                provider.generate.return_value=GeneratedReply(output=WhatsAppBotReplyOutput(intent='solicitar_agendamento',texto='Texto do modelo ignorado',solicitacao_agendamento=update),model='fake')
                result=gerar_resposta(db,wa_identity='phone',corpo_mensagem=message,modo='auto',provider=provider)
                self.assertTrue(result.auto_elegivel, result.motivo)
                self.assertEqual(db.query(WhatsAppBotResposta).count(),i-1)
                self.assertNotIn('Texto do modelo ignorado', result.texto_gerado)
                db.add(WhatsAppBotResposta(job_id=i,wa_identity='phone',conversation_id='1',clinica_id=9,decisao='sent',tools_usadas=result.tools_usadas))
                db.commit()
            state=json.loads(result.tools_usadas)[KEY]
            self.assertEqual(state['status'],'encaminhada')
            self.assertEqual(state['dados']['exame'],'ecocardiograma')
            self.assertIn('coleta_agendamento',provider.generate.call_args.kwargs['payload'])
        engine.dispose()

if __name__ == '__main__':unittest.main()
