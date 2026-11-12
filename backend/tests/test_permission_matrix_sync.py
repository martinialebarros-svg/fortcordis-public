import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault(
    "SECRET_KEY",
    "permission-audit-test-secret-key-1234567890",
)

from app.api.v1.endpoints.admin import PERMISSION_MODULE_CODES, _sync_permission_matrix
from app.api.v1.endpoints.auth import verify_password
from app.core.config import Settings
from app.core.security import _resolve_module_from_path, _user_has_matrix_permission
from app.db.database import SessionLocal
from app.models.papel import Papel
from app.models.papel_permissao import PapelPermissao


class PermissionMatrixSyncTest(unittest.TestCase):
    def test_permission_matrix_fallback_defaults_to_false(self) -> None:
        previous = os.environ.pop("ALLOW_PERMISSION_MATRIX_FALLBACK", None)
        try:
            settings = Settings(
                _env_file=None,
                DATABASE_URL="sqlite:///./fortcordis.db",
                SECRET_KEY="permission-audit-test-secret-key-1234567890",
            )
        finally:
            if previous is not None:
                os.environ["ALLOW_PERMISSION_MATRIX_FALLBACK"] = previous

        self.assertFalse(settings.ALLOW_PERMISSION_MATRIX_FALLBACK)

    def test_legacy_plain_passwords_default_to_false(self) -> None:
        previous = os.environ.pop("ALLOW_LEGACY_PLAIN_PASSWORDS", None)
        try:
            settings = Settings(
                _env_file=None,
                DATABASE_URL="sqlite:///./fortcordis.db",
                SECRET_KEY="permission-audit-test-secret-key-1234567890",
            )
        finally:
            if previous is not None:
                os.environ["ALLOW_LEGACY_PLAIN_PASSWORDS"] = previous

        self.assertFalse(settings.ALLOW_LEGACY_PLAIN_PASSWORDS)

    def test_plain_text_password_is_rejected_even_with_legacy_flag_enabled(self) -> None:
        with patch("app.api.v1.endpoints.auth.settings.ALLOW_LEGACY_PLAIN_PASSWORDS", True):
            self.assertFalse(verify_password("senha123", "senha123"))

    def test_logistica_is_registered_as_permission_module(self) -> None:
        self.assertIn("logistica", PERMISSION_MODULE_CODES)

    def test_fiscal_and_relatorios_are_registered_as_permission_modules(self) -> None:
        self.assertIn("fiscal", PERMISSION_MODULE_CODES)
        self.assertIn("relatorios", PERMISSION_MODULE_CODES)

    def test_security_path_mapping_includes_fiscal_and_relatorios(self) -> None:
        self.assertEqual(_resolve_module_from_path("/api/v1/fiscal/notas-fiscais"), "fiscal")
        self.assertEqual(_resolve_module_from_path("/api/v1/relatorios/controle"), "relatorios")

    def test_logistica_requires_explicit_permission_when_module_row_is_missing(self) -> None:
        user = SimpleNamespace(papeis=[SimpleNamespace(id=2)])

        def fake_query(_db, _papel_ids, modulo):
            return []

        with patch("app.core.security._query_permission_rows", side_effect=fake_query):
            allowed = _user_has_matrix_permission(None, user, "logistica", "visualizar")

        self.assertFalse(allowed)

    def test_explicit_logistica_permission_is_respected(self) -> None:
        user = SimpleNamespace(papeis=[SimpleNamespace(id=2)])

        def fake_query(_db, _papel_ids, modulo):
            if modulo == "logistica":
                return [SimpleNamespace(visualizar=1, editar=0, excluir=0)]
            return []

        with patch("app.core.security._query_permission_rows", side_effect=fake_query):
            allowed = _user_has_matrix_permission(None, user, "logistica", "visualizar")

        self.assertTrue(allowed)

    def test_permission_matrix_sync_supports_safe_logistica_dry_run(self) -> None:
        db = SessionLocal()
        try:
            bind = db.get_bind()
            Papel.__table__.create(bind=bind, checkfirst=True)
            PapelPermissao.__table__.create(bind=bind, checkfirst=True)
            result = _sync_permission_matrix(
                db,
                modules={"logistica"},
                commit=False,
            )
        finally:
            db.close()

        self.assertFalse(result["commit_applied"])
        self.assertEqual(result["target_modules"], ["logistica"])


if __name__ == "__main__":
    unittest.main()
