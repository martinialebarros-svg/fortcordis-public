import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "frases-eco-auth-test-secret-key-1234567890")

from app.api.v1.endpoints import frases_ecocardiograma_estruturado_teste as endpoint
from app.core.security import (
    _resolve_action_from_method,
    _resolve_module_from_path,
    get_current_user,
)


BASE_PATH = "/api/v1/frases-ecocardiograma-estruturado-teste"


class FrasesEcocardiogramaEstruturadoAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(endpoint.router, prefix=BASE_PATH)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.client.close()

    def test_todas_as_rotas_exigem_autenticacao(self) -> None:
        requests = [
            ("GET", "", None),
            ("POST", "/presets/1/aplicar", None),
            ("POST", "/presets", {}),
            ("PUT", "/presets/1", {}),
            ("DELETE", "/presets/1", None),
            ("POST", "/presets/1/restaurar", None),
            ("POST", "/presets/1/duplicar", {}),
            ("POST", "/frases", {}),
            ("PUT", "/frases/1", {}),
            ("DELETE", "/frases/1", {}),
            ("POST", "/frases/1/restaurar", {}),
            ("POST", "/frases/1/duplicar", {}),
        ]

        for method, suffix, payload in requests:
            with self.subTest(method=method, suffix=suffix):
                response = self.client.request(
                    method,
                    f"{BASE_PATH}{suffix}",
                    json=payload,
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Credenciais invalidas")

    def test_usuario_autenticado_consegue_carregar_payload(self) -> None:
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)

        with patch.object(endpoint.service, "get_payload", return_value={"version": "teste"}):
            response = self.client.get(BASE_PATH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"version": "teste"})

    def test_rota_usa_modulo_frases_e_acoes_da_matriz(self) -> None:
        self.assertEqual(_resolve_module_from_path(BASE_PATH), "frases")
        self.assertEqual(_resolve_action_from_method("GET"), "visualizar")
        self.assertEqual(_resolve_action_from_method("POST"), "editar")
        self.assertEqual(_resolve_action_from_method("PUT"), "editar")
        self.assertEqual(_resolve_action_from_method("DELETE"), "excluir")


if __name__ == "__main__":
    unittest.main()
