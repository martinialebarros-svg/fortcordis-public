import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import WebSocketException, status
from jose import jwt

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "websocket-auth-test-secret-key-1234567890")

from app.core.config import settings
from app.core import security


class _FakeWebSocket:
    def __init__(self, *, authorization: str | None = None, cookie_token: str | None = None):
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}
        if authorization is not None:
            self.headers["Authorization"] = authorization
        if cookie_token is not None:
            self.cookies[settings.AUTH_COOKIE_NAME] = cookie_token


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    def __init__(self, user):
        self._user = user

    def query(self, model):
        model_name = getattr(model, "__name__", "")
        if model_name == "User":
            return _FakeQuery(self._user)
        return _FakeQuery(None)


class WebSocketAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.active_user = SimpleNamespace(
            id=1,
            email="veterinario@example.com",
            nome="Veterinario",
            ativo=1,
        )
        self.inactive_user = SimpleNamespace(
            id=2,
            email="inativo@example.com",
            nome="Inativo",
            ativo=0,
        )

    def _make_token(self, email: str) -> str:
        return jwt.encode({"sub": email}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    def test_extracts_token_from_bearer_header(self) -> None:
        token = self._make_token(self.active_user.email)
        ws = _FakeWebSocket(
            authorization=f"Bearer {token}",
            cookie_token="cookie-token-legacy",
        )

        self.assertEqual(security.get_websocket_token(ws), token)

    def test_falls_back_to_cookie_token(self) -> None:
        token = self._make_token(self.active_user.email)
        ws = _FakeWebSocket(cookie_token=token)

        self.assertEqual(security.get_websocket_token(ws), token)

    def test_rejects_missing_credentials(self) -> None:
        ws = _FakeWebSocket()
        db = _FakeDB(self.active_user)

        with self.assertRaises(WebSocketException) as ctx:
            security.get_current_websocket_user(ws, db)

        self.assertEqual(ctx.exception.code, status.WS_1008_POLICY_VIOLATION)
        self.assertEqual(ctx.exception.reason, "Credenciais invalidas")

    def test_rejects_invalid_token(self) -> None:
        ws = _FakeWebSocket(authorization="Bearer token-invalido")
        db = _FakeDB(self.active_user)

        with self.assertRaises(WebSocketException) as ctx:
            security.get_current_websocket_user(ws, db)

        self.assertEqual(ctx.exception.code, status.WS_1008_POLICY_VIOLATION)
        self.assertEqual(ctx.exception.reason, "Credenciais invalidas")

    def test_rejects_unknown_user(self) -> None:
        token = self._make_token(self.active_user.email)
        ws = _FakeWebSocket(authorization=f"Bearer {token}")
        db = _FakeDB(None)

        with self.assertRaises(WebSocketException) as ctx:
            security.get_current_websocket_user(ws, db)

        self.assertEqual(ctx.exception.code, status.WS_1008_POLICY_VIOLATION)
        self.assertEqual(ctx.exception.reason, "Credenciais invalidas")

    def test_rejects_inactive_user(self) -> None:
        token = self._make_token(self.inactive_user.email)
        ws = _FakeWebSocket(authorization=f"Bearer {token}")
        db = _FakeDB(self.inactive_user)

        with self.assertRaises(WebSocketException) as ctx:
            security.get_current_websocket_user(ws, db)

        self.assertEqual(ctx.exception.code, status.WS_1008_POLICY_VIOLATION)
        self.assertEqual(ctx.exception.reason, "Usuario inativo")

    def test_accepts_active_user(self) -> None:
        token = self._make_token(self.active_user.email)
        ws = _FakeWebSocket(authorization=f"Bearer {token}")
        db = _FakeDB(self.active_user)

        user = security.get_current_websocket_user(ws, db)

        self.assertIs(user, self.active_user)


if __name__ == "__main__":
    unittest.main()
