import os
import socket
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-access-http-test-secret-key-1234567890")

from app.core.config import settings
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.api.v1.endpoints import laudos, portal
from app.core.portal_security import PORTAL_DOWNLOAD_TOKEN_HEADER, create_portal_session_token
from app.db.database import get_db
from app.main import app
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.papel import Papel, usuario_papel
from app.models.imagem_laudo import ImagemLaudo
from app.models.portal_access import PortalAccessChallenge
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_partner import PortalPartnerClinicLink, PortalPartnerProfile, PortalPartnerReleaseTarget
from app.models.tutor import Tutor
from app.models.user import User
from app.services.echo_editor_source import load_echo_editor_source
from app.services.portal_clinic_exam_link_service import issue_exam_link


class _FakeRemoteResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self._body = body
        self.headers = headers or {}
        self.is_redirect = False

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield self._body

    def close(self):
        return None


class _FakeRemoteClient:
    def __init__(self, body: bytes, headers: dict[str, str] | None, requested_urls: list[dict]):
        self._body = body
        self._headers = headers or {}
        self._requested_urls = requested_urls

    def build_request(self, method: str, url: str, headers: dict[str, str] | None = None):
        request = SimpleNamespace(method=method, url=url, headers=headers or {})
        self._requested_urls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
            }
        )
        return request

    def send(self, request, stream: bool = False):
        _ = request
        _ = stream
        return _FakeRemoteResponse(self._body, self._headers)

    def close(self):
        return None


class PortalAccessHttpFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "portal-access-http-flow.db"
        self._engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
        )

        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Laudo.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            PortalAccessChallenge.__table__,
        ):
            table.create(self._engine, checkfirst=True)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _override_get_db(self):
        def _get_db_override():
            db = self._session_factory()
            try:
                yield db
            finally:
                db.close()

        return _get_db_override

    def _seed_portal_data(self, *, remote_attachment_url: str | None = None):
        db = self._session_factory()
        try:
            tutor = Tutor(
                nome="Maria Tutora",
                email="maria@example.com",
                whatsapp="(85) 99999-0000",
                telefone="85999990000",
                ativo=1,
            )
            clinica = Clinica(
                nome="Clinica Parceira A",
                email="parceira@example.com",
                ativo=True,
            )
            outra_clinica = Clinica(
                nome="Clinica Parceira B",
                email="outra@example.com",
                ativo=True,
            )
            db.add_all([tutor, clinica, outra_clinica])
            db.flush()

            paciente = Paciente(
                tutor_id=tutor.id,
                nome="Luna",
                especie="Canina",
                ativo=1,
            )
            db.add(paciente)
            db.flush()

            atendimento = AtendimentoClinico(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=clinica.id,
                agendamento_id=None,
                veterinario_id=77,
                especie="Canina",
                data_atendimento=datetime(2026, 6, 16, 9, 30),
                status="Concluido",
                criado_por_id=77,
                criado_por_nome="Vet Teste",
            )
            db.add(atendimento)
            db.flush()

            exame = Exame(
                atendimento_id=atendimento.id,
                paciente_id=paciente.id,
                tipo_exame="Ecocardiograma",
                categoria_exame="Cardiologia",
                prioridade="Rotina",
                status=PORTAL_RELEASED_STATUS,
                data_solicitacao=datetime(2026, 6, 16, 9, 0),
                data_resultado=datetime(2026, 6, 16, 10, 0),
                observacoes="Exame liberado para portal.",
            )
            db.add(exame)
            db.flush()

            exame_interno = Exame(
                atendimento_id=atendimento.id,
                paciente_id=paciente.id,
                tipo_exame="Eletrocardiograma",
                categoria_exame="Cardiologia",
                prioridade="Rotina",
                status="Concluido",
                data_solicitacao=datetime(2026, 6, 16, 9, 15),
                data_resultado=datetime(2026, 6, 16, 10, 15),
                observacoes="Exame concluido internamente, ainda nao liberado no portal.",
            )
            db.add(exame_interno)
            db.flush()

            attachment_bytes = b"%PDF-1.4\nportal http flow\n"
            attachment_path = Path(self._tmpdir.name) / "eco-luna.pdf"
            if remote_attachment_url is None:
                attachment_path.write_bytes(attachment_bytes)
            anexo = AnexoAtendimento(
                atendimento_id=atendimento.id,
                exame_id=exame.id,
                tipo="documento",
                descricao="Laudo PDF",
                url=remote_attachment_url or f"/api/v1/portal/anexos/{exame.id}/arquivo",
                nome_original="eco-luna.pdf",
                tamanho=len(attachment_bytes),
                mime_type="application/pdf",
                caminho_arquivo=None if remote_attachment_url else str(attachment_path),
                origem="upload",
            )
            db.add(anexo)
            db.commit()
            return {
                "tutor_id": tutor.id,
                "tutor_email": tutor.email,
                "paciente_id": paciente.id,
                "clinica_id": clinica.id,
                "clinica_email": clinica.email,
                "outra_clinica_id": outra_clinica.id,
                "outra_clinica_email": outra_clinica.email,
                "exame_id": exame.id,
                "anexo_id": anexo.id,
                "attachment_bytes": attachment_bytes,
                "remote_attachment_url": remote_attachment_url,
            }
        finally:
            db.close()

    def _request_tutor_token(self, client: TestClient, seed: dict) -> str:
        challenge_response = client.post(
            "/api/v1/portal/tutores/sessao-link",
            json={
                "tutor_id": seed["tutor_id"],
                "paciente_id": seed["paciente_id"],
                "canal": "email",
                "contato": seed["tutor_email"],
            },
        )
        self.assertEqual(challenge_response.status_code, 202)
        challenge_payload = challenge_response.json()
        self.assertTrue(challenge_payload["accepted"])
        self.assertTrue(challenge_payload["debug_code"])

        verify_response = client.post(
            "/api/v1/portal/auth/verificar-codigo",
            json={
                "challenge_id": challenge_payload["challenge_id"],
                "codigo": challenge_payload["debug_code"],
            },
        )
        self.assertEqual(verify_response.status_code, 200)
        return verify_response.json()["access_token"]

    def _request_clinic_token(self, client: TestClient, *, clinica_id: int, clinica_email: str) -> str:
        challenge_response = client.post(
            "/api/v1/portal/clinicas/sessao-link",
            json={
                "clinica_id": clinica_id,
                "email": clinica_email,
                "responsavel_nome": "Dra. Parceira",
            },
        )
        self.assertEqual(challenge_response.status_code, 202)
        challenge_payload = challenge_response.json()
        self.assertTrue(challenge_payload["accepted"])
        self.assertTrue(challenge_payload["debug_code"])

        verify_response = client.post(
            "/api/v1/portal/auth/verificar-codigo",
            json={
                "challenge_id": challenge_payload["challenge_id"],
                "codigo": challenge_payload["debug_code"],
            },
        )
        self.assertEqual(verify_response.status_code, 200)
        return verify_response.json()["access_token"]

    def test_tutor_http_flow_lists_and_downloads_attachment(self) -> None:
        seed = self._seed_portal_data()
        app.dependency_overrides[get_db] = self._override_get_db()

        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_DEBUG_EXPOSE_CODE", True))
            stack.enter_context(patch("app.api.v1.endpoints.portal.registrar_auditoria", return_value=None))
            stack.enter_context(
                patch(
                    "app.api.v1.endpoints.portal.send_portal_access_code",
                    return_value=SimpleNamespace(provider="smtp", channel="email"),
                )
            )
            with TestClient(app) as client:
                token = self._request_tutor_token(client, seed)
                auth_headers = {"Authorization": f"Bearer {token}"}

                list_response = client.get(
                    f"/api/v1/portal/pets/{seed['paciente_id']}/exames",
                    headers=auth_headers,
                )
                self.assertEqual(list_response.status_code, 200)
                list_payload = list_response.json()
                self.assertEqual(list_payload["total"], 1)
                self.assertEqual(list_payload["items"][0]["id"], seed["exame_id"])
                self.assertEqual(list_payload["items"][0]["anexos"][0]["anexo_id"], seed["anexo_id"])

                download_url_response = client.post(
                    f"/api/v1/portal/exames/{seed['exame_id']}/download-url",
                    headers=auth_headers,
                    json={},
                )
                self.assertEqual(download_url_response.status_code, 200)
                download_item = download_url_response.json()["items"][0]
                self.assertEqual(download_item["anexo_id"], seed["anexo_id"])
                self.assertEqual(download_item["download_token_header"], PORTAL_DOWNLOAD_TOKEN_HEADER)

                file_response = client.get(
                    download_item["download_url"],
                    headers={download_item["download_token_header"]: download_item["download_token"]},
                )
                self.assertEqual(file_response.status_code, 200)
                self.assertEqual(file_response.content, seed["attachment_bytes"])
                self.assertEqual(file_response.headers["content-type"], "application/pdf")

    def test_clinic_http_flow_filters_scope_and_downloads_attachment(self) -> None:
        seed = self._seed_portal_data()
        app.dependency_overrides[get_db] = self._override_get_db()

        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_DEBUG_EXPOSE_CODE", True))
            stack.enter_context(patch("app.api.v1.endpoints.portal.registrar_auditoria", return_value=None))
            stack.enter_context(
                patch(
                    "app.api.v1.endpoints.portal.send_portal_access_code",
                    return_value=SimpleNamespace(provider="smtp", channel="email"),
                )
            )
            with TestClient(app) as client:
                token = self._request_clinic_token(
                    client,
                    clinica_id=seed["clinica_id"],
                    clinica_email=seed["clinica_email"],
                )
                other_token = self._request_clinic_token(
                    client,
                    clinica_id=seed["outra_clinica_id"],
                    clinica_email=seed["outra_clinica_email"],
                )

                clinic_headers = {"Authorization": f"Bearer {token}"}
                other_headers = {"Authorization": f"Bearer {other_token}"}

                own_list_response = client.get(
                    f"/api/v1/portal/pets/{seed['paciente_id']}/exames",
                    headers=clinic_headers,
                )
                self.assertEqual(own_list_response.status_code, 200)
                self.assertEqual(own_list_response.json()["total"], 1)

                other_list_response = client.get(
                    f"/api/v1/portal/pets/{seed['paciente_id']}/exames",
                    headers=other_headers,
                )
                self.assertEqual(other_list_response.status_code, 200)
                self.assertEqual(other_list_response.json()["total"], 0)

                download_url_response = client.post(
                    f"/api/v1/portal/exames/{seed['exame_id']}/download-url",
                    headers=clinic_headers,
                    json={},
                )
                self.assertEqual(download_url_response.status_code, 200)
                download_item = download_url_response.json()["items"][0]

                blocked_download_url_response = client.post(
                    f"/api/v1/portal/exames/{seed['exame_id']}/download-url",
                    headers=other_headers,
                    json={},
                )
                self.assertEqual(blocked_download_url_response.status_code, 403)

                file_response = client.get(
                    download_item["download_url"],
                    headers={download_item["download_token_header"]: download_item["download_token"]},
                )
                self.assertEqual(file_response.status_code, 200)
                self.assertEqual(file_response.content, seed["attachment_bytes"])

    def test_suspensao_bloqueia_downloads_e_o_mesmo_link_entrega_o_pdf_corrigido_ao_retomar(self):
        for table in (
            User.__table__, Papel.__table__, usuario_papel, AuditoriaEvento.__table__,
            ImagemLaudo.__table__, PortalClinicExamLink.__table__,
            PortalPartnerProfile.__table__, PortalPartnerReleaseTarget.__table__,
            PortalPartnerClinicLink.__table__,
        ):
            table.create(self._engine)

        seed = self._seed_portal_data()
        with self._session_factory() as db:
            admin = User(email="admin@example.com", nome="Operador de teste", papeis=[Papel(nome="admin")])
            partner = PortalPartnerProfile(tipo="veterinario", nome_exibicao="Veterinário de teste")
            laudo = Laudo(
                paciente_id=seed["paciente_id"], veterinario_id=77, tipo="ecocardiograma",
                titulo="Laudo fictício", clinic_id=seed["clinica_id"], status="Finalizado",
            )
            db.add_all([admin, partner, laudo])
            db.flush()
            db.get(Exame, seed["exame_id"]).laudo_id = laudo.id
            db.get(AnexoAtendimento, seed["anexo_id"]).origem = laudos.PORTAL_LAUDO_ATTACHMENT_ORIGIN
            db.add(PortalPartnerReleaseTarget(partner_id=partner.id, exame_id=seed["exame_id"], laudo_id=laudo.id))
            _, link_token = issue_exam_link(db, exame_id=seed["exame_id"], clinica_id=seed["clinica_id"], laudo_id=laudo.id)
            laudo_id, partner_id = laudo.id, partner.id
            original_revision = load_echo_editor_source(db, laudo_id).revision
            admin_token = jwt.encode({"sub": admin.email}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        def headers_for(actor, actor_id, **scope_ids):
            token, _ = create_portal_session_token(
                actor_type=actor, actor_id=actor_id, challenge_id="teste",
                scope=["exam:read", "exam:download"], **scope_ids,
            )
            return {"Authorization": f"Bearer {token}"}

        clinica_headers = headers_for("clinica", seed["clinica_id"], clinica_id=seed["clinica_id"])
        partner_headers = headers_for("parceiro", partner_id)
        tutor_headers = headers_for("tutor", seed["tutor_id"], paciente_id=seed["paciente_id"])
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        admin_route = f"/api/v1/laudos/{laudo_id}"
        suspension_route = f"{admin_route}/portal/download-suspenso"
        link_route = f"/api/v1/portal/laudo-link/{link_token}"
        token_route = f"/api/v1/portal/exames/{seed['exame_id']}/download-url"
        file_route = f"/api/v1/portal/anexos/{seed['anexo_id']}/arquivo"

        def download(client, item):
            return client.get(file_route, headers={item["download_token_header"]: item["download_token"]})

        app.dependency_overrides[get_db] = self._override_get_db()
        with (
            patch.object(settings, "AUTH_PROVIDER", "local"),
            patch.object(portal, "registrar_auditoria"),
            TestClient(app) as client,
        ):
            response = client.get(admin_route, headers=admin_headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["portal_pode_suspender_download"])
            old_link_item = client.post(link_route).json()["arquivos"][0]
            old_items = [
                client.post(token_route, headers=headers).json()["items"][0]
                for headers in (clinica_headers, partner_headers)
            ]
            self.assertEqual(client.put(suspension_route, json={"suspenso": True}, headers=partner_headers).status_code, 401)
            for _ in range(2):
                response = client.put(suspension_route, json={"suspenso": True}, headers=admin_headers)
                self.assertEqual(response.json(), {"portal_download_suspenso": True})
            self.assertEqual(client.post(f"{admin_route}/portal/liberar", headers=admin_headers).status_code, 409)
            response = client.post(
                f"{admin_route}/portal/whatsapp", json={"idempotency_key": "aviso-teste"}, headers=admin_headers,
            )
            self.assertEqual(response.status_code, 409)

            for headers, path in (
                (clinica_headers, "/api/v1/portal/clinicas/exames"),
                (partner_headers, "/api/v1/portal/parceiros/exames"),
            ):
                item = client.get(path, headers=headers).json()["items"][0]
                self.assertTrue(item["download_suspenso"])
                self.assertFalse(item["anexos"][0]["download_available"])
                self.assertEqual(client.post(token_route, headers=headers).status_code, 423)
                self.assertEqual(client.get(file_route, headers=headers).status_code, 423)
            for item in [old_link_item, *old_items]:
                self.assertEqual(download(client, item).status_code, 423)
            link = client.post(link_route).json()
            self.assertTrue(link["download_suspenso"])
            self.assertEqual(link["arquivos"], [])

            with self._session_factory() as db:
                self.assertEqual(load_echo_editor_source(db, laudo_id).revision, original_revision)
                self.assertIsNone(db.get(Exame, seed["exame_id"]).visualizado_portal_em)
                self.assertIsNone(db.query(PortalPartnerReleaseTarget).one().downloaded_at)
            self.assertEqual(client.get(file_route, headers=tutor_headers).content, seed["attachment_bytes"])

            novo_pdf = SimpleNamespace(content=b"%PDF-1.4\nVersao corrigida\n", filename="corrigido.pdf")
            novo_caminho = Path(self._tmpdir.name) / novo_pdf.filename
            novo_caminho.write_bytes(novo_pdf.content)
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=novo_pdf),
                patch.object(laudos, "store_atendimento_attachment_file", return_value=(str(novo_caminho), novo_pdf.filename, "application/pdf")),
            ):
                response = client.put(
                    admin_route, json={"diagnostico": "Texto corrigido", "portal_download_suspenso": False}, headers=admin_headers,
                )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["portal_download_suspenso"])
            self.assertEqual(download(client, old_link_item).status_code, 423)
            self.assertEqual(
                client.put(suspension_route, json={"suspenso": False}, headers=admin_headers).json(),
                {"portal_download_suspenso": False},
            )

            new_link_item = client.post(link_route).json()["arquivos"][0]
            response = download(client, new_link_item)
            self.assertEqual(response.content, novo_pdf.content)
            self.assertEqual(response.headers["Cache-Control"], "private, no-store")
            self.assertEqual(download(client, old_items[1]).content, novo_pdf.content)

        with self._session_factory() as db:
            self.assertEqual(db.get(Laudo, laudo_id).status, PORTAL_RELEASED_STATUS)
            self.assertIsNone(db.query(PortalPartnerReleaseTarget).one().revoked_at)
            self.assertEqual(
                [event.acao for event in db.query(AuditoriaEvento).order_by(AuditoriaEvento.id)],
                ["LAUDO_PORTAL_DOWNLOAD_SUSPENSO", "LAUDO_PORTAL_DOWNLOAD_RETOMADO"],
            )

    def test_clinic_download_marks_exame_as_visualizado_no_portal(self) -> None:
        seed = self._seed_portal_data()
        app.dependency_overrides[get_db] = self._override_get_db()

        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_DEBUG_EXPOSE_CODE", True))
            stack.enter_context(patch("app.api.v1.endpoints.portal.registrar_auditoria", return_value=None))
            stack.enter_context(
                patch(
                    "app.api.v1.endpoints.portal.send_portal_access_code",
                    return_value=SimpleNamespace(provider="smtp", channel="email"),
                )
            )
            with TestClient(app) as client:
                token = self._request_clinic_token(
                    client,
                    clinica_id=seed["clinica_id"],
                    clinica_email=seed["clinica_email"],
                )
                clinic_headers = {"Authorization": f"Bearer {token}"}

                db = self._session_factory()
                try:
                    exame_antes = db.query(Exame).filter(Exame.id == seed["exame_id"]).first()
                    self.assertIsNone(exame_antes.visualizado_portal_em)
                finally:
                    db.close()

                download_url_response = client.post(
                    f"/api/v1/portal/exames/{seed['exame_id']}/download-url",
                    headers=clinic_headers,
                    json={},
                )
                self.assertEqual(download_url_response.status_code, 200)
                download_item = download_url_response.json()["items"][0]

                file_response = client.get(
                    download_item["download_url"],
                    headers={download_item["download_token_header"]: download_item["download_token"]},
                )
                self.assertEqual(file_response.status_code, 200)

                db = self._session_factory()
                try:
                    exame_depois = db.query(Exame).filter(Exame.id == seed["exame_id"]).first()
                    self.assertIsNotNone(exame_depois.visualizado_portal_em)
                    primeiro_acesso = exame_depois.visualizado_portal_em
                finally:
                    db.close()

                # Um segundo download nao deve "andar" o timestamp - so o
                # PRIMEIRO acesso conta.
                second_file_response = client.get(
                    download_item["download_url"],
                    headers={download_item["download_token_header"]: download_item["download_token"]},
                )
                self.assertEqual(second_file_response.status_code, 200)

                db = self._session_factory()
                try:
                    exame_final = db.query(Exame).filter(Exame.id == seed["exame_id"]).first()
                    self.assertEqual(exame_final.visualizado_portal_em, primeiro_acesso)
                finally:
                    db.close()

    def test_tutor_download_nao_marca_exame_como_visualizado_no_portal(self) -> None:
        # O mesmo endpoint de download atende tutor e clinica parceira; o
        # tutor abrindo o proprio exame nao pode ser confundido com a
        # clinica parceira tendo visto o resultado.
        seed = self._seed_portal_data()
        app.dependency_overrides[get_db] = self._override_get_db()

        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_DEBUG_EXPOSE_CODE", True))
            stack.enter_context(patch("app.api.v1.endpoints.portal.registrar_auditoria", return_value=None))
            stack.enter_context(
                patch(
                    "app.api.v1.endpoints.portal.send_portal_access_code",
                    return_value=SimpleNamespace(provider="smtp", channel="email"),
                )
            )
            with TestClient(app) as client:
                token = self._request_tutor_token(client, seed)
                auth_headers = {"Authorization": f"Bearer {token}"}

                download_url_response = client.post(
                    f"/api/v1/portal/exames/{seed['exame_id']}/download-url",
                    headers=auth_headers,
                    json={},
                )
                self.assertEqual(download_url_response.status_code, 200)
                download_item = download_url_response.json()["items"][0]

                file_response = client.get(
                    download_item["download_url"],
                    headers={download_item["download_token_header"]: download_item["download_token"]},
                )
                self.assertEqual(file_response.status_code, 200)

                db = self._session_factory()
                try:
                    exame = db.query(Exame).filter(Exame.id == seed["exame_id"]).first()
                    self.assertIsNone(exame.visualizado_portal_em)
                finally:
                    db.close()

    def test_tutor_http_flow_downloads_remote_attachment_url(self) -> None:
        remote_url = "https://storage.example.com/portal/eco-luna.pdf"
        remote_bytes = b"%PDF-1.4\nremote portal http flow\n"
        requested_urls: list[dict] = []
        seed = self._seed_portal_data(remote_attachment_url=remote_url)
        app.dependency_overrides[get_db] = self._override_get_db()

        def _fake_client_factory(*args, **kwargs):
            _ = args
            _ = kwargs
            return _FakeRemoteClient(
                remote_bytes,
                headers={
                    "content-type": "application/pdf",
                    "content-length": str(len(remote_bytes)),
                },
                requested_urls=requested_urls,
            )

        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_DEBUG_EXPOSE_CODE", True))
            stack.enter_context(patch("app.api.v1.endpoints.portal.registrar_auditoria", return_value=None))
            stack.enter_context(
                patch(
                    "app.api.v1.endpoints.portal.send_portal_access_code",
                    return_value=SimpleNamespace(provider="smtp", channel="email"),
                )
            )
            stack.enter_context(
                patch("app.services.attachment_download_service.httpx.Client", side_effect=_fake_client_factory)
            )
            # "storage.example.com" e um host fictício deste teste - a
            # validacao anti-SSRF (attachment_download_service) resolve o
            # hostname de verdade antes de tentar a conexao; sem esse mock a
            # resolucao real falharia (NXDOMAIN) e o fluxo nunca chegaria ao
            # cliente HTTP mockado acima. So intercepta esse host especifico -
            # qualquer outra resolucao (usada internamente pelo TestClient/
            # anyio durante o ciclo de request) cai no socket.getaddrinfo real.
            _real_getaddrinfo = socket.getaddrinfo

            def _fake_getaddrinfo(host, *args, **kwargs):
                if host == "storage.example.com":
                    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
                return _real_getaddrinfo(host, *args, **kwargs)

            stack.enter_context(patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo))
            with TestClient(app) as client:
                token = self._request_tutor_token(client, seed)
                auth_headers = {"Authorization": f"Bearer {token}"}

                list_response = client.get(
                    f"/api/v1/portal/pets/{seed['paciente_id']}/exames",
                    headers=auth_headers,
                )
                self.assertEqual(list_response.status_code, 200)
                list_payload = list_response.json()
                self.assertTrue(list_payload["items"][0]["anexos"][0]["download_available"])

                download_url_response = client.post(
                    f"/api/v1/portal/exames/{seed['exame_id']}/download-url",
                    headers=auth_headers,
                    json={},
                )
                self.assertEqual(download_url_response.status_code, 200)
                download_item = download_url_response.json()["items"][0]

                file_response = client.get(
                    download_item["download_url"],
                    headers={download_item["download_token_header"]: download_item["download_token"]},
                )
                self.assertEqual(file_response.status_code, 200)
                self.assertEqual(file_response.content, remote_bytes)
                self.assertEqual(file_response.headers["content-type"], "application/pdf")

        self.assertEqual(len(requested_urls), 1)
        self.assertEqual(requested_urls[0]["url"], remote_url)


if __name__ == "__main__":
    unittest.main()
