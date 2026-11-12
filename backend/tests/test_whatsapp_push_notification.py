import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-push-notification-test-secret-key-1234567890")

from app.services import push_notifications


class WhatsAppPushNotificationTest(unittest.TestCase):
    def test_mensagem_recebida_esta_no_catalogo_de_acoes(self) -> None:
        self.assertIn("mensagem_recebida", push_notifications.PUSH_ACTIONS_SET)
        self.assertIn("mensagem_recebida", push_notifications.WHATSAPP_PUSH_ACTIONS_ORDER)

    def test_build_title_usa_contato_quando_disponivel(self) -> None:
        self.assertEqual(
            push_notifications._build_whatsapp_message_title("Clinica Teste"),
            "Nova mensagem de Clinica Teste",
        )
        self.assertEqual(
            push_notifications._build_whatsapp_message_title(""),
            "Nova mensagem no WhatsApp",
        )

    def test_build_body_trunca_em_160_caracteres(self) -> None:
        texto_longo = "a" * 300
        resultado = push_notifications._build_whatsapp_message_body(texto_longo)
        self.assertEqual(len(resultado), 160)

    def test_build_body_usa_fallback_quando_vazio(self) -> None:
        self.assertEqual(
            push_notifications._build_whatsapp_message_body(""),
            "Abra a Central de Atendimento para ver a mensagem.",
        )

    def test_send_whatsapp_message_push_notification_monta_payload_correto(self) -> None:
        captured = {}

        def _fake_send_web_push_payload(_db, *, payload, **kwargs):
            captured["payload"] = payload
            captured["kwargs"] = kwargs
            return {"sent": 1, "failed": 0, "deactivated": 0}

        with patch.object(push_notifications, "send_web_push_payload", side_effect=_fake_send_web_push_payload):
            result = push_notifications.send_whatsapp_message_push_notification(
                object(),
                conversation_id="42",
                contact_label="Clinica Teste",
                body_preview="Ola, gostaria de confirmar o horario.",
            )

        self.assertEqual(result, {"sent": 1, "failed": 0, "deactivated": 0})
        payload = captured["payload"]
        self.assertEqual(payload["title"], "Nova mensagem de Clinica Teste")
        self.assertEqual(payload["body"], "Ola, gostaria de confirmar o horario.")
        self.assertEqual(payload["url"], "/whatsapp-stage")
        self.assertEqual(payload["data"]["module"], "whatsapp")
        self.assertEqual(payload["data"]["action"], "mensagem_recebida")
        self.assertEqual(payload["data"]["conversation_id"], "42")
        self.assertEqual(captured["kwargs"]["notification_action"], "mensagem_recebida")
        # Broadcast: nao deve excluir nenhum usuario especifico.
        self.assertNotIn("exclude_user_id", captured["kwargs"])


if __name__ == "__main__":
    unittest.main()
