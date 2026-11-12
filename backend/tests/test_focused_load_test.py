import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "focused_load_test.py"
SPEC = importlib.util.spec_from_file_location("focused_load_test", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar script: {SCRIPT_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FocusedLoadTestUtilsTest(unittest.TestCase):
    def test_percentile_empty_returns_none(self) -> None:
        self.assertIsNone(MODULE.percentile([], 0.95))

    def test_percentile_single_value_returns_same(self) -> None:
        self.assertEqual(MODULE.percentile([123.4], 0.95), 123.4)

    def test_percentile_interpolates_values(self) -> None:
        values = [100.0, 200.0, 300.0, 400.0]
        p50 = MODULE.percentile(values, 0.50)
        p95 = MODULE.percentile(values, 0.95)

        self.assertAlmostEqual(p50, 250.0, places=2)
        self.assertAlmostEqual(p95, 385.0, places=2)

    def test_normalize_base_url_removes_trailing_slash(self) -> None:
        self.assertEqual(MODULE.normalize_base_url("https://api.example.com/"), "https://api.example.com")
        self.assertEqual(MODULE.normalize_base_url("https://api.example.com"), "https://api.example.com")


if __name__ == "__main__":
    unittest.main()
