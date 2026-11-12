import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-upload-service-test-secret-key-1234567890")

from app.services import atendimento_upload_service


class AtendimentoUploadServiceTest(unittest.TestCase):
    def test_build_upload_dedupe_key_uses_none_scope_for_null_exam(self) -> None:
        key = atendimento_upload_service.build_upload_dedupe_key(None, "ABC123")
        self.assertEqual(key, "exame:none|sha256:abc123")

    def test_build_upload_dedupe_key_uses_exam_scope_when_exam_is_present(self) -> None:
        key = atendimento_upload_service.build_upload_dedupe_key(42, "ff00")
        self.assertEqual(key, "exame:42|sha256:ff00")

    def test_calculate_attachment_sha256_returns_stable_hex_digest(self) -> None:
        digest_a = atendimento_upload_service.calculate_attachment_sha256(b"conteudo")
        digest_b = atendimento_upload_service.calculate_attachment_sha256(b"conteudo")
        self.assertEqual(digest_a, digest_b)
        self.assertEqual(len(digest_a), 64)

    def test_calculate_attachment_sha256_differs_for_distinct_content(self) -> None:
        digest_a = atendimento_upload_service.calculate_attachment_sha256(b"arquivo-a")
        digest_b = atendimento_upload_service.calculate_attachment_sha256(b"arquivo-b")
        self.assertNotEqual(digest_a, digest_b)

    def test_validate_attachment_type_accepts_allowed_extension_and_mime(self) -> None:
        mime = atendimento_upload_service.validate_attachment_type("relatorio.PDF", "application/pdf")
        self.assertEqual(mime, "application/pdf")

    def test_validate_attachment_type_accepts_octet_stream_when_extension_is_allowed(self) -> None:
        mime = atendimento_upload_service.validate_attachment_type("imagem.JPG", "application/octet-stream")
        self.assertEqual(mime, "image/jpeg")

    def test_validate_attachment_type_rejects_disallowed_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tipo de arquivo nao permitido"):
            atendimento_upload_service.validate_attachment_type("script.exe", "application/octet-stream")

    def test_validate_attachment_type_rejects_disallowed_mime(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tipo MIME nao permitido"):
            atendimento_upload_service.validate_attachment_type("relatorio.pdf", "text/plain")

    def test_validate_attachment_type_rejects_mime_extension_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "Extensao do arquivo nao corresponde ao tipo MIME informado"):
            atendimento_upload_service.validate_attachment_type("imagem.png", "image/jpeg")

    def test_validate_attachment_size_rejects_file_above_limit(self) -> None:
        oversized = b"a" * (atendimento_upload_service.MAX_ATENDIMENTO_ATTACHMENT_SIZE + 1)
        with self.assertRaises(atendimento_upload_service.AttachmentTooLargeError):
            atendimento_upload_service.validate_attachment_size(oversized)

    def test_validate_attachment_size_accepts_exact_limit(self) -> None:
        exact_limit = b"a" * atendimento_upload_service.MAX_ATENDIMENTO_ATTACHMENT_SIZE
        atendimento_upload_service.validate_attachment_size(exact_limit)

    def test_store_attachment_persists_file_and_returns_normalized_mime(self) -> None:
        content = b"arquivo-de-teste"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                atendimento_upload_service,
                "get_atendimento_upload_storage_dir",
                return_value=tmpdir,
            ):
                path, normalized_name, mime = atendimento_upload_service.store_atendimento_attachment_file(
                    atendimento_id=123,
                    filename=" Relatorio de Exame .PDF ",
                    content=content,
                    content_type="application/pdf",
                )

            self.assertTrue(path.endswith(".PDF"))
            self.assertTrue(normalized_name.lower().endswith(".pdf"))
            self.assertEqual(mime, "application/pdf")
            self.assertEqual(Path(path).read_bytes(), content)

    def test_store_attachment_rejects_invalid_extension_before_storage(self) -> None:
        with patch.object(atendimento_upload_service, "get_atendimento_upload_storage_dir") as storage_dir_mock:
            with self.assertRaisesRegex(ValueError, "Tipo de arquivo nao permitido"):
                atendimento_upload_service.store_atendimento_attachment_file(
                    atendimento_id=1,
                    filename="malicioso.exe",
                    content=b"fake",
                    content_type="application/octet-stream",
                )

        storage_dir_mock.assert_not_called()

    def test_store_attachment_rejects_oversized_before_storage(self) -> None:
        oversized = b"a" * (atendimento_upload_service.MAX_ATENDIMENTO_ATTACHMENT_SIZE + 1)
        with patch.object(atendimento_upload_service, "get_atendimento_upload_storage_dir") as storage_dir_mock:
            with self.assertRaises(atendimento_upload_service.AttachmentTooLargeError):
                atendimento_upload_service.store_atendimento_attachment_file(
                    atendimento_id=1,
                    filename="grande.pdf",
                    content=oversized,
                    content_type="application/pdf",
                )

        storage_dir_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
