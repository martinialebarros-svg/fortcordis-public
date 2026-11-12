import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-webhook-enqueue-test-secret-key-1234567890")

from app.api.v1.endpoints import whatsapp_agenda
from app.api.v1.endpoints.whatsapp_agenda import (
    WhatsAppInboundMessageNotificationRequest,
    notify_whatsapp_inbound_message,
)


class WhatsAppBotWebhookEnqueueTest(unittest.TestCase):
    """CA-004: falha ao enfileirar nunca pode alterar a resposta do push."""

    def _fake_push_result(self):
        return {"sent": 1, "failed": 0, "deactivated": 0}

    def test_enqueue_com_sucesso_marca_bot_job_enqueued_true(self) -> None:
        payload = WhatsAppInboundMessageNotificationRequest(
            conversation_id="conv-1",
            contact_label="Clinica Teste",
            body_preview="Ola",
            wa_phone_number="558588018899",
            wa_message_id="wamid.1",
            message_type="text",
        )

        with patch.object(
            whatsapp_agenda,
            "send_whatsapp_message_push_notification",
            return_value=self._fake_push_result(),
        ):
            with patch.object(whatsapp_agenda, "enqueue_job_for_inbound_message", return_value=True) as enqueue_mock:
                result = notify_whatsapp_inbound_message(payload, None, db=object())

        self.assertEqual(result["sent"], 1)
        self.assertTrue(result["bot_job_enqueued"])
        enqueue_mock.assert_called_once()

    def test_falha_no_enfileiramento_mantem_contagens_do_push_e_bot_job_enqueued_false(self) -> None:
        payload = WhatsAppInboundMessageNotificationRequest(
            conversation_id="conv-1",
            contact_label="Clinica Teste",
            body_preview="Ola",
            wa_phone_number="558588018899",
            wa_message_id="wamid.1",
            message_type="text",
        )

        with patch.object(
            whatsapp_agenda,
            "send_whatsapp_message_push_notification",
            return_value=self._fake_push_result(),
        ):
            with patch.object(
                whatsapp_agenda,
                "enqueue_job_for_inbound_message",
                side_effect=RuntimeError("banco fora do ar"),
            ):
                result = notify_whatsapp_inbound_message(payload, None, db=object())

        self.assertEqual(result, {"sent": 1, "failed": 0, "deactivated": 0, "bot_job_enqueued": False})

    def test_payload_sem_wa_message_id_nao_tenta_enfileirar(self) -> None:
        payload = WhatsAppInboundMessageNotificationRequest(
            conversation_id="conv-1",
            contact_label="Clinica Teste",
            body_preview="Ola",
        )

        with patch.object(
            whatsapp_agenda,
            "send_whatsapp_message_push_notification",
            return_value=self._fake_push_result(),
        ):
            with patch.object(whatsapp_agenda, "enqueue_job_for_inbound_message") as enqueue_mock:
                result = notify_whatsapp_inbound_message(payload, None, db=object())

        enqueue_mock.assert_not_called()
        self.assertFalse(result["bot_job_enqueued"])


if __name__ == "__main__":
    unittest.main()
