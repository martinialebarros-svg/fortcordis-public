import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault(
    "SECRET_KEY",
    "image-header-import-test-secret-key-1234567890",
)

from app.services.image_header_import_service import (  # noqa: E402
    MAX_IMAGE_HEADER_IMPORT_SIZE,
    parse_image_header_import_content,
    parse_image_header_text,
)
from app.services.tesseract_runtime import resolve_tesseract_command  # noqa: E402


def _build_png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


class ImageHeaderImportServiceTest(unittest.TestCase):
    def test_resolves_system_tesseract_when_service_path_is_restricted(self) -> None:
        def is_file(path: str) -> bool:
            return path == "/usr/bin/tesseract"

        with patch.dict(
            os.environ,
            {
                "PATH": "/opt/fortcordis/backend/venv/bin",
                "TESSERACT_CMD": "tesseract",
            },
        ):
            with patch("app.services.tesseract_runtime.shutil.which", return_value=None):
                with patch("app.services.tesseract_runtime.os.path.isfile", side_effect=is_file):
                    with patch("app.services.tesseract_runtime.os.access", return_value=True):
                        command = resolve_tesseract_command()

        self.assertEqual(command, "/usr/bin/tesseract")

    def test_parse_image_header_text_extracts_expected_fields(self) -> None:
        text = """
        Ultrassonografia
        Radiosonar Diagnostico
        Informacao paciente
        Nome: APOLLO
        ID do paciente: FRANCISCO
        Genero: Femea
        Data do exame: 27-03-2026
        Owner: MARIA
        Idade: 6a
        Species: Canina
        Breed: Shih Tzu
        Medida
        """

        payload = parse_image_header_text(text)

        self.assertEqual(payload["paciente"]["nome"], "APOLLO")
        self.assertEqual(payload["paciente"]["tutor"], "MARIA")
        self.assertEqual(payload["paciente"]["especie"], "Canina")
        self.assertEqual(payload["paciente"]["raca"], "Shih Tzu")
        self.assertEqual(payload["paciente"]["sexo"], "Femea")
        self.assertEqual(payload["paciente"]["idade"], "6 anos")
        self.assertEqual(payload["paciente"]["data_exame"], "2026-03-27")
        self.assertEqual(payload["clinica"], "Radiosonar Diagnostico")

    def test_parse_image_header_text_falls_back_to_patient_id_for_tutor(self) -> None:
        text = """
        Informacao paciente
        Nome: APOLLO
        ID do paciente: FRANCISCO
        Owner:
        Species: Canina
        """

        payload = parse_image_header_text(text)
        self.assertEqual(payload["paciente"]["nome"], "APOLLO")
        self.assertEqual(payload["paciente"]["tutor"], "FRANCISCO")

    def test_parse_image_header_import_content_requires_image_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "Arquivo deve ser uma imagem"):
            parse_image_header_import_content("cabecalho.txt", b"conteudo")

    def test_parse_image_header_import_content_enforces_size_limit(self) -> None:
        oversized = b"a" * (MAX_IMAGE_HEADER_IMPORT_SIZE + 1)
        with self.assertRaisesRegex(ValueError, "Imagem excede o limite de 15MB"):
            parse_image_header_import_content("cabecalho.png", oversized)

    @patch("app.services.image_header_import_service._extract_text_with_tesseract")
    @patch("app.services.image_header_import_service._build_image_variants")
    def test_parse_image_header_import_content_uses_best_ocr_variant(
        self,
        build_variants_mock,
        extract_text_mock,
    ) -> None:
        sample_image = Image.new("RGB", (80, 80), color="white")
        build_variants_mock.return_value = [
            ("variant_a", sample_image),
            ("variant_b", sample_image),
        ]
        extract_text_mock.side_effect = [
            "Informacao paciente\nNome: \nSpecies: N/A\n",
            "Informacao paciente\nNome: APOLLO\nOwner: MARIA\nData do exame: 27/03/2026\n",
        ]

        payload = parse_image_header_import_content("cabecalho.png", _build_png_bytes())

        self.assertEqual(payload["paciente"]["nome"], "APOLLO")
        self.assertEqual(payload["paciente"]["tutor"], "MARIA")
        self.assertEqual(payload["paciente"]["data_exame"], "2026-03-27")
        self.assertEqual(payload["meta_importacao_imagem"]["variant"], "variant_b")


if __name__ == "__main__":
    unittest.main()
