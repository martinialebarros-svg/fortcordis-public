"""Regressoes operacionais sem rede nem dados reais."""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from contextlib import ExitStack, contextmanager
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "bot-operacao-tests-12345678901234567890")
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotContextoSelecao, WhatsAppBotJob, WhatsAppBotResposta, WhatsAppBotConversaEstado, WhatsAppBotClinicaEstado, WhatsAppBotSolicitacao
from app.models.alerta_interno import AlertaInterno
from app.services import whatsapp_bot_worker_service as worker, whatsapp_bot_delivery_service as delivery, whatsapp_bot_handoff_service as handoff
from app.services.whatsapp_bot_generation import ResultadoGeracao
from app.services.whatsapp_bot_tools import WhatsAppBotToolContext, WhatsAppBotToolError, execute_bot_tool

@contextmanager
def build_context():
    engine = create_engine("sqlite://")
    for model in (WhatsAppBotContextoSelecao, Configuracao, WhatsAppBotJob, WhatsAppBotResposta, WhatsAppBotConversaEstado, WhatsAppBotClinicaEstado, WhatsAppBotSolicitacao, AlertaInterno):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db, ExitStack() as stack:
        db.add(Configuracao(whatsapp_bot_modo="auto", whatsapp_bot_atendimento_habilitado=True))
        job = WhatsAppBotJob(wa_identity="5585000000000", conversation_id="1", wa_message_id="wamid.test", status="processing", scheduled_for=datetime.now(timezone.utc))
        db.add(job)
        db.commit()
        for module in (worker, delivery):
            stack.enter_context(patch.object(module, "is_whatsapp_bot_enabled", return_value=True))
        stack.enter_context(patch.object(delivery.settings, "WHATSAPP_BOT_AUTO_SEND_ENABLED", True))
        stack.enter_context(patch.object(delivery.settings, "WHATSAPP_AGENDA_SERVICE_URL", "https://node.invalid"))
        stack.enter_context(patch.object(delivery.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "test-internal"))
        stack.enter_context(patch.object(handoff, "_mark_conversation_pending", return_value=True))
        stack.enter_context(patch.object(handoff, "send_whatsapp_message_push_notification"))
        stack.enter_context(patch.object(worker, "_fetch_historico", return_value=[]))
        conversation = dict(id="1", last_agent_id=None, last_inbound_at=datetime.now(timezone.utc).isoformat(), last_message_at=datetime.now(timezone.utc).isoformat(), last_message_body="qual o horario?", last_message_from_me=False, last_message_type="text", last_message_wa_message_id="wamid.test")
        stack.enter_context(patch.object(worker, "_fetch_conversation_by_phone", return_value=conversation))
        stack.enter_context(patch.object(delivery, "resposta_contexto_vigente", return_value=True))
        generated = ResultadoGeracao(decisao="draft", motivo="aprovado_auto", texto_gerado="Atendimento automatico: entre em contato com nossa equipe.", match_type="visitante", resolution="not_found", auto_elegivel=True)
        generate = stack.enter_context(patch.object(worker, "gerar_resposta", return_value=generated))
        yield db, job, conversation, generate
    engine.dispose()

def response(http_status=201, **payload):
    return Mock(status_code=http_status, json=Mock(return_value=payload or {"status": "sent"}))

class WhatsAppBotOperacaoTest(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.context = stack.enter_context(build_context())

    def test_timeout_encaminha_sem_reenvio(self):
        self._resultado_incerto(TimeoutError("timeout"))

    def test_202_encaminha_sem_reenvio(self):
        self._resultado_incerto(response(202, status="accepted_unconfirmed"))

    def test_502_encaminha_sem_reenvio(self):
        self._resultado_incerto(response(502))

    def test_pausa_durante_geracao_impede_post(self):
        self._controle_alterado("pausado_ate", datetime.now(timezone.utc) + timedelta(hours=1))

    def test_modo_off_durante_geracao_impede_post(self):
        self._controle_alterado("modo", "off")

    def test_auto_persiste_antes_do_envio_e_nao_duplica(self):
        context = self.context
        db, job, _, generate = context
        def post(*args, **kwargs):
            row = db.query(WhatsAppBotResposta).one()
            assert row.id and row.decisao == "sending"
            assert kwargs["json"]["metadata"]["idempotency_key"] == f"whatsapp-bot-resposta-{row.id}"
            assert kwargs["json"]["metadata"]["inbound_wa_message_id"] == job.wa_message_id
            return response()
        with patch.object(delivery.httpx, "post", side_effect=post) as send:
            worker._process_job(db, job)
            db.commit()
            worker._process_job(db, job)
        send.assert_called_once()
        generate.assert_called_once()
        row = db.query(WhatsAppBotResposta).one()
        assert row.decisao == "sent" and row.texto_enviado == row.texto_gerado
        assert row.feedback is None
        assert db.query(WhatsAppBotConversaEstado).first() is None

    def _resultado_incerto(self, result):
        context = self.context
        db, job, _, _ = context
        with patch.object(delivery.httpx, "post", side_effect=[result]) as send:
            worker._process_job(db, job)
            db.commit()
            worker._process_job(db, job)
        send.assert_called_once()
        db.flush()
        assert db.query(WhatsAppBotResposta).one().motivo == "envio_auto_incerto"
        assert db.query(AlertaInterno).count() == 1
        assert db.query(WhatsAppBotConversaEstado).one().pausado_ate is not None

    def test_nova_mensagem_durante_geracao_impede_envio(self):
        context = self.context
        db, job, _, _ = context
        with patch.object(delivery.httpx, "post", return_value=response(409, code="BOT_CONVERSATION_CHANGED")):
            worker._process_job(db, job)
        db.flush()
        assert db.query(WhatsAppBotResposta).one().motivo == "conversa_atualizada"

    def test_retomada_de_envio_interrompido_usa_mesma_resposta(self):
        context = self.context
        db, job, _, generate = context
        row = worker._record_resposta(db, job, decisao="sending", motivo="aprovado_auto", texto_gerado="Texto original", match_type="visitante")
        db.commit()
        with patch.object(delivery.httpx, "post", return_value=response()) as send:
            worker._process_job(db, job)
        generate.assert_not_called()
        assert send.call_args.kwargs["json"]["metadata"]["resposta_id"] == str(row.id)
        db.flush()
        assert db.query(WhatsAppBotResposta).count() == 1

    def test_interruptor_desligado_preserva_rascunho(self):
        context = self.context
        db, job, _, _ = context
        with patch.object(delivery.settings, "WHATSAPP_BOT_AUTO_SEND_ENABLED", False), patch.object(delivery.httpx, "post") as send:
            worker._process_job(db, job)
        send.assert_not_called()
        db.flush()
        assert db.query(WhatsAppBotResposta).one().decisao == "draft"

    def _controle_alterado(self, field, value):
        context = self.context
        db, job, _, generate = context
        original = generate.return_value
        def generating(*args, **kwargs):
            state = WhatsAppBotConversaEstado(wa_identity=job.wa_identity, modo=None)
            setattr(state, field, value)
            db.add(state)
            db.commit()
            return original
        generate.side_effect = generating
        with patch.object(delivery.httpx, "post") as send:
            worker._process_job(db, job)
        send.assert_not_called()
        db.flush()
        assert db.query(WhatsAppBotResposta).one().motivo == "auto_interrompido"

    def test_collection_notification_does_not_pause_without_attendant(self):
        db, job, _, _ = self.context
        handoff.trigger_active_handoff(db, wa_identity=job.wa_identity, conversation_id=job.conversation_id,
            motivo='solicitacao_agendamento', nivel='aviso', titulo='Pedido', mensagem_alerta='Conferir dados', pausar=False)
        db.flush()
        self.assertIsNone(db.query(WhatsAppBotConversaEstado).one().pausado_ate)
        self.assertEqual(db.query(AlertaInterno).count(),1)

    def test_emergency_in_previous_fragment_prevents_generation(self):
        db, job, conversation, generate = self.context
        now = datetime.now(timezone.utc)
        db.add(WhatsAppBotConversaEstado(wa_identity=job.wa_identity, pausado_ate=now+timedelta(hours=1)))
        db.commit()
        conversation['last_message_body'] = 'me ajude'
        conversation['last_message_at'] = now.isoformat()
        history = [{'body':'meu cachorro está sem respirar', 'from_me':False,'type':'text','created_at':(now-timedelta(seconds=5)).isoformat()}, {'body':'me ajude','from_me':False,'type':'text','created_at':now.isoformat()}]
        with patch.object(worker, '_fetch_historico', return_value=history):
            worker._process_job(db, job)
        generate.assert_not_called()
        db.flush()
        self.assertEqual(db.query(WhatsAppBotResposta).one().motivo,'emergencia')

    def test_pedido_assumido_durante_geracao_impede_envio(self):
        db, job, _, generate = self.context
        original = generate.return_value
        def generating(*args, **kwargs):
            now = datetime.now(timezone.utc)
            db.add(WhatsAppBotSolicitacao(resposta_id=99, wa_identity=job.wa_identity,
                conversation_id=job.conversation_id, clinica_id=9, resumo='Pedido',
                status='em_atendimento', responsavel_id=3, prazo_em=now, created_at=now,
                updated_at=now, versao=1, historico='[]'))
            db.commit()
            return original
        generate.side_effect = generating
        with patch.object(delivery.httpx, "post") as send:
            worker._process_job(db, job)
        send.assert_not_called()
        self.assertEqual(db.query(WhatsAppBotResposta).one().motivo, 'auto_interrompido')

    def test_emergencia_alerta_mesmo_durante_pausa(self):
        context = self.context
        db, job, conversation, generate = context
        db.add(WhatsAppBotConversaEstado(wa_identity=job.wa_identity, modo=None, pausado_ate=datetime.now(timezone.utc) + timedelta(hours=2)))
        db.commit()
        conversation["last_message_body"] = "meu cachorro nao esta respirando"
        worker._process_job(db, job)
        db.commit()
        generate.assert_not_called()
        assert db.query(AlertaInterno).one().nivel == "critico"
        db.flush()
        assert db.query(WhatsAppBotResposta).one().motivo == "emergencia"

    def test_mensagem_antiga_nao_gera_resposta_para_nova(self):
        context = self.context
        db, job, conversation, generate = context
        conversation["last_message_wa_message_id"] = "wamid.new"
        worker._process_job(db, job)
        generate.assert_not_called()
        db.flush()
        assert db.query(WhatsAppBotResposta).one().motivo == "conversa_atualizada"

    def test_mensagem_do_bot_nao_cria_pausa_humana(self):
        context = self.context
        db, job, conversation, generate = context
        conversation.update(last_message_from_me=True, last_message_origem="bot")
        worker._process_job(db, job)
        generate.assert_not_called()
        assert db.query(WhatsAppBotConversaEstado).first() is None

    def test_recupera_apenas_processamento_antigo(self):
        context = self.context
        db, job, _, _ = context
        worker._recover_interrupted_jobs(db)
        assert job.status == "processing"
        job.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        worker._recover_interrupted_jobs(db)
        assert job.status == "pending" and job.attempts == 1

    def test_visitante_nao_executa_ferramentas_de_dados(self):
        context = self.context
        db, *_ = context
        ctx = WhatsAppBotToolContext(db=db, match_type="visitante")
        for name in ("consultar_status_laudo", "consultar_preco_tabela", "buscar_clinica_parceira"):
            assert execute_bot_tool(ctx, name, {"tutor_id": 1, "clinica_id": 1})["ok"] is False
        with self.assertRaises(WhatsAppBotToolError):
            WhatsAppBotToolContext(db=db, match_type="visitante", tutor_id=1)


    def test_envio_auto_nao_conta_como_aprovacao_humana(self):
        context = self.context
        from app.services import whatsapp_bot_metrics_service as metrics
        db, job, _, _ = context
        row = worker._record_resposta(db, job, decisao="sent", motivo="enviado_auto")
        bucket = metrics._bucket_vazio()
        metrics._acumular(bucket, row)
        result = metrics._finalizar(bucket)
        assert result["enviados_auto"] == 1
        assert result["aceitos"] == 0
        assert result["rascunhos_oferecidos"] == 0
        assert result["taxa_aceite"] is None


    def test_bloqueio_prevalece_sobre_flag_de_elegibilidade(self):
        context = self.context
        db, job, _, generate = context
        generate.return_value.decisao = "blocked"
        with patch.object(delivery.httpx, "post") as send:
            worker._process_job(db, job)
        send.assert_not_called()
        db.flush()
        assert db.query(AlertaInterno).count() == 1

    def test_visitante_recebe_apenas_conhecimento_publico(self):
        from app.services import assistente_ia_management as management
        db, *_ = self.context
        ctx = WhatsAppBotToolContext(db=db, match_type="visitante")
        public = {"category": "institucional", "source": "Recepcao", "title": "Agendar", "excerpt": "Entre em contato com a recepcao para agendar.", "keyword_score": 5, "score": 0.35}
        private = {**public, "category": "institucional_clinica", "excerpt": "Orientacao exclusiva para clinicas"}
        with patch.object(management, "search_knowledge", return_value={"ok": True, "items": [private, public]}):
            result = execute_bot_tool(ctx, "buscar_conhecimento_institucional", {"consulta": "como agendar"})
        assert result["ok"]
        assert len(result["trechos"]) == 1
        assert result["trechos"][0]["trecho"] == public["excerpt"]
