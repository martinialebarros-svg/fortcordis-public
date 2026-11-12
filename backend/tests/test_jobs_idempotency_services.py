import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "jobs-idempotency-services-test-secret-key-1234567890")

from app.models.laudo_pdf_job import LaudoPdfJob
from app.models.xml_import_job import XmlImportJob
from app.services import laudo_pdf_jobs, xml_import_jobs


class JobsIdempotencyServicesTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "jobs-idempotency-services.db"
        engine = create_engine(f"sqlite:///{db_path}")
        LaudoPdfJob.__table__.create(engine, checkfirst=True)
        XmlImportJob.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def test_enqueue_laudo_pdf_job_is_idempotent_for_same_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    with patch.object(
                        laudo_pdf_jobs,
                        "compute_laudo_pdf_cache_key",
                        return_value="cache-key-1",
                    ):
                        with patch.object(laudo_pdf_jobs, "submit_laudo_pdf_job", return_value=None):
                            first = laudo_pdf_jobs.enqueue_laudo_pdf_job(
                                db,
                                laudo_id=77,
                                requested_by_id=9,
                            )
                            second = laudo_pdf_jobs.enqueue_laudo_pdf_job(
                                db,
                                laudo_id=77,
                                requested_by_id=9,
                            )

                    self.assertEqual(first["job_id"], second["job_id"])
                    total = db.query(LaudoPdfJob).count()
                    self.assertEqual(total, 1)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_enqueue_xml_import_job_is_idempotent_for_same_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    xml_bytes = b"<eco><paciente>Luna</paciente></eco>"
                    with patch.object(xml_import_jobs, "submit_xml_import_job", return_value=None):
                        with patch.object(
                            xml_import_jobs,
                            "_write_xml_file",
                            return_value="/tmp/xml_idempotente.xml",
                        ):
                            first = xml_import_jobs.enqueue_xml_import_job(
                                db,
                                requested_by_id=21,
                                filename="exame.xml",
                                xml_content=xml_bytes,
                            )
                            second = xml_import_jobs.enqueue_xml_import_job(
                                db,
                                requested_by_id=21,
                                filename="exame.xml",
                                xml_content=xml_bytes,
                            )

                    self.assertEqual(first["job_id"], second["job_id"])
                    jobs = db.query(XmlImportJob).all()
                    self.assertEqual(len(jobs), 1)
                    self.assertTrue(bool(jobs[0].conteudo_hash))
                finally:
                    db.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
