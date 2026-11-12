import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "endereco-fiscal-synthetic-test-key-1234567890")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api.v1.endpoints import clinicas
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.clinica import Clinica


class EnderecoFiscalApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Clinica.__table__.create(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        with self.Session() as db:
            db.add(Clinica(id=1, nome="Clínica sintética", cnpj="11.222.333/0001-81", ativo=True,
                           endereco="Rua Operacional", numero="5", complemento="Sala Operacional", bairro="Centro",
                           cep="60000000", cidade="Fortaleza", estado="CE", latitude=-3.75, longitude=-38.5,
                           place_id="pin-preservado", whatsapps=["85999999999"], tabela_preco_id=2))
            db.commit()
            self.before = {c.name: getattr(db.get(Clinica, 1), c.name) for c in Clinica.__table__.columns if c.name not in {"endereco_fiscal", "updated_at"}}
        def dependency_db():
            with self.Session() as db:
                yield db
        self.app = FastAPI()
        self.app.include_router(clinicas.router, prefix="/clinicas")
        self.app.dependency_overrides[get_db] = dependency_db
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        self.client = TestClient(self.app)
        self.payload = dict(cnpj="11.222.333/0001-81", endereco="Rua Fiscal", numero="500", complemento="",
                            bairro="Bairro Fiscal", cidade="Fortaleza", estado="ce", cep="60763-730",
                            fonte_url="https://example.test/cartao")

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_atualiza_somente_json_fiscal_sem_geocode_ou_aprendizado_cep(self):
        with patch.object(clinicas, "geocodificar_endereco_google") as maps, patch.object(clinicas, "_upsert_bairro_aprendizado") as bairro:
            response = self.client.put("/clinicas/1/endereco-fiscal", json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        maps.assert_not_called()
        bairro.assert_not_called()
        saved = response.json()["endereco_fiscal"]
        self.assertEqual(saved["cnpj"], "11222333000181")
        self.assertEqual(saved["cep"], "60763730")
        self.assertEqual(saved["estado"], "CE")
        self.assertEqual(saved["conferido_por"], 7)
        self.assertTrue(saved["conferido_em"])
        with self.Session() as db:
            row = db.get(Clinica, 1)
            self.assertEqual(self.before, {k: getattr(row, k) for k in self.before})
            self.assertEqual(row.endereco_fiscal, saved)
        self.assertEqual(self.client.get("/clinicas/1").json()["endereco_fiscal"], saved)

    def test_rejeita_cnpj_diferente_endereco_parcial_cep_uf_e_campos_operacionais(self):
        for changes in ({"cnpj": "12.345.678/0001-95"}, {"cep": "123"}, {"estado": "XX"}, {"endereco": " "}, {"latitude": -3}, {"fonte_url": "javascript:alert(1)"}):
            with self.subTest(changes=changes):
                response = self.client.put("/clinicas/1/endereco-fiscal", json={**self.payload, **changes})
                self.assertEqual(response.status_code, 422, response.text)
        with self.Session() as db:
            self.assertIsNone(db.get(Clinica, 1).endereco_fiscal)

    def test_exige_autenticacao(self):
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.put("/clinicas/1/endereco-fiscal", json=self.payload).status_code, 401)

    def test_clinica_inexistente(self):
        self.assertEqual(self.client.put("/clinicas/999/endereco-fiscal", json=self.payload).status_code, 404)

    def test_migracao_idempotente_preserva_endereco_e_pin(self):
        engine = create_engine("sqlite://")
        path = Path(__file__).parents[1] / "migrations/versions/20261025_100_clinica_endereco_fiscal.py"
        spec = importlib.util.spec_from_file_location("endereco_fiscal_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE clinicas (id INTEGER PRIMARY KEY, cep TEXT, latitude REAL, longitude REAL)"))
            connection.execute(text("INSERT INTO clinicas VALUES (1, '60000000', -3.75, -38.5)"))
            migration.upgrade(connection, "sqlite")
            migration.upgrade(connection, "sqlite")
            row = connection.execute(text("SELECT cep,latitude,longitude,endereco_fiscal FROM clinicas")).one()
            self.assertEqual(tuple(row), ("60000000", -3.75, -38.5, None))
        engine.dispose()
