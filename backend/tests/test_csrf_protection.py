import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.core.csrf import (
    has_valid_csrf_token_pair,
    is_trusted_origin,
    should_protect_request,
)


class CsrfProtectionTest(unittest.TestCase):
    def test_mutating_request_with_session_cookie_requires_protection(self) -> None:
        self.assertTrue(should_protect_request("/api/v1/agenda", "POST", True))

    def test_safe_method_is_not_protected(self) -> None:
        self.assertFalse(should_protect_request("/api/v1/agenda", "GET", True))

    def test_login_path_is_exempt(self) -> None:
        self.assertFalse(should_protect_request("/api/v1/auth/login", "POST", True))

    def test_no_cookie_session_skips_csrf(self) -> None:
        self.assertFalse(should_protect_request("/api/v1/agenda", "POST", False))

    def test_token_pair_must_match(self) -> None:
        self.assertTrue(has_valid_csrf_token_pair("abc123", "abc123"))
        self.assertFalse(has_valid_csrf_token_pair("abc123", "abc124"))
        self.assertFalse(has_valid_csrf_token_pair("", "abc123"))

    def test_origin_is_trusted_when_in_allowlist(self) -> None:
        self.assertTrue(
            is_trusted_origin(
                origin="https://app.stage.fortcordis.com.br",
                referer=None,
                allowed_origins={"https://app.stage.fortcordis.com.br"},
                request_origin="http://127.0.0.1:8001",
            )
        )

    def test_referer_origin_is_trusted_when_origin_absent(self) -> None:
        self.assertTrue(
            is_trusted_origin(
                origin=None,
                referer="https://app.stage.fortcordis.com.br/agenda",
                allowed_origins={"https://app.stage.fortcordis.com.br"},
                request_origin="http://127.0.0.1:8001",
            )
        )

    def test_untrusted_origin_is_rejected(self) -> None:
        self.assertFalse(
            is_trusted_origin(
                origin="https://evil.example",
                referer=None,
                allowed_origins={"https://app.stage.fortcordis.com.br"},
                request_origin="https://app.stage.fortcordis.com.br",
            )
        )


if __name__ == "__main__":
    unittest.main()
