import hashlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault(
    "SECRET_KEY",
    "xml-import-test-secret-key-1234567890",
)

from app.services.xml_import_jobs import (
    MAX_XML_IMPORT_SIZE,
    _compute_xml_content_hash,
    _get_cached_xml_import_job,
    decode_xml_import_base64,
    parse_xml_import_content,
    serialize_xml_import_job,
)
from app.models.xml_import_job import XmlImportJob


class XmlImportJobsTest(unittest.TestCase):
    def test_content_hash_is_stable_but_changes_with_parser_version(self) -> None:
        content = b"<root><parameter NAME='RVOT Vmax'><aver>0.8</aver></parameter></root>"
        current_hash = _compute_xml_content_hash(content)

        self.assertEqual(current_hash, _compute_xml_content_hash(content))
        self.assertNotEqual(current_hash, hashlib.sha256(content).hexdigest())
        with patch("app.services.xml_import_jobs.XML_IMPORT_PARSER_VERSION", "next"):
            self.assertNotEqual(current_hash, _compute_xml_content_hash(content))

    def test_legacy_cache_is_not_reused_and_current_cache_is_reused(self) -> None:
        content = b"<root><parameter NAME='RVOT Vmax'><aver>0.8</aver></parameter></root>"
        legacy_result = '{"medidas":{"Vmax_pulmonar":0.8}}'
        engine = create_engine("sqlite://")
        XmlImportJob.__table__.create(engine)
        try:
            with Session(engine) as db:
                legacy = XmlImportJob(
                    requested_by_id=7,
                    status="completed",
                    conteudo_hash=hashlib.sha256(content).hexdigest(),
                    resultado_json=legacy_result,
                )
                db.add(legacy)
                db.commit()
                current_hash = _compute_xml_content_hash(content)

                self.assertIsNone(_get_cached_xml_import_job(
                    db, requested_by_id=7, conteudo_hash=current_hash,
                ))

                current = XmlImportJob(
                    requested_by_id=7,
                    status="completed",
                    conteudo_hash=current_hash,
                    resultado_json='{"medidas":{"Vmax_VSVD":0.8}}',
                )
                db.add(current)
                db.commit()

                self.assertIs(_get_cached_xml_import_job(
                    db, requested_by_id=7, conteudo_hash=current_hash,
                ), current)
                self.assertEqual(legacy.resultado_json, legacy_result)
                self.assertEqual(legacy.conteudo_hash, hashlib.sha256(content).hexdigest())
        finally:
            engine.dispose()

    def test_parse_xml_import_content_requires_xml_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "Arquivo deve ser um XML"):
            parse_xml_import_content("exame.txt", b"<xml />")

    def test_parse_xml_import_content_enforces_size_limit(self) -> None:
        oversized = b"a" * (MAX_XML_IMPORT_SIZE + 1)
        with self.assertRaisesRegex(ValueError, "XML excede o limite de 5MB"):
            parse_xml_import_content("exame.xml", oversized)

    def test_decode_invalid_base64_raises_clean_message(self) -> None:
        with self.assertRaisesRegex(ValueError, "Conteudo base64 invalido"):
            decode_xml_import_base64("%%%")

    @patch("app.utils.xml_parser.parse_xml_eco", return_value={"paciente": {"nome": "Bob"}})
    def test_parse_xml_import_content_returns_parser_payload(self, parser_mock) -> None:
        result = parse_xml_import_content("exame.xml", b"<xml></xml>")

        self.assertEqual(result["paciente"]["nome"], "Bob")
        parser_mock.assert_called_once()

    def test_serialize_xml_import_job_includes_completed_payload(self) -> None:
        job = SimpleNamespace(
            id=12,
            status="completed",
            arquivo_nome="exame.xml",
            erro=None,
            resultado_json='{"paciente":{"nome":"Luna"}}',
            created_at=None,
            started_at=None,
            finished_at=None,
        )

        payload = serialize_xml_import_job(job)

        self.assertEqual(payload["job_id"], 12)
        self.assertEqual(payload["dados"]["paciente"]["nome"], "Luna")


if __name__ == "__main__":
    unittest.main()
