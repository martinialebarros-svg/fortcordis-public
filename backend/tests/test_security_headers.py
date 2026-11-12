import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.core.security_headers import API_CSP_POLICY, build_security_headers


class SecurityHeadersTest(unittest.TestCase):
    def test_always_sets_frame_and_nosniff_headers(self) -> None:
        headers = build_security_headers("/")

        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_sets_csp_for_api_paths(self) -> None:
        headers = build_security_headers("/api/v1/agenda")

        self.assertEqual(headers.get("Content-Security-Policy"), API_CSP_POLICY)

    def test_sets_csp_for_health_endpoints(self) -> None:
        for path in ("/health", "/ready"):
            headers = build_security_headers(path)
            self.assertEqual(headers.get("Content-Security-Policy"), API_CSP_POLICY)

    def test_does_not_set_csp_for_non_api_paths(self) -> None:
        headers = build_security_headers("/docs")

        self.assertNotIn("Content-Security-Policy", headers)


if __name__ == "__main__":
    unittest.main()
