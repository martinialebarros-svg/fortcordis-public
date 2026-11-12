import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "attachment-download-service-ssrf-test-secret-key-1234567890")

from app.services import attachment_download_service as service


class AttachmentDownloadServiceSsrfTest(unittest.TestCase):
    def test_is_public_address_rejeita_faixas_privadas_e_especiais(self) -> None:
        enderecos_bloqueados = [
            "169.254.169.254",  # metadata cloud (AWS/GCP/Azure)
            "127.0.0.1",
            "10.0.0.5",
            "172.16.0.1",
            "192.168.1.1",
            "::1",
            "0.0.0.0",
            "224.0.0.1",  # multicast
            "100.64.0.1",  # CGNAT (RFC 6598) - inicio da faixa
            "100.100.100.200",  # CGNAT - equivalente ao metadata da Alibaba Cloud
            "100.127.255.255",  # CGNAT - fim da faixa
        ]
        for endereco in enderecos_bloqueados:
            with self.subTest(endereco=endereco):
                self.assertFalse(service._is_public_address(endereco))

    def test_is_public_address_aceita_enderecos_publicos(self) -> None:
        for endereco in ("8.8.8.8", "1.1.1.1", "93.184.216.34"):
            with self.subTest(endereco=endereco):
                self.assertTrue(service._is_public_address(endereco))

    def test_hostname_resolves_to_public_address_respeita_timeout(self) -> None:
        def _getaddrinfo_lento(*_args, **_kwargs):
            import time

            time.sleep(5)
            return [(2, 1, 6, "", ("8.8.8.8", 0))]

        with patch.object(service.socket, "getaddrinfo", side_effect=_getaddrinfo_lento):
            with patch.object(service, "DNS_RESOLUTION_TIMEOUT_SECONDS", 0.2):
                import time

                inicio = time.monotonic()
                resultado = service._hostname_resolves_to_public_address("host-lento.exemplo")
                duracao = time.monotonic() - inicio

        self.assertFalse(resultado)
        self.assertLess(duracao, 1.0, "a resolucao deveria respeitar o timeout curto, nao os 5s do getaddrinfo")

    def test_normalize_remote_url_rejeita_ip_privado_literal(self) -> None:
        self.assertIsNone(service._normalize_remote_url("http://169.254.169.254/latest/meta-data/"))
        self.assertIsNone(service._normalize_remote_url("http://127.0.0.1:8000/x"))
        self.assertIsNone(service._normalize_remote_url("http://10.0.0.5/x"))

    def test_normalize_remote_url_rejeita_scheme_invalido(self) -> None:
        self.assertIsNone(service._normalize_remote_url("ftp://example.com/x"))
        self.assertIsNone(service._normalize_remote_url("file:///etc/passwd"))
        self.assertIsNone(service._normalize_remote_url(""))
        self.assertIsNone(service._normalize_remote_url(None))

    def test_normalize_remote_url_aceita_host_publico(self) -> None:
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            self.assertEqual(
                service._normalize_remote_url("https://example.com/arquivo.pdf"),
                "https://example.com/arquivo.pdf",
            )

    def test_normalize_remote_url_rejeita_hostname_que_resolve_para_ip_privado(self) -> None:
        # DNS rebinding: hostname aparenta ser externo, mas resolve para uma
        # faixa privada/interna - deve ser bloqueado mesmo sem IP literal na URL.
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 0))]):
            self.assertIsNone(service._normalize_remote_url("https://attacker.example/x"))

    def test_normalize_remote_url_rejeita_hostname_nao_resolvivel(self) -> None:
        import socket

        with patch("socket.getaddrinfo", side_effect=socket.gaierror):
            self.assertIsNone(service._normalize_remote_url("https://host-inexistente.invalid/x"))

    def test_build_remote_headers_nao_envia_token_para_host_nao_confiavel(self) -> None:
        with patch.object(service.settings, "PORTAL_REMOTE_STORAGE_AUTH_TOKEN", "segredo-123"):
            with patch.object(service.settings, "PORTAL_REMOTE_STORAGE_TRUSTED_HOSTS", "storage.fortcordis.com.br"):
                headers = service._build_remote_headers("https://attacker.example/collect")
                self.assertEqual(headers, {})

    def test_build_remote_headers_envia_token_para_host_confiavel(self) -> None:
        with patch.object(service.settings, "PORTAL_REMOTE_STORAGE_AUTH_TOKEN", "segredo-123"):
            with patch.object(service.settings, "PORTAL_REMOTE_STORAGE_TRUSTED_HOSTS", "storage.fortcordis.com.br"):
                headers = service._build_remote_headers("https://storage.fortcordis.com.br/arquivo.pdf")
                self.assertIn("Authorization", headers)
                self.assertEqual(headers["Authorization"], "Bearer segredo-123")

    def test_build_remote_headers_sem_allowlist_configurada_nunca_envia_token(self) -> None:
        with patch.object(service.settings, "PORTAL_REMOTE_STORAGE_AUTH_TOKEN", "segredo-123"):
            with patch.object(service.settings, "PORTAL_REMOTE_STORAGE_TRUSTED_HOSTS", ""):
                headers = service._build_remote_headers("https://qualquer-coisa.example/x")
                self.assertEqual(headers, {})


if __name__ == "__main__":
    unittest.main()
