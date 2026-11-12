import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "synthetic-auth-test-secret-1234567890")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from jose import JWTError, jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import auth
from app.core import security
from app.core.config import settings
from app.db.database import Base, get_db
from app.models.papel import Papel
from app.models.papel_permissao import PapelPermissao
from app.models.user import User
from app.services import supabase_auth
from scripts.import_supabase_auth_users import plan_import

IDENTITY_ID = "00000000-0000-4000-8000-000000000001"


class SupabaseAuthTest(unittest.TestCase):
    def setUp(self):
        self.config = patch.multiple(
            settings, AUTH_PROVIDER="supabase", SUPABASE_URL="https://synthetic.supabase.co",
            SUPABASE_PUBLISHABLE_KEY="sb_publishable_synthetic", SUPABASE_SECRET_KEY="sb_secret_synthetic",
        )
        self.config.start()
        self.addCleanup(self.config.stop)
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine, tables=[Base.metadata.tables[n] for n in ("usuarios", "papeis", "usuario_papel", "papeis_permissoes")])
        self.db = Session(engine)
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(id=1, email="staff@example.invalid", nome="Synthetic", ativo=1, senha_hash=auth.pwd_context.hash("synthetic-password"))
        self.db.add(self.user)
        self.db.commit()
        self.identity = {"id": IDENTITY_ID, "email": self.user.email, "email_confirmed_at": "2026-01-01T00:00:00Z", "app_metadata": {"fortcordis_user_id": 1}}
        self.token = jwt.encode({"sub": IDENTITY_ID, "exp": int(time.time()) + 3600}, "synthetic-key", algorithm="HS256")
        self.calls = []
        self.upstream = patch.object(supabase_auth.httpx, "request", side_effect=self.request)
        self.upstream.start()
        self.addCleanup(self.upstream.stop)
        app = FastAPI()
        self.app = app
        app.include_router(auth.router, prefix="/api/v1/auth")
        app.dependency_overrides[get_db] = lambda: self.db

        @app.get("/api/v1/agenda")
        def private_page(user=Depends(security.get_current_user)):
            return {"id": user.id}

        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if "/token?" in url:
            body = {"access_token": self.token, "refresh_token": "synthetic-refresh", "user": self.identity}
        elif "/admin/users" in url:
            body = {"users": [self.identity]} if method == "GET" else self.identity
        elif "/logout" in url:
            return httpx.Response(204)
        else:
            body = self.identity
        return httpx.Response(200, json=body)

    def login(self):
        return self.client.post("/api/v1/auth/login", data={"username": self.user.email, "password": "synthetic-password"})

    def test_login_uses_supabase_and_sets_private_cookies_without_exposing_refresh(self):
        response = self.login()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["provider"], "supabase")
        self.assertNotIn("refresh_token", response.json())
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(any("fortcordis_refresh=" in c and "HttpOnly" in c for c in cookies))
        self.assertTrue(any("fortcordis_session=" in c and "HttpOnly" in c for c in cookies))
        self.assertIn("grant_type=password", self.calls[0][1])
        self.assertEqual(self.calls[0][2]["headers"]["apikey"], "sb_publishable_synthetic")

    def test_wrong_password_has_no_legacy_fallback(self):
        with patch.object(supabase_auth, "password_session", side_effect=JWTError("invalid")), patch.object(auth, "verify_password") as legacy:
            self.assertEqual(self.login().status_code, 401)
            legacy.assert_not_called()

    def test_no_email_only_or_user_metadata_binding(self):
        for metadata in ({}, {"fortcordis_user_id": "1"}, {"fortcordis_user_id": True}, {"fortcordis_user_id": 2}):
            self.identity["app_metadata"] = metadata
            self.identity["user_metadata"] = {"fortcordis_user_id": 1, "papeis": ["admin"]}
            self.assertEqual(self.login().status_code, 401)

    def test_unconfirmed_anonymous_and_email_mismatch_are_rejected(self):
        for field, value in (("email_confirmed_at", None), ("is_anonymous", True), ("email", "other@example.invalid")):
            with self.subTest(field=field):
                old = self.identity.get(field)
                self.identity[field] = value
                self.assertEqual(self.login().status_code, 401)
                self.identity[field] = old

    def test_inactive_user_is_denied(self):
        self.user.ativo = 0
        self.db.commit()
        self.assertEqual(self.login().status_code, 403)

    def test_session_checks_supabase_and_local_permissions_remain_authoritative(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/agenda").status_code, 403)
        role = Papel(nome="secretaria")
        self.user.papeis.append(role)
        self.db.flush()
        self.db.add(PapelPermissao(papel_id=role.id, modulo="agenda", visualizar=1, editar=0, excluir=0))
        self.db.commit()
        self.assertEqual(self.client.get("/api/v1/agenda").status_code, 200)

    def test_revoked_token_and_missing_cookie_are_rejected(self):
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
        self.login()
        with patch.object(supabase_auth.httpx, "request", return_value=httpx.Response(401)):
            self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_refresh_rotates_both_tokens_without_returning_refresh(self):
        self.client.cookies.set(settings.SUPABASE_REFRESH_COOKIE_NAME, "old-refresh")
        response = self.client.post("/api/v1/auth/refresh")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("refresh_token", response.json())
        self.assertIn("grant_type=refresh_token", self.calls[0][1])
        self.assertEqual(self.calls[0][2]["json"], {"refresh_token": "old-refresh"})

    def test_cookie_takes_precedence_over_stale_browser_bearer(self):
        self.login()
        self.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer stale"})
        self.assertEqual(self.calls[-1][2]["headers"]["Authorization"], f"Bearer {self.token}")

    def test_logout_revokes_session_and_clears_cookies(self):
        self.login()
        response = self.client.post("/api/v1/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("logout?scope=local" in call[1] for call in self.calls))
        self.assertNotIn(settings.AUTH_COOKIE_NAME, self.client.cookies)
        self.assertNotIn(settings.SUPABASE_REFRESH_COOKIE_NAME, self.client.cookies)

    def test_logout_with_only_refresh_cookie_revokes_server_session(self):
        self.client.cookies.set(settings.SUPABASE_REFRESH_COOKIE_NAME, "old-refresh")
        response = self.client.post("/api/v1/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.assertIn("grant_type=refresh_token", self.calls[0][1])
        self.assertIn("logout?scope=local", self.calls[1][1])

    def test_logout_failure_preserves_cookies_until_revocation_can_be_retried(self):
        self.login()
        with patch.object(supabase_auth.httpx, "request", side_effect=httpx.ConnectError("down")):
            response = self.client.post("/api/v1/auth/logout")
        self.assertEqual(response.status_code, 503)
        self.assertIn(settings.SUPABASE_REFRESH_COOKIE_NAME, self.client.cookies)

    def test_websocket_uses_the_same_verified_supabase_identity(self):
        from types import SimpleNamespace
        websocket = SimpleNamespace(headers={}, cookies={settings.AUTH_COOKIE_NAME: self.token})
        self.assertEqual(security.get_current_websocket_user(websocket, self.db).id, self.user.id)
        with patch.object(supabase_auth.httpx, "request", return_value=httpx.Response(401)):
            from fastapi import WebSocketException
            with self.assertRaises(WebSocketException):
                security.get_current_websocket_user(websocket, self.db)

    def test_auth_outage_fails_closed(self):
        with patch.object(supabase_auth.httpx, "request", side_effect=httpx.ConnectError("down")):
            self.assertEqual(self.login().status_code, 503)
        self.assertNotIn(settings.AUTH_COOKIE_NAME, self.client.cookies)

    def test_no_redirects_and_admin_key_never_used_for_login(self):
        self.login()
        self.assertFalse(self.calls[0][2]["follow_redirects"])
        self.assertNotIn("sb_secret_synthetic", str(self.calls))

    def test_import_is_idempotent_and_refuses_existing_email_without_binding(self):
        self.assertEqual(plan_import([self.user], [self.identity]), ([], 1))
        self.assertEqual(plan_import([self.user], [])[0], [self.user])
        self.identity["app_metadata"] = {}
        with self.assertRaises(ValueError):
            plan_import([self.user], [self.identity])

    def test_import_preserves_bcrypt_without_sending_email(self):
        supabase_auth.create_identity(self.user)
        body = self.calls[-1][2]["json"]
        self.assertEqual(body["password_hash"], self.user.senha_hash)
        self.assertTrue(body["email_confirm"])
        self.assertEqual(body["app_metadata"], {"fortcordis_user_id": 1})
        self.assertNotIn("password", body)

    def test_import_preflight_rejects_duplicate_emails_and_malformed_hashes(self):
        from types import SimpleNamespace
        duplicate = SimpleNamespace(id=2, email=self.user.email.upper(), senha_hash=self.user.senha_hash)
        with self.assertRaises(ValueError):
            plan_import([self.user, duplicate], [])
        self.user.senha_hash = "$2b$invalid"
        with self.assertRaises(ValueError):
            plan_import([self.user], [])

    def test_legacy_mode_remains_available_for_explicit_rollback(self):
        with patch.object(settings, "AUTH_PROVIDER", "legacy"):
            response = self.login()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["provider"], "legacy")
            self.assertEqual(self.calls, [])

    def test_admin_account_creation_and_credentials_updates_use_supabase(self):
        from app.api.v1.endpoints import admin
        self.app.include_router(admin.router, prefix="/api/v1/admin")
        self.login()
        payload = {"nome": "New staff", "email": "new@example.com", "senha": "synthetic-password", "papeis": []}
        self.assertEqual(self.client.post("/api/v1/admin/usuarios", json=payload).status_code, 403)
        self.user.papeis.append(Papel(nome="admin"))
        self.db.commit()
        with patch.object(supabase_auth, "create_identity", return_value={"id": IDENTITY_ID}) as create:
            response = self.client.post("/api/v1/admin/usuarios", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        created = create.call_args.args[0]
        self.assertGreater(created.id, 1)
        self.assertEqual(create.call_args.kwargs, {"password": "synthetic-password"})
        with patch.object(supabase_auth, "update_identity") as update:
            response = self.client.put(f"/api/v1/admin/usuarios/{created.id}", json={"email": "renamed@example.com", "senha": "updated-password"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(update.call_args.args[0].email, "renamed@example.com")
        self.assertEqual(update.call_args.kwargs, {"password": "updated-password"})


if __name__ == "__main__":
    unittest.main()
