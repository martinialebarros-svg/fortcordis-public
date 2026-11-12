import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "attachment-is-verified-pdf-test-secret-key-1234567890")

from app.services import attachment_download_service as service


def _fake_attachment(*, caminho_arquivo=None, url=None, mime_type="application/pdf"):
    return SimpleNamespace(caminho_arquivo=caminho_arquivo, url=url, mime_type=mime_type)


class AttachmentIsVerifiedPdfTest(unittest.TestCase):
    def test_arquivo_local_com_bytes_magicos_de_pdf_e_verificado(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            caminho = Path(tmpdir) / "resultado.pdf"
            caminho.write_bytes(b"%PDF-1.7\n%conteudo qualquer")
            attachment = _fake_attachment(caminho_arquivo=str(caminho))
            self.assertTrue(service.attachment_is_verified_pdf(attachment))

    def test_arquivo_local_sem_bytes_magicos_e_rejeitado(self) -> None:
        # mime_type informado como PDF, mas o conteudo real e outra coisa
        # (ex.: renomeado de .txt para .pdf, ou upload corrompido).
        with tempfile.TemporaryDirectory() as tmpdir:
            caminho = Path(tmpdir) / "nao-e-pdf.pdf"
            caminho.write_bytes(b"isto e so um texto qualquer, nao um pdf de verdade")
            attachment = _fake_attachment(caminho_arquivo=str(caminho))
            self.assertFalse(service.attachment_is_verified_pdf(attachment))

    def test_arquivo_local_inexistente_e_rejeitado(self) -> None:
        attachment = _fake_attachment(caminho_arquivo="/caminho/que/nao/existe.pdf")
        self.assertFalse(service.attachment_is_verified_pdf(attachment))

    def test_url_remota_com_conteudo_pdf_e_verificada(self) -> None:
        attachment = _fake_attachment(url="https://storage.example.com/laudo.pdf")
        fake_response = MagicMock()
        fake_response.is_redirect = False
        fake_response.status_code = 206
        fake_response.iter_bytes.return_value = iter([b"%PDF-1.4\nresto do conteudo"])

        fake_client = MagicMock()
        fake_client.build_request.return_value = SimpleNamespace()
        fake_client.send.return_value = fake_response

        with patch.object(service, "_hostname_resolves_to_public_address", return_value=True):
            with patch.object(service.httpx, "Client", return_value=fake_client):
                self.assertTrue(service.attachment_is_verified_pdf(attachment))

    def test_url_remota_com_conteudo_nao_pdf_e_rejeitada(self) -> None:
        attachment = _fake_attachment(url="https://storage.example.com/nao-e-pdf")
        fake_response = MagicMock()
        fake_response.is_redirect = False
        fake_response.status_code = 200
        fake_response.iter_bytes.return_value = iter([b"<html>nao e um pdf</html>"])

        fake_client = MagicMock()
        fake_client.build_request.return_value = SimpleNamespace()
        fake_client.send.return_value = fake_response

        with patch.object(service, "_hostname_resolves_to_public_address", return_value=True):
            with patch.object(service.httpx, "Client", return_value=fake_client):
                self.assertFalse(service.attachment_is_verified_pdf(attachment))

    def test_url_remota_com_redirect_e_rejeitada(self) -> None:
        attachment = _fake_attachment(url="https://storage.example.com/laudo.pdf")
        fake_response = MagicMock()
        fake_response.is_redirect = True
        fake_response.status_code = 302

        fake_client = MagicMock()
        fake_client.build_request.return_value = SimpleNamespace()
        fake_client.send.return_value = fake_response

        with patch.object(service, "_hostname_resolves_to_public_address", return_value=True):
            with patch.object(service.httpx, "Client", return_value=fake_client):
                self.assertFalse(service.attachment_is_verified_pdf(attachment))

    def test_url_remota_com_falha_de_rede_e_rejeitada(self) -> None:
        import httpx

        attachment = _fake_attachment(url="https://storage.example.com/laudo.pdf")
        fake_client = MagicMock()
        fake_client.build_request.return_value = SimpleNamespace()
        fake_client.send.side_effect = httpx.ConnectError("falha de rede")

        with patch.object(service, "_hostname_resolves_to_public_address", return_value=True):
            with patch.object(service.httpx, "Client", return_value=fake_client):
                self.assertFalse(service.attachment_is_verified_pdf(attachment))


if __name__ == "__main__":
    unittest.main()
