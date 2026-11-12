"""Vinculo do veterinario parceiro com varias clinicas (CA-001..CA-005, CA-016, CA-017)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-partner-clinic-links-test-secret-key-123456")

from app.api.v1.endpoints import portal_partners
from app.db.database import get_db
from app.models.clinica import Clinica
from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_CLINICA,
    PORTAL_PARTNER_TYPE_VETERINARIO,
    PortalPartnerClinicLink,
    PortalPartnerProfile,
)


def _load_migration():
    from importlib import util

    module_path = BACKEND_DIR / "migrations" / "versions" / "20260916_86_portal_partner_clinic_links.py"
    spec = util.spec_from_file_location("portal_partner_clinic_links_migration", module_path)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PortalPartnerClinicLinksTest(unittest.TestCase):
    def setUp(self) -> None:
        self._app = FastAPI()
        self._app.include_router(portal_partners.router, prefix="/api/v1/portal", tags=["portal"])
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "portal-partner-clinic-links.db"
        self._engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)

        for table in (
            Clinica.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerClinicLink.__table__,
        ):
            table.create(self._engine, checkfirst=True)

        self._app.dependency_overrides[get_db] = self._override_get_db()
        self._app.dependency_overrides[portal_partners._require_portal_admin] = lambda: SimpleNamespace(
            id=1, nome="Admin Teste", email="admin@example.com"
        )
        self._app.dependency_overrides[portal_partners._require_portal_operational_user] = lambda: SimpleNamespace(
            id=2, nome="Operacao Teste", email="operacao@example.com"
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

    def _seed_clinic(self, nome: str, *, ativo: bool = True) -> int:
        db = self._session_factory()
        try:
            clinic = Clinica(
                nome=nome,
                email=f"{nome.lower().replace(' ', '')}@example.com",
                telefone="85999990001",
                cidade="Fortaleza",
                estado="CE",
                ativo=ativo,
            )
            db.add(clinic)
            db.commit()
            db.refresh(clinic)
            return clinic.id
        finally:
            db.close()

    def _payload_veterinario(self, **overrides):
        payload = {
            "tipo": PORTAL_PARTNER_TYPE_VETERINARIO,
            "nome_exibicao": "Dra. Carla Soares",
            "email_login": "carla@vetparceiro.com",
            "whatsapp": "85999990010",
            "cidade_base": "Fortaleza",
            "estado_base": "CE",
        }
        payload.update(overrides)
        return payload

    def _links_no_banco(self, partner_id: int):
        db = self._session_factory()
        try:
            return {
                int(link.clinica_id): bool(link.receber_todos_laudos)
                for link in db.query(PortalPartnerClinicLink)
                .filter(PortalPartnerClinicLink.partner_id == partner_id)
                .all()
            }
        finally:
            db.close()

    def test_cria_veterinario_com_tres_clinicas_vinculadas(self) -> None:
        """CA-001."""
        clinica_a = self._seed_clinic("Animal Care")
        clinica_b = self._seed_clinic("Bicho Feliz")
        clinica_c = self._seed_clinic("Cao e Cia")

        with TestClient(self._app) as client:
            response = client.post(
                "/api/v1/portal/parceiros",
                json=self._payload_veterinario(
                    clinicas_vinculadas=[
                        {"clinica_id": clinica_a, "receber_todos_laudos": True},
                        {"clinica_id": clinica_b},
                        {"clinica_id": clinica_c, "receber_todos_laudos": False},
                    ]
                ),
            )

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        vinculos = body["clinicas_vinculadas"]
        self.assertEqual(len(vinculos), 3)
        self.assertEqual(
            {item["clinica_id"]: item["receber_todos_laudos"] for item in vinculos},
            {clinica_a: True, clinica_b: False, clinica_c: False},
        )
        self.assertEqual(
            {item["clinica_id"]: item["clinica_nome"] for item in vinculos},
            {clinica_a: "Animal Care", clinica_b: "Bicho Feliz", clinica_c: "Cao e Cia"},
        )
        self.assertEqual(
            self._links_no_banco(body["id"]),
            {clinica_a: True, clinica_b: False, clinica_c: False},
        )

    def test_clinica_repetida_no_payload_responde_422_e_nao_grava(self) -> None:
        """CA-002."""
        clinica_a = self._seed_clinic("Animal Care")

        with TestClient(self._app) as client:
            response = client.post(
                "/api/v1/portal/parceiros",
                json=self._payload_veterinario(
                    clinicas_vinculadas=[
                        {"clinica_id": clinica_a, "receber_todos_laudos": True},
                        {"clinica_id": clinica_a},
                    ]
                ),
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("mais de uma vez", response.json()["detail"])

        db = self._session_factory()
        try:
            self.assertEqual(db.query(PortalPartnerProfile).count(), 0)
            self.assertEqual(db.query(PortalPartnerClinicLink).count(), 0)
        finally:
            db.close()

    def test_clinica_inativa_responde_404_e_nao_grava(self) -> None:
        """CA-003."""
        clinica_inativa = self._seed_clinic("Clinica Fechada", ativo=False)

        with TestClient(self._app) as client:
            response = client.post(
                "/api/v1/portal/parceiros",
                json=self._payload_veterinario(
                    clinicas_vinculadas=[{"clinica_id": clinica_inativa, "receber_todos_laudos": True}]
                ),
            )

        self.assertEqual(response.status_code, 404, response.text)

        db = self._session_factory()
        try:
            self.assertEqual(db.query(PortalPartnerProfile).count(), 0)
            self.assertEqual(db.query(PortalPartnerClinicLink).count(), 0)
        finally:
            db.close()

    def test_vinculos_em_parceiro_do_tipo_clinica_responde_422(self) -> None:
        """CA-004."""
        clinica_a = self._seed_clinic("Animal Care")
        clinica_b = self._seed_clinic("Bicho Feliz")

        with TestClient(self._app) as client:
            response = client.post(
                "/api/v1/portal/parceiros",
                json={
                    "tipo": PORTAL_PARTNER_TYPE_CLINICA,
                    "clinica_id": clinica_a,
                    "clinicas_vinculadas": [{"clinica_id": clinica_b}],
                },
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("somente ao veterinario parceiro", response.json()["detail"])

    def test_patch_substitui_o_conjunto_e_sem_o_campo_preserva(self) -> None:
        """CA-005."""
        clinica_a = self._seed_clinic("Animal Care")
        clinica_b = self._seed_clinic("Bicho Feliz")
        clinica_c = self._seed_clinic("Cao e Cia")

        with TestClient(self._app) as client:
            criado = client.post(
                "/api/v1/portal/parceiros",
                json=self._payload_veterinario(
                    clinicas_vinculadas=[
                        {"clinica_id": clinica_a, "receber_todos_laudos": True},
                        {"clinica_id": clinica_b},
                        {"clinica_id": clinica_c},
                    ]
                ),
            )
            self.assertEqual(criado.status_code, 201, criado.text)
            partner_id = criado.json()["id"]

            # Substitui: clinica_c sai, clinica_b liga a difusao, clinica_a desliga.
            substituido = client.patch(
                f"/api/v1/portal/parceiros/{partner_id}",
                json={
                    "clinicas_vinculadas": [
                        {"clinica_id": clinica_a, "receber_todos_laudos": False},
                        {"clinica_id": clinica_b, "receber_todos_laudos": True},
                    ]
                },
            )
            self.assertEqual(substituido.status_code, 200, substituido.text)
            self.assertEqual(
                {
                    item["clinica_id"]: item["receber_todos_laudos"]
                    for item in substituido.json()["clinicas_vinculadas"]
                },
                {clinica_a: False, clinica_b: True},
            )
            self.assertEqual(self._links_no_banco(partner_id), {clinica_a: False, clinica_b: True})

            # PATCH de outro campo nao mexe nos vinculos.
            sem_campo = client.patch(
                f"/api/v1/portal/parceiros/{partner_id}",
                json={"telefone": "85999990099"},
            )
            self.assertEqual(sem_campo.status_code, 200, sem_campo.text)
            self.assertEqual(self._links_no_banco(partner_id), {clinica_a: False, clinica_b: True})

    def test_opcoes_ordena_vinculados_da_clinica_primeiro(self) -> None:
        """CA-016."""
        clinica_a = self._seed_clinic("Animal Care")

        with TestClient(self._app) as client:
            # Nome comeca com "A" para provar que a ordem alfabetica cede lugar ao vinculo.
            sem_vinculo = client.post(
                "/api/v1/portal/parceiros",
                json=self._payload_veterinario(
                    nome_exibicao="Dr. Alberto Sem Vinculo",
                    email_login="alberto@vetparceiro.com",
                ),
            )
            self.assertEqual(sem_vinculo.status_code, 201, sem_vinculo.text)

            vinculado_sem_difusao = client.post(
                "/api/v1/portal/parceiros",
                json=self._payload_veterinario(
                    nome_exibicao="Dr. Zeca Vinculado",
                    email_login="zeca@vetparceiro.com",
                    clinicas_vinculadas=[{"clinica_id": clinica_a, "receber_todos_laudos": False}],
                ),
            )
            self.assertEqual(vinculado_sem_difusao.status_code, 201, vinculado_sem_difusao.text)

            vinculado_com_difusao = client.post(
                "/api/v1/portal/parceiros",
                json=self._payload_veterinario(
                    nome_exibicao="Dra. Wanda Difusao",
                    email_login="wanda@vetparceiro.com",
                    clinicas_vinculadas=[{"clinica_id": clinica_a, "receber_todos_laudos": True}],
                ),
            )
            self.assertEqual(vinculado_com_difusao.status_code, 201, vinculado_com_difusao.text)

            sem_filtro = client.get("/api/v1/portal/parceiros/veterinarios/opcoes")
            self.assertEqual(sem_filtro.status_code, 200, sem_filtro.text)
            self.assertEqual(
                [item["nome_exibicao"] for item in sem_filtro.json()["items"]],
                ["Dr. Alberto Sem Vinculo", "Dr. Zeca Vinculado", "Dra. Wanda Difusao"],
            )

            com_filtro = client.get(
                "/api/v1/portal/parceiros/veterinarios/opcoes",
                params={"clinica_id": clinica_a},
            )

        self.assertEqual(com_filtro.status_code, 200, com_filtro.text)
        items = com_filtro.json()["items"]
        self.assertEqual(
            [item["nome_exibicao"] for item in items],
            ["Dra. Wanda Difusao", "Dr. Zeca Vinculado", "Dr. Alberto Sem Vinculo"],
        )
        # Ninguem sai da lista, e os vinculos viajam junto para a tela.
        self.assertEqual(items[0]["clinicas_vinculadas"][0]["clinica_nome"], "Animal Care")
        self.assertEqual(items[2]["clinicas_vinculadas"], [])

    def test_migracao_dos_vinculos_e_idempotente(self) -> None:
        """CA-017."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            migration = _load_migration()
            engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'migracao-86.db'}")
            with engine.begin() as connection:
                migration.upgrade(connection, "sqlite")
                migration.upgrade(connection, "sqlite")

            with engine.connect() as connection:
                inspector = inspect(connection)
                self.assertIn("portal_partner_clinic_links", inspector.get_table_names())
                colunas = {column["name"] for column in inspector.get_columns("portal_partner_clinic_links")}
                self.assertEqual(
                    colunas,
                    {"id", "partner_id", "clinica_id", "receber_todos_laudos", "created_at", "updated_at"},
                )
                indices = {index["name"] for index in inspector.get_indexes("portal_partner_clinic_links")}
                self.assertIn("uq_portal_partner_clinic_link", indices)

                connection.execute(
                    text(
                        "INSERT INTO portal_partner_clinic_links (partner_id, clinica_id, receber_todos_laudos) "
                        "VALUES (1, 2, 1)"
                    )
                )
                with self.assertRaises(Exception):
                    connection.execute(
                        text(
                            "INSERT INTO portal_partner_clinic_links "
                            "(partner_id, clinica_id, receber_todos_laudos) VALUES (1, 2, 0)"
                        )
                    )
            engine.dispose()
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
