import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-delivery-service-test-secret-key-1234567890")

from app.core.config import settings
from app.services.portal_delivery_service import (
    PortalChallengeDeliveryRequest,
    PortalDeliveryConfigurationError,
    send_portal_access_code,
)


class _FakeSMTP:
    last_instance = None

    def __init__(self, host, port, timeout=0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = None
        self.sent_messages = []
        type(self).last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ehlo(self):
        return None

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.sent_messages.append(message)


class PortalDeliveryServiceTest(unittest.TestCase):
    def _payload(self, *, channel: str, destination: str) -> PortalChallengeDeliveryRequest:
        return PortalChallengeDeliveryRequest(
            challenge_id="challenge-1234567890",
            actor_type="tutor",
            actor_id=101,
            channel=channel,
            destination=destination,
            code="123456",
            expires_in_minutes=15,
            display_name="Maria Tutora",
            paciente_nome="Luna",
        )

    def test_email_delivery_uses_smtp_provider(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_EMAIL_SMTP_HOST", "smtp.example.com"))
            stack.enter_context(patch.object(settings, "PORTAL_EMAIL_SMTP_PORT", 587))
            stack.enter_context(patch.object(settings, "PORTAL_EMAIL_SMTP_USERNAME", "portal"))
            stack.enter_context(patch.object(settings, "PORTAL_EMAIL_SMTP_PASSWORD", "secret"))
            stack.enter_context(patch.object(settings, "PORTAL_EMAIL_SMTP_USE_TLS", True))
            stack.enter_context(patch.object(settings, "PORTAL_EMAIL_SMTP_USE_SSL", False))
            stack.enter_context(patch.object(settings, "PORTAL_EMAIL_FROM_EMAIL", "portal@example.com"))
            stack.enter_context(patch.object(settings, "PORTAL_EMAIL_FROM_NAME", "Portal Fort Cordis"))
            stack.enter_context(patch("app.services.portal_delivery_service.smtplib.SMTP", _FakeSMTP))

            result = send_portal_access_code(
                self._payload(channel="email", destination="maria@example.com")
            )

        self.assertEqual(result.provider, "smtp")
        smtp = _FakeSMTP.last_instance
        self.assertIsNotNone(smtp)
        self.assertTrue(smtp.started_tls)
        self.assertEqual(smtp.logged_in, ("portal", "secret"))
        self.assertEqual(len(smtp.sent_messages), 1)
        message = smtp.sent_messages[0]
        self.assertEqual(message["To"], "maria@example.com")
        self.assertIn("123456", message.get_content())

    def test_whatsapp_delivery_posts_webhook_payload(self) -> None:
        captured = {}

        class _FakeResponse:
            def raise_for_status(self):
                return None

        def _fake_request(method, url, json=None, headers=None, timeout=None):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return _FakeResponse()

        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_WHATSAPP_ENABLED", True))
            stack.enter_context(patch.object(settings, "PORTAL_WHATSAPP_WEBHOOK_URL", "https://api.example.com/whatsapp"))
            stack.enter_context(patch.object(settings, "PORTAL_WHATSAPP_WEBHOOK_METHOD", "POST"))
            stack.enter_context(patch.object(settings, "PORTAL_WHATSAPP_WEBHOOK_AUTH_HEADER", "Authorization"))
            stack.enter_context(patch.object(settings, "PORTAL_WHATSAPP_WEBHOOK_AUTH_TOKEN", "token-123"))
            stack.enter_context(patch.object(settings, "PORTAL_WHATSAPP_WEBHOOK_TIMEOUT_SECONDS", 9))
            stack.enter_context(patch("app.services.portal_delivery_service.httpx.request", side_effect=_fake_request))

            result = send_portal_access_code(
                self._payload(channel="whatsapp", destination="85999990000")
            )

        self.assertEqual(result.provider, "whatsapp_webhook")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["url"], "https://api.example.com/whatsapp")
        self.assertEqual(captured["json"]["destination"], "85999990000")
        self.assertEqual(captured["json"]["code"], "123456")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer token-123")
        self.assertEqual(captured["timeout"], 9)

    def test_whatsapp_delivery_requires_feature_flag(self) -> None:
        with self.assertRaisesRegex(PortalDeliveryConfigurationError, "WhatsApp"):
            send_portal_access_code(
                self._payload(channel="whatsapp", destination="85999990000")
            )


if __name__ == "__main__":
    unittest.main()
