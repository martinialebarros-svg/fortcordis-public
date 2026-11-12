import os
import shutil
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "eco-study-ocr-runtime-test-secret-key-1234567890")

from app.core import runtime_checks  # noqa: E402
from scripts.verify_eco_study_ocr import (  # noqa: E402
    EXPECTED_MEASUREMENTS,
    build_scanned_pdf,
    build_synthetic_study_image,
)
from app.services.eco_study_extraction_service import parse_eco_study_import_content  # noqa: E402


class EcoStudyOcrRuntimeTest(unittest.TestCase):
    def test_runtime_check_reports_missing_binary(self) -> None:
        with patch.object(runtime_checks, "resolve_tesseract_command", return_value="tesseract"):
            with patch.object(runtime_checks.shutil, "which", return_value=None):
                payload = runtime_checks._check_eco_study_ocr()

        self.assertFalse(payload["available"])
        self.assertEqual(payload["missing_languages"], ["por", "eng"])

    def test_runtime_check_reports_version_and_languages(self) -> None:
        responses = [
            SimpleNamespace(returncode=0, stdout="tesseract 5.5.2\n"),
            SimpleNamespace(returncode=0, stdout="List of available languages in tessdata/:\neng\npor\n"),
        ]
        with patch.object(
            runtime_checks,
            "resolve_tesseract_command",
            return_value="/usr/bin/tesseract",
        ):
            with patch.object(runtime_checks.subprocess, "run", side_effect=responses):
                payload = runtime_checks._check_eco_study_ocr()

        self.assertTrue(payload["available"])
        self.assertEqual(payload["version"], "tesseract 5.5.2")
        self.assertEqual(payload["missing_languages"], [])

    @unittest.skipUnless(shutil.which("tesseract"), "Tesseract nao instalado")
    def test_real_ocr_extracts_synthetic_image_and_scanned_pdf(self) -> None:
        image_content = build_synthetic_study_image()
        image_payload = parse_eco_study_import_content("synthetic-ultrasound.png", image_content)
        pdf_payload = parse_eco_study_import_content(
            "synthetic-scanned.pdf",
            build_scanned_pdf(image_content),
        )

        self.assertEqual(image_payload["medidas"], EXPECTED_MEASUREMENTS)
        self.assertEqual(pdf_payload["medidas"], EXPECTED_MEASUREMENTS)


if __name__ == "__main__":
    unittest.main()
