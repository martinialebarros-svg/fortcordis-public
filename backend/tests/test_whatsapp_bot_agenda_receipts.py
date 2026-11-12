import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "receipt-test-secret-key-123456789012345")

from app.models.alerta_interno import AlertaInterno
from app.models.configuracao import Configuracao
from app.models.whatsapp_agenda_resposta import WhatsappAgendaResposta
from app.models.whatsapp_bot import (
    WhatsAppBotConversaEstado, WhatsAppBotContextoSelecao, WhatsAppBotJob,
    WhatsAppBotResposta, WhatsAppBotSolicitacao,
)
from app.services.whatsapp_bot_agenda_receipts import confirmacao_agenda_processada
from app.services import whatsapp_bot_queue_service as queue
from app.services import whatsapp_bot_worker_service as worker


class AgendaReceiptBotTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        for model in (WhatsappAgendaResposta, WhatsAppBotJob, WhatsAppBotResposta,
                      WhatsAppBotConversaEstado, WhatsAppBotContextoSelecao,
                      WhatsAppBotSolicitacao, Configuracao, AlertaInterno):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def receipt(self, *, message_id="wamid.receipt", action="confirmar_presenca",
                result="presenca_confirmada", status="Confirmado", phone="5585988018899"):
        receipt = WhatsappAgendaResposta(
            provider_message_id=message_id, agendamento_id=19, action=action,
            result=result, from_phone=phone, result_json=json.dumps({
                "action": action, "result": result, "status": status, "agendamento_id": 19,
            }),
        )
        self.db.add(receipt)
        self.db.commit()
        return receipt

    def recognized(self, **kwargs):
        return confirmacao_agenda_processada(
            self.db, wa_identity=kwargs.get("phone", "558588018899"),
            wa_message_id=kwargs.get("message_id", "wamid.receipt"),
            message_type=kwargs.get("message_type", "button"),
        )

    def test_apenas_recibos_positivos_confirmados_e_alias_do_mesmo_remetente(self):
        for i, (action, result, status) in enumerate((
            ("confirmar_presenca", "presenca_confirmada", "Agendado"),
            ("confirmar_presenca", "presenca_confirmada", "Confirmado"),
            ("confirmar", "confirmado", "Confirmado"),
            ("confirmar", "ja_confirmado", "Confirmado"),
        )):
            with self.subTest(action=action, result=result, status=status):
                message_id = f"wamid.receipt.{i}"
                self.receipt(message_id=message_id, action=action, result=result, status=status)
                self.assertTrue(self.recognized(message_id=message_id))

    def test_nao_silencia_sem_prova_ou_com_escopo_incompativel(self):
        receipt = self.receipt()
        for changes in ({"phone": "5585987654321"}, {"message_id": "unknown"},
                        {"message_type": "text"}, {"message_type": "interactive"}):
            with self.subTest(changes=changes):
                self.assertFalse(self.recognized(**changes))
        for payload in ("not json", "[]", json.dumps({"status": "Confirmado"}),
                        json.dumps({"action": "confirmar_presenca", "result": "presenca_confirmada",
                                    "agendamento_id": 19, "status": {}})):
            receipt.result_json = payload
            self.db.commit()
            self.assertFalse(self.recognized())

    def test_alteracao_ja_alertada_e_reconhecida_sem_confirmar_agenda(self):
        for i, status in enumerate(("Agendado", "Confirmado", "Reservado")):
            with self.subTest(status=status):
                message_id = f"wamid.alteracao.{i}"
                self.receipt(message_id=message_id, action="solicitar_alteracao",
                             result="alteracao_solicitada", status=status)
                self.assertTrue(self.recognized(message_id=message_id))

    def test_revisoes_e_outros_pedidos_nao_sao_respostas_tratadas(self):
        for i, (action, result, status) in enumerate((
            ("confirmar_presenca", "revisao_manual", "Cancelado"),
            ("confirmar", "confirmacao_apos_prazo", "Expirado"),
            ("confirmar", "confirmacao_dados_pendentes", "Reservado"),
            ("falar_equipe", "falar_equipe_solicitado", "Confirmado"),
            ("solicitar_alteracao", "agendamento_nao_encontrado", "Confirmado"),
        )):
            message_id = f"wamid.manual.{i}"
            self.receipt(message_id=message_id, action=action, result=result, status=status)
            self.assertFalse(self.recognized(message_id=message_id))

    def test_callback_confirmacao_nao_cria_job_nem_substitui_texto_pendente(self):
        self.assertTrue(queue.enqueue_job_for_inbound_message(
            self.db, wa_identity="558588018899", conversation_id="c1",
            wa_message_id="wamid.question", message_type="text",
        ))
        self.receipt()
        self.assertFalse(queue.enqueue_job_for_inbound_message(
            self.db, wa_identity="558588018899", conversation_id="c1",
            wa_message_id="wamid.receipt", message_type="button",
        ))
        jobs = self.db.query(WhatsAppBotJob).all()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, "pending")

    def test_callback_alteracao_nao_cria_handoff_nem_substitui_texto_pendente(self):
        self.assertTrue(queue.enqueue_job_for_inbound_message(
            self.db, wa_identity="558588018899", conversation_id="c1",
            wa_message_id="wamid.question", message_type="text",
        ))
        self.receipt(action="solicitar_alteracao", result="alteracao_solicitada", status="Agendado")
        self.assertFalse(queue.enqueue_job_for_inbound_message(
            self.db, wa_identity="558588018899", conversation_id="c1",
            wa_message_id="wamid.receipt", message_type="button",
        ))
        jobs = self.db.query(WhatsAppBotJob).all()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, "pending")

    def test_botao_desconhecido_continua_na_fila_para_revisao(self):
        self.assertTrue(queue.enqueue_job_for_inbound_message(
            self.db, wa_identity="558588018899", conversation_id="c1",
            wa_message_id="wamid.unknown", message_type="button",
        ))

    def job(self):
        job = WhatsAppBotJob(
            wa_identity="558588018899", conversation_id="c1", wa_message_id="wamid.receipt",
            status="processing", scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
        self.db.add(job)
        self.db.commit()
        return job

    def test_worker_legado_nao_pausa_nem_alerta_por_confirmacao_ja_processada(self):
        self.receipt()
        job = self.job()
        now = datetime.now(timezone.utc).isoformat()
        conversation = {
            "id": "c1", "last_message_at": now, "last_inbound_at": now,
            "last_message_from_me": False, "last_message_type": "button",
            "last_message_wa_message_id": "wamid.receipt", "last_message_body": "Confirmar presença",
        }
        with patch.object(worker, "is_whatsapp_bot_enabled", return_value=True), \
             patch.object(worker, "resolve_conversation_mode", return_value="auto"), \
             patch.object(worker, "_bot_internal_client_config", return_value=("http://synthetic", {}, 1)), \
             patch.object(worker, "_fetch_conversation_by_phone", return_value=conversation), \
             patch.object(worker, "_fetch_historico", return_value=[]), \
             patch.object(worker, "gerar_resposta") as generate, \
             patch.object(worker, "trigger_active_handoff") as handoff, \
             patch.object(worker, "deliver_automatic_reply") as send:
            self.assertEqual(worker._process_job(self.db, job), "done")
            self.assertEqual(worker._process_job(self.db, job), "done")
        generate.assert_not_called()
        handoff.assert_not_called()
        send.assert_not_called()
        self.assertEqual(self.db.query(WhatsAppBotConversaEstado).count(), 0)
        self.assertEqual(self.db.query(AlertaInterno).count(), 0)
        responses = self.db.query(WhatsAppBotResposta).all()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].motivo, "confirmacao_agenda_processada")

    def test_worker_legado_nao_pausa_por_ack_apos_alteracao_ja_alertada(self):
        self.receipt(action="solicitar_alteracao", result="alteracao_solicitada", status="Agendado")
        job = self.job()
        now = datetime.now(timezone.utc).isoformat()
        conversation = {
            "id": "c1", "last_message_at": now, "last_inbound_at": now,
            "last_message_from_me": True, "last_message_type": "text",
            "last_message_origem": "bot",
            "last_message_wa_message_id": "wamid.ack", "last_message_body": "Recebemos sua solicitação.",
        }
        with patch.object(worker, "is_whatsapp_bot_enabled", return_value=True), \
             patch.object(worker, "resolve_conversation_mode", return_value="auto"), \
             patch.object(worker, "_bot_internal_client_config", return_value=("http://synthetic", {}, 1)), \
             patch.object(worker, "_fetch_conversation_by_phone", return_value=conversation), \
             patch.object(worker, "_fetch_historico", return_value=[]), \
             patch.object(worker, "gerar_resposta") as generate, \
             patch.object(worker, "trigger_active_handoff") as handoff, \
             patch.object(worker, "pause_conversation") as pause:
            self.assertEqual(worker._process_job(self.db, job), "done")
        generate.assert_not_called()
        handoff.assert_not_called()
        pause.assert_not_called()
        self.assertEqual(self.db.query(WhatsAppBotResposta).one().motivo, "conversa_atualizada")

    def test_reconciliacao_nao_ressuscita_confirmacao_tratada(self):
        self.receipt()
        with patch.object(worker, "_bot_internal_client_config", return_value=("http://synthetic", {}, 1)), \
             patch.object(worker, "_fetch_recently_active_conversations", return_value=[{
                 "id": "c1", "wa_phone_number": "558588018899",
             }]), \
             patch.object(worker, "_fetch_last_message", return_value={
                 "type": "button", "from_me": False, "wa_message_id": "wamid.receipt",
                 "created_at": datetime.now(timezone.utc).isoformat(),
             }):
            self.assertEqual(worker.run_reconciliation_sweep(self.db), {"checked": 1, "enqueued": 0})
        self.assertEqual(self.db.query(WhatsAppBotJob).count(), 0)

    def test_reconciliacao_nao_ressuscita_alteracao_ja_alertada(self):
        self.receipt(action="solicitar_alteracao", result="alteracao_solicitada", status="Agendado")
        with patch.object(worker, "_bot_internal_client_config", return_value=("http://synthetic", {}, 1)), \
             patch.object(worker, "_fetch_recently_active_conversations", return_value=[{
                 "id": "c1", "wa_phone_number": "558588018899",
             }]), \
             patch.object(worker, "_fetch_last_message", return_value={
                 "type": "button", "from_me": False, "wa_message_id": "wamid.receipt",
                 "created_at": datetime.now(timezone.utc).isoformat(),
             }):
            self.assertEqual(worker.run_reconciliation_sweep(self.db), {"checked": 1, "enqueued": 0})
        self.assertEqual(self.db.query(WhatsAppBotJob).count(), 0)
