"""Fluxo integrado de ambiguidade/entrega com banco sintético e transporte mockado."""
import os
import sys
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "contexto-entrega-test-key-12345678901234567890")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.models  # registra FKs da base sintetica
from app.models.clinica import Clinica
from app.models.tutor import Tutor
from app.models.configuracao import Configuracao
from app.models.alerta_interno import AlertaInterno
from app.models.whatsapp_bot import (
    WhatsAppBotContextoSelecao, WhatsAppBotConversaEstado, WhatsAppBotJob, WhatsAppBotResposta,
)
from app.api.v1.endpoints import whatsapp_bot
from app.api.v1.endpoints.whatsapp_contexto import resolve_whatsapp_context
from app.services import whatsapp_bot_generation as generation
from app.services import whatsapp_bot_worker_service as worker
from app.services import whatsapp_bot_delivery_service as delivery
from app.services import whatsapp_bot_handoff_service as handoff

PHONE = '5585987654321'


class ContextoEntregaTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.addCleanup(self.db.close)
        self.clinic = Clinica(nome='Clínica privada do teste', telefone=PHONE, ativo=True)
        self.tutor = Tutor(nome='Tutor privado do teste', whatsapp=PHONE, ativo=1)
        self.db.add_all([self.clinic, self.tutor, Configuracao(
            whatsapp_bot_modo='auto', whatsapp_bot_atendimento_habilitado=True)])
        self.db.commit()
        self.job = WhatsAppBotJob(wa_identity=PHONE, conversation_id='test-1', wa_message_id='wamid.test',
            status='processing', scheduled_for=datetime.now(timezone.utc))
        self.db.add(self.job)
        self.db.commit()
        self.conversation = dict(id='test-1', last_agent_id=None,
            last_inbound_at=datetime.now(timezone.utc).isoformat(),
            last_message_at=datetime.now(timezone.utc).isoformat(), last_message_from_me=False,
            last_message_body='Como está meu pedido?', last_message_type='text', last_message_wa_message_id='wamid.test')
        for module in (worker, delivery):
            self.stack.enter_context(patch.object(module, 'is_whatsapp_bot_enabled', return_value=True))
        self.stack.enter_context(patch.object(delivery.settings, 'WHATSAPP_BOT_AUTO_SEND_ENABLED', True))
        self.stack.enter_context(patch.object(delivery.settings, 'WHATSAPP_AGENDA_SERVICE_URL', 'https://node.invalid'))
        self.stack.enter_context(patch.object(delivery.settings, 'WHATSAPP_AGENDA_INTERNAL_TOKEN', 'synthetic'))
        self.stack.enter_context(patch.object(worker, '_fetch_conversation_by_phone', return_value=self.conversation))
        self.stack.enter_context(patch.object(worker, '_fetch_historico', return_value=[]))
        self.stack.enter_context(patch.object(handoff, '_mark_conversation_pending', return_value=True))
        self.stack.enter_context(patch.object(handoff, 'send_whatsapp_message_push_notification'))
        self.provider = self.stack.enter_context(patch.object(generation, 'get_whatsapp_bot_reply_provider', side_effect=AssertionError('sem IA para ambiguidade')))
        self.send = self.stack.enter_context(patch.object(delivery.httpx, 'post', return_value=Mock(status_code=201, json=Mock(return_value={'status':'sent'}))))

    def run_job(self):
        worker._process_job(self.db, self.job)
        self.db.commit()
        return self.db.query(WhatsAppBotResposta).one()

    def test_ambiguidade_avisa_uma_vez_e_mantem_encaminhamento(self):
        row = self.run_job()
        self.assertEqual(row.decisao, 'handoff')
        self.assertEqual(row.motivo, 'identidade_ambigua')
        self.assertEqual(row.texto_enviado, generation.IDENTITY_HANDOFF_MESSAGE)
        self.assertNotIn(self.clinic.nome, row.texto_enviado)
        self.assertNotIn(self.tutor.nome, row.texto_enviado)
        self.assertEqual(len(row.contexto_chave), 64)
        self.assertTrue(self.db.query(WhatsAppBotConversaEstado).one().pausado_ate)
        self.assertEqual(self.db.query(AlertaInterno).count(), 1)
        self.run_job()
        self.send.assert_called_once()
        self.provider.assert_not_called()
        meta = self.send.call_args.kwargs['json']['metadata']
        self.assertEqual(meta['inbound_wa_message_id'], self.job.wa_message_id)
        self.assertEqual(meta['idempotency_key'], f'whatsapp-bot-resposta-{row.id}')
        payload = whatsapp_bot.get_conversa_estado(PHONE, db=self.db, current_user=SimpleNamespace(id=1))
        self.assertTrue(payload['ultima_recusa']['aviso_enviado'])

    def test_copiloto_nao_envia_aviso_sozinho(self):
        self.db.add(WhatsAppBotConversaEstado(wa_identity=PHONE, modo='suggest'))
        self.db.commit()
        row = self.run_job()
        self.send.assert_not_called()
        self.assertEqual(row.decisao, 'handoff')
        self.assertIsNone(row.texto_enviado)

    def test_kill_switch_envio_nao_e_contornado_pelo_aviso(self):
        with patch.object(delivery.settings, 'WHATSAPP_BOT_AUTO_SEND_ENABLED', False):
            row = self.run_job()
        self.send.assert_not_called()
        self.assertEqual(row.decisao, 'handoff')
        self.assertIsNone(row.texto_enviado)

    def test_janela_fechada_nao_envia_aviso(self):
        self.conversation['last_inbound_at'] = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        row = self.run_job()
        self.send.assert_not_called()
        self.assertEqual(row.motivo, 'janela_fechada')

    def test_atendente_atribuido_nao_recebe_interferencia(self):
        self.conversation['last_agent_id'] = 2
        row = self.run_job()
        self.send.assert_not_called()
        self.assertEqual(row.motivo, 'pausado')

    def test_pausa_explicitamente_respeitada(self):
        self.db.add(WhatsAppBotConversaEstado(wa_identity=PHONE, pausado_ate=datetime.now(timezone.utc)+timedelta(hours=1)))
        self.db.commit()
        row = self.run_job()
        self.send.assert_not_called()
        self.assertEqual(row.motivo, 'pausado')

    def test_aviso_com_resultado_incerto_nao_repete(self):
        self.send.side_effect = TimeoutError('synthetic')
        row = self.run_job()
        self.run_job()
        self.send.assert_called_once()
        self.assertEqual(row.motivo, 'envio_auto_incerto')
        self.assertEqual(self.db.query(AlertaInterno).count(), 1)
        self.assertIsNone(row.texto_enviado)

    def test_cliente_mudou_conversa_antes_envio_nao_avisa_nem_pausa(self):
        self.send.return_value = Mock(status_code=409, json=Mock(return_value={'code':'BOT_CONVERSATION_CHANGED'}))
        row = self.run_job()
        self.assertEqual(row.motivo, 'conversa_atualizada')
        self.assertIsNone(row.texto_enviado)
        self.assertEqual(self.db.query(WhatsAppBotConversaEstado).count(), 0)

    def test_selecao_durante_geracao_invalida_resposta(self):
        real_generate = generation.gerar_resposta
        def generate(*args, **kwargs):
            result = real_generate(*args, **kwargs)
            from app.services.whatsapp_contexto_selecao_service import canonical_context_identity
            self.db.add(WhatsAppBotContextoSelecao(wa_identity=canonical_context_identity(PHONE),
                match_type='clinica', cadastro_id=self.clinic.id, versao=1, atualizado_por_id=1))
            self.db.commit()
            return result
        with patch.object(worker, 'gerar_resposta', side_effect=generate), patch(
            'app.services.whatsapp_bot_continuidade.registrar_complemento'
        ) as complement:
            row = self.run_job()
        complement.assert_not_called()
        self.send.assert_not_called()
        self.assertEqual(row.motivo, 'contexto_alterado')
        self.assertIsNone(row.texto_enviado)

    def test_rascunho_legado_sem_escopo_nao_pode_ser_enviado(self):
        row = worker._record_resposta(self.db, self.job, decisao='draft', motivo='modo_suggest', texto_gerado='Texto antigo')
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            whatsapp_bot.enviar_rascunho(row.id, whatsapp_bot.WhatsAppBotRespostaEnviarRequest(), db=self.db, current_user=SimpleNamespace(id=1))
        self.assertEqual(error.exception.status_code,409)
        self.send.assert_not_called()
        self.assertEqual(row.motivo, 'contexto_alterado')

    def test_rascunho_com_vinculo_removido_nao_pode_ser_enviado(self):
        key = resolve_whatsapp_context(self.db, PHONE)['contexto_chave']
        row = worker._record_resposta(self.db,self.job,decisao='draft',motivo='modo_suggest',texto_gerado='Dados do cadastro',contexto_chave=key)
        self.db.commit()
        self.tutor.whatsapp = '5585999990000'
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            whatsapp_bot.enviar_rascunho(row.id,whatsapp_bot.WhatsAppBotRespostaEnviarRequest(),db=self.db,current_user=SimpleNamespace(id=1))
        self.assertEqual(error.exception.status_code,409)
        self.send.assert_not_called()

    def test_historico_anterior_a_selecao_nao_e_reutilizado(self):
        now = datetime.now(timezone.utc)
        history = [dict(body='cadastro antigo',created_at=(now-timedelta(seconds=1)).isoformat()),
            dict(body='sem data'),dict(body='novo contexto',created_at=(now+timedelta(seconds=1)).isoformat())]
        context = {'selecao':{'versao':1,'updated_at':now.isoformat()}}
        self.assertEqual(generation._historico_do_contexto(history,context),history[2:])
        self.assertEqual(generation._historico_do_contexto(history,{'selecao':{'versao':2}}),[])

    def test_fragmentos_antes_da_escolha_nao_entram_no_corpo(self):
        now = datetime.now(timezone.utc)
        old = dict(body='pet e tutor do outro cadastro', type='text', from_me=False,
            created_at=(now-timedelta(seconds=60)).isoformat())
        current = dict(body='Como está meu pedido?', type='text', from_me=False,created_at=now.isoformat())
        context = {'resolution':'matched','contexto_chave':'a'*64,
            'selecao':{'versao':1,'updated_at':(now-timedelta(seconds=30)).isoformat()}}
        with patch.object(generation,'_resolver_contexto',return_value=context), patch.object(
            generation,'_gerar_resposta_no_contexto',return_value=generation.ResultadoGeracao('draft','ok')
        ) as generate:
            result = generation.gerar_resposta(self.db,wa_identity=PHONE,
                corpo_mensagem=old['body']+'\n'+current['body'], modo='auto',
                mensagem_atual=current,historico_bruto=[old],historico=[])
        self.assertEqual(generate.call_args.kwargs['corpo_mensagem'],current['body'])
        self.assertEqual(result.contexto_chave,'a'*64)

    def test_mensagem_anterior_a_escolha_nao_reinterpreta_novo_cadastro(self):
        now = datetime.now(timezone.utc)
        context = {'contexto_chave':'a'*64,'selecao':{'versao':1,'updated_at':now.isoformat()}}
        with patch.object(generation,'_resolver_contexto',return_value=context), patch.object(
            generation,'_gerar_resposta_no_contexto'
        ) as generate:
            result = generation.gerar_resposta(self.db,wa_identity=PHONE,corpo_mensagem='meu pedido',
                modo='auto',mensagem_atual={'created_at':(now-timedelta(seconds=1)).isoformat()})
        generate.assert_not_called()
        self.assertEqual(result.motivo,'contexto_alterado')

    def test_rascunho_atual_revisado_e_enviado_uma_vez(self):
        from app.services.whatsapp_contexto_selecao_service import canonical_context_identity
        self.db.add(WhatsAppBotContextoSelecao(wa_identity=canonical_context_identity(PHONE),
            match_type='clinica',cadastro_id=self.clinic.id,versao=1,atualizado_por_id=1))
        self.db.commit()
        key = resolve_whatsapp_context(self.db,PHONE)['contexto_chave']
        row = worker._record_resposta(self.db,self.job,decisao='draft',motivo='modo_suggest',
            texto_gerado='Texto revisado',contexto_chave=key)
        self.db.commit()
        with patch.object(whatsapp_bot,'registrar_auditoria'):
            for _ in range(2):
                result = whatsapp_bot.enviar_rascunho(row.id,whatsapp_bot.WhatsAppBotRespostaEnviarRequest(),
                    db=self.db,current_user=SimpleNamespace(id=1))
        self.assertEqual(result['status'],'sent')
        self.assertTrue(result['idempotent'])
        self.send.assert_called_once()

    def test_pedido_humano_antigo_nao_reabre_handoff_apos_escolha(self):
        from app.services.whatsapp_contexto_selecao_service import canonical_context_identity
        now = datetime.now(timezone.utc)
        self.db.add(WhatsAppBotContextoSelecao(wa_identity=canonical_context_identity(PHONE),
            match_type='clinica',cadastro_id=self.clinic.id,versao=1,atualizado_por_id=1,
            updated_at=now-timedelta(seconds=30)))
        self.db.commit()
        old = dict(body='quero falar com uma pessoa',type='text',from_me=False,
            created_at=(now-timedelta(seconds=60)).isoformat())
        current = dict(body=self.conversation['last_message_body'],type='text',from_me=False,
            created_at=self.conversation['last_message_at'])
        with patch.object(worker,'_fetch_historico',return_value=[old,current]), patch.object(
            worker,'gerar_resposta',return_value=generation.ResultadoGeracao('suppressed','teste')
        ) as generate:
            row = self.run_job()
        self.assertEqual(row.motivo,'teste')
        self.assertEqual(generate.call_args.kwargs['corpo_mensagem'],current['body'])
        self.assertEqual(self.db.query(AlertaInterno).count(),0)
