import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-partners-api-test-secret-key-1234567890")

from app.api.v1.endpoints import portal_partners
from app.db.database import get_db
from app.models.clinica import Clinica
from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_CLINICA,
    PortalPartnerClinicLink,
    PortalPartnerProfile,
)


class PortalPartnersApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._app = FastAPI()
        self._app.include_router(portal_partners.router, prefix="/api/v1/portal", tags=["portal"])
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "portal-partners-api.db"
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
            Clinica.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerClinicLink.__table__,
        ):
            table.create(self._engine, checkfirst=True)

        self._app.dependency_overrides[get_db] = self._override_get_db()
        self._app.dependency_overrides[portal_partners._require_portal_admin] = lambda: SimpleNamespace(
            id=1,
            nome="Admin Teste",
            email="admin@example.com",
        )
        self._app.dependency_overrides[portal_partners._require_portal_operational_user] = lambda: SimpleNamespace(
            id=2,
            nome="Operacao Teste",
            email="operacao@example.com",
        )

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

    def _seed_active_clinic(self, *, nome: str = "Animal Care", email: str = "contato@animalcare.com") -> int:
        db = self._session_factory()
        try:
            clinic = Clinica(
                nome=nome,
                email=email,
                telefone="85999990001",
                cidade="Fortaleza",
                estado="CE",
                observacoes="Clinica base de teste",
                ativo=True,
            )
            db.add(clinic)
            db.commit()
            db.refresh(clinic)
            return clinic.id
        finally:
            db.close()

    def test_admin_can_list_create_and_update_external_veterinary_partner(self) -> None:
        clinica_id = self._seed_active_clinic()

        db = self._session_factory()
        try:
            db.add(
                PortalPartnerProfile(
                    tipo=PORTAL_PARTNER_TYPE_CLINICA,
                    clinica_id=clinica_id,
                    nome_exibicao="Animal Care",
                    email_login="portal@animalcare.com",
                    telefone="85999990001",
                    whatsapp="85999990001",
                    cidade_base="Fortaleza",
                    estado_base="CE",
                    ativo=True,
                )
            )
            db.commit()
        finally:
            db.close()

        with TestClient(self._app) as client:
            list_response = client.get("/api/v1/portal/parceiros?tipo=clinica")
            self.assertEqual(list_response.status_code, 200)
            list_payload = list_response.json()
            self.assertEqual(list_payload["total"], 1)
            self.assertEqual(list_payload["items"][0]["clinica_id"], clinica_id)
            self.assertEqual(list_payload["items"][0]["tipo_label"], "Clinica parceira")

            create_response = client.post(
                "/api/v1/portal/parceiros",
                json={
                    "tipo": "veterinario",
                    "nome_exibicao": "Dra. Carla Soares",
                    "email_login": "carla.soares@example.com",
                    "whatsapp": "85999990002",
                    "cidade_base": "Fortaleza",
                    "estado_base": "CE",
                    "area_atuacao": "Cardiologia volante",
                    "crmv": "12345",
                },
            )
            self.assertEqual(create_response.status_code, 201)
            create_payload = create_response.json()
            self.assertEqual(create_payload["tipo"], "veterinario")
            self.assertEqual(create_payload["tipo_label"], "Veterinario parceiro")
            self.assertEqual(create_payload["email_login"], "carla.soares@example.com")
            self.assertEqual(create_payload["area_atuacao"], "Cardiologia volante")

            partner_id = create_payload["id"]
            search_response = client.get("/api/v1/portal/parceiros?q=carla")
            self.assertEqual(search_response.status_code, 200)
            self.assertEqual(search_response.json()["total"], 1)

            update_response = client.patch(
                f"/api/v1/portal/parceiros/{partner_id}",
                json={
                    "telefone": "85999990003",
                    "area_atuacao": "Telemedicina cardiologica",
                    "ativo": False,
                },
            )
            self.assertEqual(update_response.status_code, 200)
            update_payload = update_response.json()
            self.assertEqual(update_payload["telefone"], "85999990003")
            self.assertEqual(update_payload["area_atuacao"], "Telemedicina cardiologica")
            self.assertFalse(update_payload["ativo"])

    def test_admin_can_create_clinic_partner_with_defaults_and_prevent_duplicate_bindings(self) -> None:
        clinica_id = self._seed_active_clinic(nome="Pet SUS", email="portal@petsus.com")

        with TestClient(self._app) as client:
            create_response = client.post(
                "/api/v1/portal/parceiros",
                json={
                    "tipo": "clinica",
                    "clinica_id": clinica_id,
                },
            )
            self.assertEqual(create_response.status_code, 201)
            payload = create_response.json()
            self.assertEqual(payload["clinica_id"], clinica_id)
            self.assertEqual(payload["nome_exibicao"], "Pet SUS")
            self.assertEqual(payload["email_login"], "portal@petsus.com")
            self.assertEqual(payload["whatsapp"], "85999990001")
            self.assertEqual(payload["cidade_base"], "Fortaleza")
            self.assertEqual(payload["estado_base"], "CE")

            duplicate_clinic_response = client.post(
                "/api/v1/portal/parceiros",
                json={
                    "tipo": "clinica",
                    "clinica_id": clinica_id,
                },
            )
            self.assertEqual(duplicate_clinic_response.status_code, 409)
            self.assertIn("ja possui", duplicate_clinic_response.json()["detail"])

            duplicate_email_response = client.post(
                "/api/v1/portal/parceiros",
                json={
                    "tipo": "veterinario",
                    "nome_exibicao": "Dr. Bruno Lima",
                    "email_login": "portal@petsus.com",
                    "telefone": "85999990005",
                    "cidade_base": "Aquiraz",
                    "estado_base": "CE",
                },
            )
            self.assertEqual(duplicate_email_response.status_code, 409)
            self.assertIn("email de login", duplicate_email_response.json()["detail"])

    def test_operational_flow_can_list_and_quick_create_veterinary_partner(self) -> None:
        with TestClient(self._app) as client:
            create_response = client.post(
                "/api/v1/portal/parceiros/veterinarios/cadastro-rapido",
                json={
                    "tipo": "clinica",
                    "nome_exibicao": "Dra. Lia Ponte",
                    "email_login": "lia.ponte@example.com",
                    "whatsapp": "85999990008",
                    "cidade_base": "Fortaleza",
                    "estado_base": "CE",
                    "area_atuacao": "Cardiologia domiciliar",
                },
            )
            self.assertEqual(create_response.status_code, 201)
            payload = create_response.json()
            self.assertEqual(payload["tipo"], "veterinario")
            self.assertEqual(payload["nome_exibicao"], "Dra. Lia Ponte")

            list_response = client.get("/api/v1/portal/parceiros/veterinarios/opcoes?q=lia")
            self.assertEqual(list_response.status_code, 200)
            list_payload = list_response.json()
            self.assertEqual(list_payload["total"], 1)
            self.assertEqual(list_payload["items"][0]["id"], payload["id"])
            self.assertEqual(list_payload["items"][0]["tipo"], "veterinario")


if __name__ == "__main__":
    unittest.main()
