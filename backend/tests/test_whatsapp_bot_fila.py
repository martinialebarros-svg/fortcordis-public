import os
import sys
import json
import unittest
import importlib
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DATABASE_URL','sqlite://')
os.environ.setdefault('SECRET_KEY','bot-fila-local-validation-key-1234567890')
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.models.whatsapp_bot import WhatsAppBotResposta as Resposta, WhatsAppBotSolicitacao as Pedido
from app.services.whatsapp_bot_fila import registrar, listar, atualizar, ultimo
from app.api.v1.endpoints.whatsapp_bot import WhatsAppBotSolicitacaoUpdate as Update, router
from app.core.security import get_current_user
from app.db.database import get_db


class FilaTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
        from app.models.clinica import Clinica
        Clinica.__table__.create(self.engine)
        Resposta.__table__.create(self.engine)
        Pedido.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.user = SimpleNamespace(id=1,nome='Ana',email='ana@example.test',tem_papel=lambda p:p=='recepcao')
        self.state={'clinica_id':9,'status':'encaminhada','dados':{'paciente':'Rex','tutor':'Maria','exame':'eco','preferencia':'amanhã'}}
        self.response = Resposta(job_id=1,wa_identity='phone',conversation_id='1',clinica_id=9,decisao='sent',tools_usadas=json.dumps({'solicitacao_agendamento':self.state}))
        self.db.add(self.response);self.db.commit()

    def tearDown(self):
        self.db.close();self.engine.dispose()

    def pedido(self):
        registrar(self.db,self.response,self.state);self.db.commit()
        return self.db.query(Pedido).one()

    def test_only_sent_final_creates_one_durable_request(self):
        self.response.decisao='draft';registrar(self.db,self.response,self.state)
        self.assertEqual(self.db.query(Pedido).count(),0)
        self.response.decisao='sent'
        p=self.pedido();registrar(self.db,self.response,self.state);self.db.commit()
        self.assertEqual(self.db.query(Pedido).count(),1)
        self.assertEqual(p.status,'aguardando_equipe')
        self.assertIsNone(ultimo(self.db,'other',9));self.assertIsNone(ultimo(self.db,'phone',16))
        p.created_at=datetime.now(timezone.utc)-timedelta(days=10);self.db.commit()
        self.assertEqual(ultimo(self.db,'phone',9).id,p.id)

    def test_list_scoped_to_selected_conversation(self):
        self.pedido()
        self.assertEqual(listar(self.db, 1, 'abertas', False, 1, '1')['total'], 1)
        self.assertEqual(listar(self.db, 1, 'abertas', False, 1, 'other')['total'], 0)

    def test_claim_conflict_release_and_owner_only(self):
        p=self.pedido()
        a=atualizar(self.db,p.id,Update(acao='assumir',versao=1),self.user)
        self.assertTrue(a['minha']);self.assertEqual(a['status'],'em_atendimento')
        other=SimpleNamespace(id=2,nome='Bia')
        for req,code in [(Update(acao='assumir',versao=1),409),(Update(acao='assumir',versao=2),409),(Update(acao='atualizar',versao=2,status='agendado',observacao='Confirmado na agenda'),403)]:
            with self.assertRaises(HTTPException) as exc: atualizar(self.db,p.id,req,other)
            self.assertEqual(exc.exception.status_code,code)
        result=atualizar(self.db,p.id,Update(acao='liberar',versao=2),self.user)
        self.assertTrue(result['sem_responsavel'])
        self.assertEqual(len(result['historico']),3)

    def test_terminal_requires_result_and_preserves_history(self):
        p=self.pedido();atualizar(self.db,p.id,Update(acao='assumir',versao=1),self.user)
        with self.assertRaises(HTTPException): atualizar(self.db,p.id,Update(acao='atualizar',versao=2,status='agendado'),self.user)
        result=atualizar(self.db,p.id,Update(acao='atualizar',versao=2,status='cancelado',observacao='Solicitante desistiu'),self.user)
        self.assertFalse(result['atrasada']);self.assertEqual(result['historico'][-1]['usuario_nome'],'Ana')
        with self.assertRaises(HTTPException): atualizar(self.db,p.id,Update(acao='assumir',versao=3),self.user)
        self.assertEqual(listar(self.db,1,'abertas',False,1)['total'],0)
        self.assertEqual(listar(self.db,1,'cancelado',True,1)['total'],1)

    def test_deadline_filters_and_validation(self):
        p=self.pedido();p.prazo_em=datetime.now(timezone.utc)-timedelta(minutes=1);self.db.commit()
        self.assertTrue(listar(self.db,1,'atrasadas',False,1)['itens'][0]['atrasada'])
        atualizar(self.db,p.id,Update(acao='assumir',versao=1),self.user)
        for deadline in [datetime.now(),datetime.now(timezone.utc)-timedelta(seconds=5),datetime.now(timezone.utc)+timedelta(days=31)]:
            with self.assertRaises(HTTPException): atualizar(self.db,p.id,Update(acao='atualizar',versao=2,prazo_em=deadline),self.user)
        result=atualizar(self.db,p.id,Update(acao='atualizar',versao=2,status='aguardando_cliente',prazo_em=datetime.now(timezone.utc)+timedelta(days=1)),self.user)
        self.assertFalse(result['atrasada'])
        self.assertEqual(listar(self.db,2,'abertas',True,1)['total'],0)

    def test_api_permissions_and_contract(self):
        app=FastAPI();app.include_router(router,prefix='/bot')
        app.dependency_overrides[get_db]=lambda:self.db
        with TestClient(app) as client:
            self.assertIn(client.get('/bot/solicitacoes').status_code,(401,403))
            app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(tem_papel=lambda p:False)
            self.assertEqual(client.get('/bot/solicitacoes').status_code,403)
            app.dependency_overrides[get_current_user]=lambda:self.user
            self.assertEqual(client.get('/bot/solicitacoes?page=0').status_code,422)
            p=self.pedido()
            from app.models.whatsapp_bot import WhatsAppBotConversaEstado
            WhatsAppBotConversaEstado.__table__.create(self.engine, checkfirst=True)
            def remote(method,path,**kwargs):
                if path == '/agents': return {'data':[{'id':7,'active':True,'email':self.user.email}]}
                if path == '/conversations': return {'data':[{'id':'1','wa_phone_number':'phone'}]}
                return {}
            with patch('app.services.whatsapp_bot_atendimento.node', side_effect=remote):
                self.assertEqual(client.patch(f'/bot/solicitacoes/{p.id}',json={'acao':'assumir','versao':1}).status_code,200)
            self.assertEqual(client.get('/bot/solicitacoes?minhas=true').json()['total'],1)

    def test_migration_backfills_sent_only_and_is_idempotent(self):
        Pedido.__table__.drop(self.engine)
        migration=importlib.import_module('migrations.versions.20260909_81_whatsapp_bot_solicitacoes')
        with self.engine.begin() as conn:
            migration.upgrade(conn,'sqlite');migration.upgrade(conn,'sqlite')
            self.assertEqual(conn.execute(text('SELECT count(*) FROM whatsapp_bot_solicitacoes')).scalar(),1)
            self.assertIn('ix_whatsapp_bot_solicitacoes_prazo_em',[i['name'] for i in inspect(conn).get_indexes('whatsapp_bot_solicitacoes')])

    def test_bot_tracks_request_and_explicit_new_collection(self):
        from app.services.whatsapp_bot_generation import gerar_resposta
        from app.schemas.whatsapp_bot import WhatsAppBotReplyOutput
        from app.services.whatsapp_bot_providers import GeneratedReply
        p=self.pedido()
        provider=Mock();provider.generate.return_value=GeneratedReply(output=WhatsAppBotReplyOutput(intent='solicitar_agendamento',texto='ignorado'),model='fake')
        context={'resolution':'matched','match_type':'clinica','clinicas':[{'id':9,'nome':'Clinica teste'}]}
        with patch('app.services.whatsapp_bot_generation._resolver_contexto',return_value=context),patch('app.services.whatsapp_bot_generation.resolve_modo_efetivo',return_value=('auto',None)):
            result=gerar_resposta(self.db,wa_identity='phone',corpo_mensagem='Como está meu pedido?',modo='auto',provider=provider)
            self.assertTrue(result.auto_elegivel,result.motivo)
            self.assertIn('Aguardando equipe',result.texto_gerado)
            self.assertEqual(json.loads(result.tools_usadas)['continuidade_pedido']['pedido_id'],p.id)
            for status in ('em_atendimento', 'aguardando_cliente', 'agendado', 'cancelado'):
                p.status=status;self.db.commit()
                follow=gerar_resposta(self.db,wa_identity='phone',corpo_mensagem='Como está meu pedido?',modo='auto',provider=provider)
                self.assertTrue(follow.auto_elegivel,follow.motivo)
                self.assertEqual(json.loads(follow.tools_usadas)['continuidade_pedido']['pedido_id'],p.id)
            result=gerar_resposta(self.db,wa_identity='phone',corpo_mensagem='nova solicitação',modo='auto',provider=provider)
            state=json.loads(result.tools_usadas)['solicitacao_agendamento']
            self.assertEqual(state['status'],'coletando');self.assertEqual(state['fila_anterior_id'],p.id)
            self.assertEqual(self.db.query(Pedido).count(),1) # simulation never persists


class FilaPostgresTests(unittest.TestCase):
    def test_local_migration_concurrent_claim_and_delivery_retry(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from urllib.parse import urlparse
        from uuid import uuid4
        url=os.environ.get('WHATSAPP_BOT_TEST_DATABASE_URL')
        if not url:
            self.skipTest('Banco PostgreSQL local exclusivo de testes nao configurado')
        parsed=urlparse(url)
        self.assertEqual(parsed.hostname,'127.0.0.1');self.assertIn('test',parsed.path)
        schema='bot_fila_'+uuid4().hex
        admin=create_engine(url)
        with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
        try:
            Resposta.__table__.create(engine)
            migration=importlib.import_module('migrations.versions.20260909_81_whatsapp_bot_solicitacoes')
            with engine.begin() as c:
                migration.upgrade(c,'postgresql');migration.upgrade(c,'postgresql')
                importlib.import_module('migrations.versions.20260909_82_whatsapp_pedido_agendamento').upgrade(c,'postgresql')
            state={'clinica_id':9,'status':'encaminhada','dados':{'paciente':'Rex'}}
            with Session(engine) as db:
                r=Resposta(job_id=1,wa_identity='phone',conversation_id='1',clinica_id=9,decisao='sent')
                db.add(r);db.commit();rid=r.id
            barrier=Barrier(2)
            def retry(_):
                with Session(engine) as db:
                    r=db.get(Resposta,rid);barrier.wait(timeout=10)
                    registrar(db,r,state);db.commit()
            with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(retry,[1,2]))
            with Session(engine) as db:
                self.assertEqual(db.query(Pedido).count(),1)
                pid=db.query(Pedido).one().id
            barrier=Barrier(2)
            def claim(uid):
                with Session(engine) as db:
                    barrier.wait(timeout=10)
                    try:
                        atualizar(db,pid,Update(acao='assumir',versao=1),SimpleNamespace(id=uid,nome=f'Atendente {uid}'))
                        return 200
                    except HTTPException as exc:return exc.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sorted(pool.map(claim,[1,2])),[200,409])
            with Session(engine) as db:
                p=db.get(Pedido,pid)
                self.assertEqual(p.versao,2);self.assertEqual(len(json.loads(p.historico)),2)
                db.add(Resposta(job_id=2,wa_identity='phone2',conversation_id='2',clinica_id=9,decisao='sent',tools_usadas=json.dumps({'solicitacao_agendamento':state})))
                db.commit()
            with engine.begin() as c:
                migration.upgrade(c,'postgresql');migration.upgrade(c,'postgresql')
                importlib.import_module('migrations.versions.20260909_82_whatsapp_pedido_agendamento').upgrade(c,'postgresql')
                self.assertEqual(c.execute(text('SELECT count(*) FROM whatsapp_bot_solicitacoes')).scalar(),2)
        finally:
            engine.dispose()
            with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
