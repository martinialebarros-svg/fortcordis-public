import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-partner-auth-test-secret-key-1234567890")

from app.api.v1.endpoints import portal, portal_partner_auth
from app.core.config import settings
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.db.database import get_db
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.auditoria_evento import AuditoriaEvento
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_partner import (
    PortalPartnerClinicLink,
    PortalPartnerProfile,
    PortalPartnerReleaseTarget,
)
from app.models.portal_partner_auth import (
    PortalPartnerAccount,
    PortalPartnerAuthChallenge,
    PortalPartnerInvite,
    PortalPartnerPasswordResetToken,
    PortalPartnerSession,
)
from app.models.tutor import Tutor


class PortalPartnerAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self._app = FastAPI()
        self._app.include_router(portal.router, prefix="/api/v1/portal", tags=["portal"])
        self._app.include_router(portal_partner_auth.router, prefix="/api/v1/portal", tags=["portal"])
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "portal-partner-auth.db"
        self._engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)

        for table in (
            Tutor.__table__,
            Paciente.__table__,
            AtendimentoClinico.__table__,
            Laudo.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            AuditoriaEvento.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerClinicLink.__table__,
            PortalPartnerReleaseTarget.__table__,
            PortalPartnerInvite.__table__,
            PortalPartnerAccount.__table__,
            PortalPartnerSession.__table__,
            PortalPartnerPasswordResetToken.__table__,
            PortalPartnerAuthChallenge.__table__,
        ):
            table.create(self._engine, checkfirst=True)

    def tearDown(self) -> None:
        self._app.dependency_overrides.clear()
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

    def _install_overrides(self):
        self._app.dependency_overrides[get_db] = self._override_get_db()
        self._app.dependency_overrides[portal_partner_auth._require_portal_admin] = lambda: SimpleNamespace(
            id=1,
            nome="Admin Teste",
            email="admin@example.com",
        )

    def _seed_partner_data(self):
        db = self._session_factory()
        try:
            tutor = Tutor(
                nome="Monica Tutora",
                email="monica@example.com",
                whatsapp="85999990000",
                telefone="85999990000",
                ativo=1,
            )
            db.add(tutor)
            db.flush()

            paciente = Paciente(
                tutor_id=tutor.id,
                nome="Luke",
                especie="Canina",
                ativo=1,
            )
            db.add(paciente)
            db.flush()

            atendimento = AtendimentoClinico(
                paciente_id=paciente.id,
                tutor_id=tutor.id,
                clinica_id=None,
                agendamento_id=None,
                veterinario_id=77,
                especie="Canina",
                data_atendimento=datetime(2026, 7, 30, 9, 30),
                status="Concluido",
                criado_por_id=77,
                criado_por_nome="Vet Teste",
            )
            db.add(atendimento)
            db.flush()

            exam_visible = Exame(
                atendimento_id=atendimento.id,
                paciente_id=paciente.id,
                tipo_exame="Eletrocardiograma",
                categoria_exame="Cardiologia",
                prioridade="Rotina",
                status=PORTAL_RELEASED_STATUS,
                data_solicitacao=datetime(2026, 7, 30, 9, 0),
                data_resultado=datetime(2026, 7, 30, 10, 0),
                observacoes="Exame liberado para o parceiro.",
            )
            exam_hidden = Exame(
                atendimento_id=atendimento.id,
                paciente_id=paciente.id,
                tipo_exame="Ecocardiograma",
                categoria_exame="Cardiologia",
                prioridade="Rotina",
                status=PORTAL_RELEASED_STATUS,
                data_solicitacao=datetime(2026, 7, 30, 11, 0),
                data_resultado=datetime(2026, 7, 30, 12, 0),
                observacoes="Exame liberado no portal, mas nao para este parceiro.",
            )
            db.add_all([exam_visible, exam_hidden])
            db.flush()

            partner = PortalPartnerProfile(
                tipo="veterinario",
                nome_exibicao="Dra. Carla",
                email_login="carla@vetparceiro.com",
                telefone="85988887777",
                whatsapp="85988887777",
                cidade_base="Fortaleza",
                estado_base="CE",
                area_atuacao="Cardiologia volante",
                ativo=True,
            )
            db.add(partner)
            db.flush()

            db.add(
                PortalPartnerReleaseTarget(
                    partner_id=partner.id,
                    exame_id=exam_visible.id,
                    permitir_download=True,
                    contexto_json="{}",
                )
            )
            db.commit()
            return {
                "partner_id": partner.id,
                "partner_email": partner.email_login,
                "exam_visible_id": exam_visible.id,
                "exam_hidden_id": exam_hidden.id,
            }
        finally:
            db.close()

    def test_admin_can_generate_invite_and_activate_partner(self) -> None:
        seed = self._seed_partner_data()
        self._install_overrides()

        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_PARTNER_INVITE_AUTH_ENABLED", True))
            stack.enter_context(patch.object(settings, "PORTAL_WHATSAPP_ENABLED", False))
            stack.enter_context(patch("app.api.v1.endpoints.portal_partner_auth.registrar_auditoria", return_value=None))
            with TestClient(self._app) as client:
                create_response = client.post(
                    f"/api/v1/portal/parceiros/{seed['partner_id']}/convites",
                    json={
                        "delivery_channel": "whatsapp",
                        "delivery_target": "85988887777",
                        "expires_in_hours": 72,
                        "allow_manual_copy": True,
                    },
                )
                self.assertEqual(create_response.status_code, 200)
                create_payload = create_response.json()
                self.assertEqual(create_payload["access_mode"], "activation")
                self.assertIn("/veterinario-parceiro/ativar/", create_payload["activation_url"])

                invite_token = create_payload["activation_url"].rsplit("/", 1)[-1]
                status_response = client.get(f"/api/v1/portal/parceiros/convites/{invite_token}")
                self.assertEqual(status_response.status_code, 200)
                self.assertTrue(status_response.json()["can_activate"])

                activate_response = client.post(
                    "/api/v1/portal/parceiros/ativacao",
                    json={
                        "invite_token": invite_token,
                        "responsavel_nome": "Carla Parceira",
                        "password": "Senha123",
                        "password_confirmation": "Senha123",
                    },
                )
                self.assertEqual(activate_response.status_code, 200)
                activation_payload = activate_response.json()
                self.assertEqual(activation_payload["actor_type"], "parceiro")
                self.assertEqual(activation_payload["partner_id"], seed["partner_id"])
                self.assertEqual(activation_payload["partner_tipo"], "veterinario")

    def test_partner_login_lists_only_released_exams_in_scope(self) -> None:
        seed = self._seed_partner_data()
        self._install_overrides()

        db = self._session_factory()
        try:
            db.add(
                PortalPartnerAccount(
                    partner_id=seed["partner_id"],
                    email_normalized=seed["partner_email"],
                    responsavel_nome="Carla Parceira",
                    password_hash=portal_partner_auth.hash_password("Senha123"),
                    status="active",
                    email_verified_at=datetime(2026, 7, 30, 8, 0),
                    activated_at=datetime(2026, 7, 30, 8, 0),
                )
            )
            db.commit()
        finally:
            db.close()

        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, "PORTAL_PARTNER_INVITE_AUTH_ENABLED", True))
            stack.enter_context(patch.object(settings, "PORTAL_PARTNER_PASSWORD_LOGIN_ENABLED", True))
            stack.enter_context(patch("app.api.v1.endpoints.portal_partner_auth.registrar_auditoria", return_value=None))
            with TestClient(self._app) as client:
                login_response = client.post(
                    "/api/v1/portal/parceiros/auth/login",
                    json={
                        "email": seed["partner_email"],
                        "password": "Senha123",
                        "remember_device_until_shift_end": False,
                    },
                )
                self.assertEqual(login_response.status_code, 200)
                token = login_response.json()["access_token"]
                self.assertTrue(token)

                list_response = client.get(
                    "/api/v1/portal/parceiros/exames",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(list_response.status_code, 200)
                payload = list_response.json()
                self.assertEqual(payload["partner_id"], seed["partner_id"])
                self.assertEqual(payload["total"], 1)
                self.assertEqual([item["id"] for item in payload["items"]], [seed["exam_visible_id"]])
                self.assertNotIn(seed["exam_hidden_id"], [item["id"] for item in payload["items"]])


if __name__ == "__main__":
    unittest.main()
