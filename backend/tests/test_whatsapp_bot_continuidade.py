import os
os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('SECRET_KEY', 'continuity-local-test-key-1234567890')
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, Mock
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.models.whatsapp_bot import WhatsAppBotSolicitacao as Pedido, WhatsAppBotResposta, WhatsAppBotConversaEstado
from app.services.whatsapp_bot_atendimento import assumir
from app.services.whatsapp_bot_continuidade import resposta_pedido, registrar_complemento, agrupar_fragmentos, novo_pedido, KEY


class ContinuidadeTests(unittest.TestCase):
    def setUp(self):
        self.admin = None
        url = os.environ.get('WHATSAPP_BOT_TEST_DATABASE_URL')
        if url:
            from uuid import uuid4
            from urllib.parse import urlparse
            parsed = urlparse(url)
            assert parsed.hostname == '127.0.0.1' and 'test' in parsed.path
            self.schema = 'continuidade_' + uuid4().hex
            self.admin = create_engine(url)
            with self.admin.begin() as conn: conn.execute(text(f'CREATE SCHEMA {self.schema}'))
            self.engine = create_engine(url, connect_args={'options':f'-csearch_path={self.schema}'})
        else:
            self.engine=create_engine('sqlite://')
        for model in (Pedido, WhatsAppBotResposta, WhatsAppBotConversaEstado):model.__table__.create(self.engine)
        self.db=Session(self.engine)
        now=datetime.now(timezone.utc)
        self.p=Pedido(id=1,resposta_id=1,wa_identity='558588018899',conversation_id='49',clinica_id=9,resumo='Rex, Maria',status='aguardando_equipe',prazo_em=now,created_at=now,updated_at=now,versao=1,historico='[]')
        self.db.add(self.p);self.db.commit()
        self.user=SimpleNamespace(id=2,nome='Ana',email='ana@example.test')

    def tearDown(self):
        self.db.close();self.engine.dispose()
        if self.admin:
            with self.admin.begin() as conn: conn.execute(text(f'DROP SCHEMA {self.schema} CASCADE'))
            self.admin.dispose()

    def test_concurrent_claim_has_one_owner_in_postgres(self):
        if not self.admin: self.skipTest('PostgreSQL local de testes não configurado')
        from threading import Barrier
        from concurrent.futures import ThreadPoolExecutor
        barrier = Barrier(2)
        def remote(method, path, **kwargs):
            if path == '/agents': return {'data':[{'id':u,'email':f'a{u}@example.test','active':True} for u in (2,3)]}
            if path == '/conversations': return {'data':[{'id':'49','wa_phone_number':'558588018899'}]}
            return {}
        def claim(uid):
            with Session(self.engine) as db:
                barrier.wait(timeout=10)
                try:
                    assumir(db, '49', '558588018899', SimpleNamespace(id=uid,nome=f'A{uid}',email=f'a{uid}@example.test'))
                    return 200
                except HTTPException as exc: return exc.status_code
        with patch('app.services.whatsapp_bot_atendimento.node', side_effect=remote) as calls:
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(claim,[2,3])), [200,409])
            self.assertEqual(sum(c.args[0]=='POST' for c in calls.call_args_list),1)
        self.db.refresh(self.p)
        self.assertEqual(len(json.loads(self.p.historico)),1)


    def test_concurrent_complements_preserve_both_histories(self):
        if not self.admin: self.skipTest('PostgreSQL local de testes não configurado')
        from threading import Barrier
        from concurrent.futures import ThreadPoolExecutor
        barrier = Barrier(2)
        def add(job_id):
            with Session(self.engine) as db:
                db.get(Pedido, 1)  # snapshot carregado antes da disputa
                barrier.wait(timeout=10)
                resposta = SimpleNamespace(tools_usadas=json.dumps({KEY:{'pedido_id':1,'complemento':f'Atualização {job_id}'}}),
                    wa_identity='558588018899',conversation_id='49',clinica_id=9,job_id=job_id)
                registrar_complemento(db, resposta);db.commit()
        with patch('app.services.alerta_interno_service.criar_alerta_interno'):
            with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(add,[3,4]))
        self.db.refresh(self.p)
        self.assertEqual({e['job_id'] for e in json.loads(self.p.historico)}, {3,4})
        self.assertEqual(self.p.versao,3)

    def node(self,method,path,**kwargs):
        if path=='/agents':return {'data':[{'id':'7','email':self.user.email,'active':True}]}
        if path=='/conversations':return {'data':[{'id':'49','wa_phone_number':self.p.wa_identity}]}
        self.assertEqual(kwargs['json'], {'agent_id':7,'only_if_unassigned':True})
        return {'message':'claimed'}

    def test_claim_both_and_idempotent_retry(self):
        with patch('app.services.whatsapp_bot_atendimento.node',side_effect=self.node):
            result=assumir(self.db,'49',self.p.wa_identity,self.user,1,1)
            self.assertEqual(result['pedidos'],[1]);self.assertEqual(self.p.responsavel_id,2)
            self.assertEqual(self.p.status,'em_atendimento')
            self.assertIsNotNone(self.db.get(WhatsAppBotConversaEstado,self.p.wa_identity).pausado_ate)
            assumir(self.db,'49',self.p.wa_identity,self.user,1,1)
            self.assertEqual(len(json.loads(self.p.historico)),1)

    def test_does_not_take_another_owners_request(self):
        self.p.responsavel_id=99;self.db.commit()
        with patch('app.services.whatsapp_bot_atendimento.node',side_effect=self.node) as remote:
            with self.assertRaises(HTTPException) as exc:assumir(self.db,'49',self.p.wa_identity,self.user)
            self.assertEqual(exc.exception.status_code,409)
            self.assertFalse(any(c.args[0]=='POST' for c in remote.call_args_list))

    def test_remote_conflict_never_assigns_local_request(self):
        def fail(method,path,**kwargs):
            if method=='POST':raise HTTPException(409,'Outro atendente')
            return self.node(method,path,**kwargs)
        with patch('app.services.whatsapp_bot_atendimento.node',side_effect=fail):
            with self.assertRaises(HTTPException):assumir(self.db,'49',self.p.wa_identity,self.user)
        self.assertIsNone(self.p.responsavel_id)

    def test_local_failure_can_be_reconciled_without_release(self):
        with patch('app.services.whatsapp_bot_atendimento.node',side_effect=self.node):
            with patch.object(self.db,'commit',side_effect=RuntimeError('local failure')):
                with self.assertRaises(HTTPException) as exc:assumir(self.db,'49',self.p.wa_identity,self.user)
                self.assertEqual(exc.exception.status_code,503)
            assumir(self.db,'49',self.p.wa_identity,self.user)
            self.assertEqual(self.p.responsavel_id,2)

    def test_status_and_correction_do_not_modify_appointment(self):
        text,meta=resposta_pedido(self.db,self.p,'Como está meu agendamento?',None)
        self.assertIn('nenhum horário está reservado',text)
        self.assertEqual(meta,{'pedido_id':1})
        text,meta=resposta_pedido(self.db,self.p,'Na verdade o tutor é Ricardo',None)
        r=SimpleNamespace(tools_usadas=json.dumps({KEY:meta}),wa_identity=self.p.wa_identity,conversation_id='49',clinica_id=9,job_id=3)
        with patch('app.services.alerta_interno_service.criar_alerta_interno') as alert:
            registrar_complemento(self.db,r);registrar_complemento(self.db,r)
            self.assertEqual(alert.call_count,1)
        self.assertEqual(self.p.resumo,'Rex, Maria');self.assertEqual(self.p.status,'aguardando_equipe')
        self.assertEqual(len(json.loads(self.p.historico)),1)
        self.assertIsNone(resposta_pedido(self.db,self.p,'Na verdade é Ricardo',{'status':'coletando'}))
        self.assertTrue(novo_pedido('Quero agendar outro exame'))
        self.assertFalse(novo_pedido('Não quero outro agendamento'))

    def test_status_uses_current_appointment_and_hides_foreign_clinic(self):
        self.p.agendamento_id=7
        db=Mock()
        db.get.return_value=SimpleNamespace(clinica_id=9,status='Cancelado',inicio=datetime(2026,9,15,15,30,tzinfo=timezone.utc))
        message,_=resposta_pedido(db,self.p,'Qual o horário do meu agendamento?',None)
        self.assertIn('Cancelado',message)
        self.assertIn('15/09/2026 às 12:30',message)
        db.get.return_value.clinica_id=10
        message,_=resposta_pedido(db,self.p,'Qual o horário do meu agendamento?',None)
        self.assertNotIn('12:30',message)
        self.assertIn('conferido pela equipe',message)

    def test_groups_only_recent_contiguous_inbound_text(self):
        now=datetime.now(timezone.utc)
        def msg(text,seconds,own=False):return {'body':text,'from_me':own,'type':'text','created_at':(now-timedelta(seconds=seconds)).isoformat()}
        old=msg('outro paciente',20,True)
        history=[old,msg('Pet: Rex',10),msg('Tutor: Maria',5)]
        text,remaining=agrupar_fragmentos(history,msg('amanhã cedo',0))
        self.assertEqual(text,'Pet: Rex\nTutor: Maria\namanhã cedo');self.assertEqual(remaining,[old])
        self.assertEqual(agrupar_fragmentos([msg('Rex',121)],msg('Maria',0))[0],'Maria')
