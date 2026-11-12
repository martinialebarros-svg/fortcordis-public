import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "eco-study-jobs-test-secret-key-1234567890")

from app.services.eco_study_extraction_service import ECO_STUDY_EXTRACTOR_VERSION  # noqa: E402
from app.services.eco_study_import_jobs import (  # noqa: E402
    _get_cached_job,
    _result_uses_current_extractor,
    serialize_eco_study_import_job,
)


class EcoStudyImportJobsTest(unittest.TestCase):
    @staticmethod
    def _database_with_jobs(jobs):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = jobs
        return db

    def test_only_reuses_results_from_current_extractor_version(self) -> None:
        current = (
            '{"meta_importacao_estudo":{"versao_extrator":"'
            + ECO_STUDY_EXTRACTOR_VERSION
            + '"}}'
        )

        self.assertTrue(_result_uses_current_extractor(current))
        self.assertFalse(_result_uses_current_extractor('{"meta_importacao_estudo":{}}'))
        self.assertFalse(
            _result_uses_current_extractor(
                '{"meta_importacao_estudo":{"versao_extrator":"anterior"}}'
            )
        )

    def test_does_not_return_completed_job_from_previous_extractor(self) -> None:
        legacy = SimpleNamespace(
            status="completed",
            resultado_json='{"medidas":{"IT_Vmax":null}}',
        )

        cached = _get_cached_job(
            self._database_with_jobs([legacy]),
            requested_by_id=7,
            content_hash="same-pdf",
        )

        self.assertIsNone(cached)

    def test_returns_completed_job_from_current_extractor(self) -> None:
        current = SimpleNamespace(
            status="completed",
            resultado_json=(
                '{"meta_importacao_estudo":{"versao_extrator":"'
                + ECO_STUDY_EXTRACTOR_VERSION
                + '"}}'
            ),
        )

        cached = _get_cached_job(
            self._database_with_jobs([current]),
            requested_by_id=7,
            content_hash="same-pdf",
        )

        self.assertIs(cached, current)

    def test_serializes_completed_result(self) -> None:
        job = SimpleNamespace(
            id=42,
            status="completed",
            arquivo_nome="estudo.pdf",
            erro=None,
            resultado_json='{"medidas":{"DIVEd":32.4}}',
            created_at=None,
            started_at=None,
            finished_at=None,
        )

        payload = serialize_eco_study_import_job(job)

        self.assertEqual(payload["job_id"], 42)
        self.assertEqual(payload["dados"]["medidas"]["DIVEd"], 32.4)


if __name__ == "__main__":
    unittest.main()
