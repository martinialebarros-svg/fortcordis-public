"""Safety checks for the one-shot operator; never connect to runtime services."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

_spec=importlib.util.spec_from_file_location('maps_cutover',Path(__file__).resolve().parents[2]/'scripts/activate_maps_monitor_production.py')
cutover=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(cutover)


class ProductionMapsCutoverTests(unittest.TestCase):
    def test_overlapping_sources_do_not_become_added_usage(self):
        usage=cutover.observed_baseline(7000,100,{'routes_essentials':400,'geocoding':30},{'routes_essentials':90,'geocoding':2})
        self.assertEqual(usage['month']['calls'],7030)
        self.assertEqual(usage['day']['calls'],102)
        self.assertEqual(usage['day']['estimated_brl'],'3.672')

    def test_older_google_observation_is_not_discarded_by_shorter_logs(self):
        usage=cutover.observed_baseline(6258,27,{'routes_essentials':413,'geocoding':5},{})
        self.assertEqual(usage['month']['calls'],6510)
        self.assertEqual(usage['day']['calls'],27)

    def test_newer_observation_is_counted_and_month_includes_day(self):
        usage=cutover.observed_baseline(7000,8000,{}, {})
        self.assertEqual(usage['month']['calls'],8000)
        self.assertEqual(usage['day']['calls'],8000)

    def test_atomic_environment_update_preserves_other_runtime_secrets_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('SECRET_KEY=do-not-print\nAPP_ENV=development\nexport APP_ENV=old\nAUTH_PROVIDER=supabase\n')
            path.chmod(0o600)
            cutover.upsert_env(path,{'APP_ENV':'production','GOOGLE_MAPS_COST_EMERGENCY_RELEASE':'false'})
            body=path.read_text()
            self.assertIn('SECRET_KEY=do-not-print\n',body)
            self.assertIn('AUTH_PROVIDER=supabase\n',body)
            self.assertEqual(body.count('APP_ENV='),1)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertFalse(list(Path(directory).glob('.maps-env-*')))
