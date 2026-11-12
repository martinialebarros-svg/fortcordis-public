import os,sys,json,unittest,importlib
from pathlib import Path
from datetime import datetime,timedelta
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DATABASE_URL','sqlite://')
os.environ.setdefault('SECRET_KEY','pedido-agenda-test-key-1234567890')
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from starlette.requests import Request
from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.servico import Servico
from app.models.whatsapp_bot import WhatsAppBotResposta as Resposta, WhatsAppBotSolicitacao as Pedido
from app.schemas.agendamento import AgendamentoCreate
from app.services.whatsapp_bot_pedido_agenda import preparar
from app.services.whatsapp_bot_fila import registrar

class PedidoAgendaTests(unittest.TestCase):
    def setUp(self):
        url=os.environ.get('WHATSAPP_PEDIDO_TEST_DATABASE_URL')
        self.admin=None;self.schema=None
        if url:
            from urllib.parse import urlparse
            from uuid import uuid4
            parsed=urlparse(url)
            assert parsed.hostname=='127.0.0.1' and 'test' in parsed.path
            self.schema='pedido_agenda_'+uuid4().hex
            self.admin=create_engine(url)
            with self.admin.begin() as c:c.execute(text(f'CREATE SCHEMA {self.schema}'))
            self.engine=create_engine(url,connect_args={'options':f'-csearch_path={self.schema}'})
        else:
            self.engine=create_engine('sqlite://')
        for model in (Configuracao,Clinica,Paciente,Tutor,Servico,Agendamento,Resposta,Pedido):model.__table__.create(self.engine)
        self.db=Session(self.engine)
        self.user=SimpleNamespace(id=1,nome='Ana',tem_papel=lambda p:p=='recepcao')
        self.db.add_all([Clinica(id=9,nome='Vet World',ativo=True,latitude=-3.7,longitude=-38.5),
            Tutor(id=1,nome='Maria',ativo=1),Paciente(id=1,nome='Rex',tutor_id=1,ativo=1),
            Servico(id=1,nome='Ecocardiograma',ativo=True,duracao_minutos=30)])
        state={'clinica_id':9,'status':'encaminhada','dados':{'paciente':'Rex','tutor':'Maria','exame':'ecocardiograma','preferencia':'amanhã'}}
        r=Resposta(job_id=1,wa_identity='phone',conversation_id='1',clinica_id=9,decisao='sent',tools_usadas=json.dumps({'solicitacao_agendamento':state}))
        self.db.add(r);self.db.commit();registrar(self.db,r,state);self.db.flush()
        self.pedido=self.db.query(Pedido).one();self.pedido.responsavel_id=1;self.pedido.status='em_atendimento';self.db.commit()
        self.start=(datetime.now()+timedelta(days=7)).replace(hour=10,minute=0,second=0,microsecond=0)
        self.body=dict(pedido_whatsapp_id=self.pedido.id,pedido_whatsapp_versao=1,clinica_id=9,paciente_id=1,tutor_id=1,servico_id=1,inicio=self.start,status='Agendado')
        self.stack=ExitStack()
        for name in ('_validar_agendamento_no_funcionamento','_validar_deslocamento_agendamento','registrar_auditoria','_notificar_agenda_update'):
            self.stack.enter_context(patch.object(agenda,name,return_value=None))

    def tearDown(self):
        self.stack.close();self.db.close();self.engine.dispose()
        if self.admin:
            with self.admin.begin() as c:c.execute(text(f'DROP SCHEMA {self.schema} CASCADE'))
            self.admin.dispose()

    def create(self,**changes):
        return agenda.criar_agendamento(AgendamentoCreate(**{**self.body,**changes}),Request({'type':'http'}),self.db,self.user)

    def test_save_and_replay_are_one_atomic_link(self):
        result=self.create()
        self.db.refresh(self.pedido)
        self.assertEqual(self.pedido.agendamento_id,result['id']);self.assertEqual(self.pedido.status,'agendado')
        self.assertEqual(self.pedido.versao,2)
        again=self.create()
        self.assertEqual(again['id'],result['id']);self.assertEqual(self.db.query(Agendamento).count(),1)
        with self.assertRaises(HTTPException) as exc:self.create(inicio=self.start+timedelta(hours=1))
        self.assertEqual(exc.exception.status_code,409)

    def test_concurrent_replay_postgres(self):
        if self.engine.dialect.name!='postgresql':self.skipTest('Concorrencia requer PostgreSQL local')
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.db.rollback()
        barrier=Barrier(2)
        def create(_):
            with Session(self.engine) as db:
                barrier.wait(timeout=10)
                return agenda.criar_agendamento(AgendamentoCreate(**self.body),Request({'type':'http'}),db,self.user)['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(create,[1,2]))
        self.assertEqual(ids[0],ids[1]);self.assertEqual(self.db.query(Agendamento).count(),1)
        self.assertEqual(self.db.query(Pedido).one().versao,2)

    def test_owner_version_and_role_are_enforced(self):
        for changes in ({'pedido_whatsapp_versao':99},{'clinica_id':10},{'status':'Reservado'},{'tutor_id':2}):
            with self.assertRaises(HTTPException):self.create(**changes)
        self.user=SimpleNamespace(id=2,nome='Bia',tem_papel=lambda p:p=='recepcao')
        with self.assertRaises(HTTPException):self.create()
        self.user=SimpleNamespace(id=1,nome='Ana',tem_papel=lambda p:False)
        with self.assertRaises(HTTPException):self.create()
        self.assertEqual(self.db.query(Agendamento).count(),0)

    def test_real_slot_conflict_keeps_request_open(self):
        self.db.add(Agendamento(clinica_id=9,paciente_id=1,tutor_id=1,servico_id=1,inicio=agenda._coerce_datetime(self.start),fim=agenda._coerce_datetime(self.start+timedelta(minutes=30)),status='Agendado'))
        self.db.commit()
        with self.assertRaises(HTTPException):self.create()
        self.db.rollback();self.db.refresh(self.pedido)
        self.assertIsNone(self.pedido.agendamento_id);self.assertEqual(self.pedido.status,'em_atendimento')
        self.assertEqual(self.db.query(Agendamento).count(),1)

    def test_commit_failure_rolls_back_both(self):
        def fail(db):db.rollback();raise HTTPException(500,'falha simulada')
        with patch.object(agenda,'_commit_agenda_write',side_effect=fail),self.assertRaises(HTTPException):self.create()
        self.db.refresh(self.pedido)
        self.assertIsNone(self.pedido.agendamento_id);self.assertEqual(self.pedido.versao,1)
        self.assertEqual(self.db.query(Agendamento).count(),0)

    def test_different_pet_requires_explicit_confirmation_and_is_audited(self):
        self.db.add(Paciente(id=2,nome='Galhofa',tutor_id=1,ativo=1));self.db.commit()
        self.body['paciente_id'] = 2
        with self.assertRaises(HTTPException) as exc:
            self.create()
        self.assertEqual(exc.exception.status_code, 422)
        self.assertEqual(self.db.query(Agendamento).count(), 0)
        self.body['pedido_whatsapp_divergencia_confirmada'] = True
        self.create()
        self.db.refresh(self.pedido)
        evento = json.loads(self.pedido.historico)[-1]
        self.assertEqual(evento['divergencias_confirmadas']['paciente'], {'informado':'Rex', 'selecionado':'Galhofa'})

    def test_prefill_unique_active_pair_and_service_only(self):
        ctx={'resolution':'matched','match_type':'clinica','clinicas':[{'id':9}],'pets':[{'id':1}]}
        with patch('app.services.whatsapp_bot_generation._resolver_contexto',return_value=ctx):
            result=preparar(self.db,self.pedido.id,self.user)
            self.assertEqual(result['paciente']['id'],1);self.assertEqual(result['tutor']['id'],1);self.assertEqual(result['servico_id'],1)
            self.assertNotIn('inicio',result)
            self.assertEqual(result['dados_coletados'], {'paciente':'Rex', 'tutor':'Maria',
                'preferencia_horario':'amanhã', 'preferencia_agenda':None})
            self.db.add(Paciente(id=2,nome='Rex',tutor_id=1,ativo=1));self.db.commit();ctx['pets'].append({'id':2})
            self.assertIsNone(preparar(self.db,self.pedido.id,self.user)['paciente'])
        with patch('app.services.whatsapp_bot_generation._resolver_contexto',return_value={'resolution':'ambiguous'}):
            self.assertIsNone(preparar(self.db,self.pedido.id,self.user)['paciente'])

    def test_prefill_carries_safe_week_preference_anchored_to_original_message(self):
        response = self.db.get(Resposta, self.pedido.resposta_id)
        audit = json.loads(response.tools_usadas)
        state = audit['solicitacao_agendamento']
        state['dados']['preferencia'] = 'na próxima semana à tarde'
        state['preferencia_recebida_em'] = '2026-10-05T01:00:00Z'
        response.tools_usadas = json.dumps(audit)
        self.db.commit()
        with patch('app.services.whatsapp_bot_generation._resolver_contexto', return_value={'resolution': 'ambiguous'}):
            result = preparar(self.db, self.pedido.id, self.user)
        self.assertEqual(result['dados_coletados']['preferencia_agenda'],
            {'data_inicio': '2026-10-05', 'data_fim': '2026-10-11', 'turno': 'tarde'})
        self.assertNotIn('inicio', result)
        self.assertEqual(self.db.query(Agendamento).count(), 0)

    def test_prefill_does_not_guess_unknown_corrected_or_other_conversation_preference(self):
        response = self.db.get(Resposta, self.pedido.resposta_id)
        audit = json.loads(response.tools_usadas)
        state = audit['solicitacao_agendamento']
        state['preferencia_recebida_em'] = '2026-10-04T10:00:00-03:00'
        with patch('app.services.whatsapp_bot_generation._resolver_contexto', return_value={'resolution': 'ambiguous'}):
            for text in ('depois do almoço, menos terça', 'na próxima semana pela manhã'):
                state['dados']['preferencia'] = text
                response.tools_usadas = json.dumps(audit)
                if text.startswith('na próxima'):
                    self.pedido.historico = json.dumps([{'acao': 'complemento_cliente', 'observacao': 'Só na sexta'}])
                self.db.commit()
                result = preparar(self.db, self.pedido.id, self.user)
                self.assertIsNone(result['dados_coletados']['preferencia_agenda'])
                self.assertTrue(any('preferência' in aviso for aviso in result['avisos']))
            response.conversation_id = 'outra'
            self.db.commit()
            result = preparar(self.db, self.pedido.id, self.user)
        self.assertIsNone(result['dados_coletados']['preferencia_horario'])
        self.assertIsNone(result['servico_id'])

    def test_migration_preserves_legacy_rows(self):
        self.db.rollback()
        with self.engine.begin() as c:
            # Schema legado minimo, sem coluna nova.
            c.execute(text('DROP TABLE whatsapp_bot_solicitacoes'))
            importlib.import_module('migrations.versions.20260909_81_whatsapp_bot_solicitacoes').upgrade(c,self.engine.dialect.name)
            before=c.execute(text('SELECT count(*) FROM whatsapp_bot_solicitacoes')).scalar()
            m=importlib.import_module('migrations.versions.20260909_82_whatsapp_pedido_agendamento')
            m.upgrade(c,self.engine.dialect.name);m.upgrade(c,self.engine.dialect.name)
            self.assertEqual(c.execute(text('SELECT count(*) FROM whatsapp_bot_solicitacoes')).scalar(),before)
            self.assertEqual(c.execute(text('SELECT count(*) FROM whatsapp_bot_solicitacoes WHERE agendamento_id IS NOT NULL')).scalar(),0)
