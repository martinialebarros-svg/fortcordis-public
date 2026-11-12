import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "data-resultado-timezone-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento


class DataResultadoTimezoneTest(unittest.TestCase):
    def test_to_local_naive_shifts_utc_to_local_wall_clock(self) -> None:
        utc_value = datetime(2026, 8, 11, 15, 0, 0, tzinfo=timezone.utc)
        result = atendimento._to_local_naive(utc_value)
        self.assertIsNone(result.tzinfo)
        self.assertEqual(result, datetime(2026, 8, 11, 12, 0, 0))

    def test_to_local_naive_leaves_naive_datetime_untouched(self) -> None:
        naive_value = datetime(2026, 8, 11, 12, 0, 0)
        result = atendimento._to_local_naive(naive_value)
        self.assertEqual(result, naive_value)

    def test_to_local_naive_handles_none(self) -> None:
        self.assertIsNone(atendimento._to_local_naive(None))

    def test_client_supplied_iso_z_normalizes_to_naive_local_wall_clock(self) -> None:
        payload_value = "2026-08-11T15:00:00.000Z"
        parsed = atendimento._to_local_naive(atendimento._parse_datetime(payload_value))

        self.assertIsNone(parsed.tzinfo)
        # Must land on the same naive local timeline as datetime.now() fallbacks
        # (UTC-3 for this deployment), not the raw UTC clock time.
        self.assertEqual(parsed, datetime(2026, 8, 11, 12, 0, 0))


if __name__ == "__main__":
    unittest.main()
