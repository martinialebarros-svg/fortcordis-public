import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from io import BytesIO

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from jose import JWTError, jwt
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-pdf-auth-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.core.config import settings
from app.core import security
from app.db.database import Base, get_db
from app.models.atendimento_clinico import AtendimentoClinico, PrescricaoClinica, PrescricaoItem
from app.models.paciente import Paciente
from app.models.papel import Papel
from app.models.papel_permissao import PapelPermissao
from app.models.user import User
from app.services import supabase_auth


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


def _make_request(
    *,
    authorization: str | None = None,
    query_string: str = "",
    cookie_token: str | None = None,
) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode("utf-8")))
    if cookie_token:
        cookie_header = f"{settings.AUTH_COOKIE_NAME}={cookie_token}"
        headers.append((b"cookie", cookie_header.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/atendimentos/1/prescricao/pdf",
        "raw_path": b"/api/v1/atendimentos/1/prescricao/pdf",
        "query_string": query_string.encode("utf-8"),
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


class AtendimentoPdfAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        provider = patch.object(settings, "AUTH_PROVIDER", "legacy")
        provider.start()
        self.addCleanup(provider.stop)
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
        return jwt.encode(
            {"sub": email},
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )

    def test_rejects_access_token_query_even_with_valid_bearer(self) -> None:
        token = self._make_token(self.active_user.email)
        request = _make_request(
            authorization=f"Bearer {token}",
            query_string="access_token=legacy-token",
        )
        db = _FakeDB(self.active_user)

        with patch.object(security, "_authorize_request_by_matrix") as authorize_mock:
            with self.assertRaises(HTTPException) as ctx:
                atendimento._autenticar_usuario_pdf(request, db)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Nao use access_token na URL", str(ctx.exception.detail))
        self.assertEqual(authorize_mock.call_count, 0)

    def test_requires_auth_credentials(self) -> None:
        request = _make_request()
        db = _FakeDB(self.active_user)

        with self.assertRaises(HTTPException) as ctx:
            atendimento._autenticar_usuario_pdf(request, db)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.headers.get("WWW-Authenticate"), "Bearer")

    def test_returns_user_for_valid_cookie(self) -> None:
        token = self._make_token(self.active_user.email)
        request = _make_request(cookie_token=token)
        db = _FakeDB(self.active_user)

        with patch.object(security, "_authorize_request_by_matrix") as authorize_mock:
            result = atendimento._autenticar_usuario_pdf(request, db)

        self.assertIs(result, self.active_user)
        self.assertEqual(authorize_mock.call_count, 1)

    def test_rejects_invalid_bearer(self) -> None:
        request = _make_request(authorization="Bearer token-invalido")
        db = _FakeDB(self.active_user)

        with self.assertRaises(HTTPException) as ctx:
            atendimento._autenticar_usuario_pdf(request, db)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.headers.get("WWW-Authenticate"), "Bearer")

    def test_returns_user_for_valid_bearer(self) -> None:
        token = self._make_token(self.active_user.email)
        request = _make_request(authorization=f"Bearer {token}")
        db = _FakeDB(self.active_user)

        with patch.object(security, "_authorize_request_by_matrix") as authorize_mock:
            result = atendimento._autenticar_usuario_pdf(request, db)

        self.assertIs(result, self.active_user)
        self.assertEqual(authorize_mock.call_count, 1)

    def test_rejects_inactive_user_with_403(self) -> None:
        token = self._make_token(self.inactive_user.email)
        request = _make_request(authorization=f"Bearer {token}")
        db = _FakeDB(self.inactive_user)

        with patch.object(security, "_authorize_request_by_matrix") as authorize_mock:
            with self.assertRaises(HTTPException) as ctx:
                atendimento._autenticar_usuario_pdf(request, db)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Usuario inativo", str(ctx.exception.detail))
        self.assertEqual(authorize_mock.call_count, 0)


class AtendimentoPdfSupabaseAuthTest(unittest.TestCase):
    paths = (
        "/api/v1/atendimentos/999/prescricao/pdf",
        "/api/v1/atendimentos/999/prescricoes/1/pdf",
        "/api/v1/atendimentos/999/exames/pdf",
        "/api/v1/atendimentos/999/documentos/1/pdf",
    )

    def setUp(self) -> None:
        provider = patch.object(settings, "AUTH_PROVIDER", "supabase")
        provider.start()
        self.addCleanup(provider.stop)
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in (
            "usuarios", "papeis", "usuario_papel", "papeis_permissoes", "pacientes",
            "atendimentos_clinicos", "prescricoes_clinicas", "prescricoes_itens",
        )])
        self.addCleanup(engine.dispose)
        self.db = Session(engine)
        self.addCleanup(self.db.close)
        role = Papel(nome="veterinario")
        self.user = User(id=1, email="vet@example.invalid", nome="Veterinario sintetico", ativo=1)
        self.user.papeis.append(role)
        self.db.add(self.user)
        self.db.flush()
        self.permission = PapelPermissao(
            papel_id=role.id, modulo="atendimento_clinico", visualizar=1, editar=0, excluir=0
        )
        self.db.add_all([
            self.permission,
            Paciente(id=1, nome="Paciente sintetica", especie="Canina", sexo="Femea"),
            AtendimentoClinico(id=1, paciente_id=1, veterinario_id=1, status="Concluido"),
            PrescricaoClinica(id=1, atendimento_id=1, sequencia=1),
            PrescricaoClinica(id=2, atendimento_id=1, sequencia=2),
            PrescricaoItem(id=1, prescricao_id=1, medicamento_nome="Medicamento sintetico A", dose="1 comprimido", frequencia="A cada 12 horas", via="Oral"),
            PrescricaoItem(id=2, prescricao_id=2, medicamento_nome="Medicamento sintetico B", dose="2 comprimidos", frequencia="A cada 24 horas", via="Oral"),
        ])
        self.db.commit()
        self.identity = {
            "id": "00000000-0000-4000-8000-000000000001",
            "email": self.user.email,
            "email_confirmed_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"fortcordis_user_id": self.user.id},
        }
        upstream = patch.object(supabase_auth, "request_auth", return_value=self.identity)
        self.upstream = upstream.start()
        self.addCleanup(upstream.stop)
        branding = patch.object(atendimento, "_obter_branding_pdf_documento", return_value={
            "nome_veterinario": "", "crmv": "", "logomarca_bytes": None,
            "assinatura_bytes": None, "texto_rodape": None,
        })
        branding.start()
        self.addCleanup(branding.stop)
        app = FastAPI()
        app.include_router(atendimento.router, prefix="/api/v1/atendimentos")
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.client.cookies.set(settings.AUTH_COOKIE_NAME, "synthetic-supabase-session")

    def test_current_cookie_authenticates_all_document_routes_despite_stale_bearer(self):
        for path in self.paths:
            with self.subTest(path=path):
                response = self.client.get(path, headers={"Authorization": "Bearer stale-legacy"})
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["detail"], "Atendimento nao encontrado.")
                self.upstream.assert_called_with("GET", "user", token="synthetic-supabase-session")

    def test_cookie_downloads_real_pdf_and_preserves_selected_prescription(self):
        for suffix, expected, excluded in (
            ("prescricao/pdf", "Medicamento sintetico A", "Medicamento sintetico B"),
            ("prescricoes/2/pdf", "Medicamento sintetico B", "Medicamento sintetico A"),
        ):
            with self.subTest(suffix=suffix):
                response = self.client.get(f"/api/v1/atendimentos/1/{suffix}")
                self.assertEqual(response.status_code, 200, response.text[:200])
                self.assertEqual(response.headers["content-type"], "application/pdf")
                self.assertEqual(response.headers["cache-control"], "no-store, no-cache, must-revalidate, max-age=0")
                self.assertTrue(response.content.startswith(b"%PDF-"))
                text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(response.content)).pages)
                self.assertIn("Paciente sintetica", text)
                self.assertIn(expected, text)
                self.assertNotIn(excluded, text)
        self.assertEqual(self.db.get(AtendimentoClinico, 1).status, "Concluido")
        self.assertIsNotNone(self.db.get(PrescricaoClinica, 1).emitida_em)
        self.assertIsNotNone(self.db.get(PrescricaoClinica, 2).emitida_em)

    def test_supabase_bearer_works_without_cookie(self):
        self.client.cookies.clear()
        response = self.client.get(self.paths[0], headers={"Authorization": "Bearer synthetic-supabase-bearer"})
        self.assertEqual(response.status_code, 404, response.text)
        self.upstream.assert_called_once_with("GET", "user", token="synthetic-supabase-bearer")

    def test_missing_or_revoked_session_is_rejected_on_all_routes(self):
        for revoked in (False, True):
            if revoked:
                self.client.cookies.set(settings.AUTH_COOKIE_NAME, "revoked-session")
                self.upstream.side_effect = JWTError("revoked")
            else:
                self.client.cookies.clear()
            for path in self.paths:
                with self.subTest(revoked=revoked, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 401, response.text)
                    self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_local_permission_and_active_user_are_required(self):
        for inactive in (False, True):
            self.permission.visualizar = 0 if not inactive else 1
            self.user.ativo = 0 if inactive else 1
            self.db.commit()
            for path in self.paths:
                with self.subTest(inactive=inactive, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 403, response.text)

    def test_user_metadata_cannot_replace_verified_local_binding(self):
        self.identity["app_metadata"] = {}
        self.identity["user_metadata"] = {"fortcordis_user_id": self.user.id}
        self.assertEqual(self.client.get(self.paths[0]).status_code, 401)

    def test_auth_outage_is_recoverable_and_does_not_fall_back_to_legacy(self):
        self.upstream.side_effect = HTTPException(503, "Servico de autenticacao indisponivel.")
        self.assertEqual(self.client.get(self.paths[0]).status_code, 503)

    def test_query_token_stays_rejected_before_provider_io(self):
        for path in self.paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, params={"access_token": "legacy"}).status_code, 400)
        self.upstream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
