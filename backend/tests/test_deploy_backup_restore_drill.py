import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_DIR / "scripts" / "deploy_backup_restore_drill.py"
SPEC = importlib.util.spec_from_file_location("deploy_backup_restore_drill", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar script drill: {SCRIPT_PATH}")
DRILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRILL)


class DeployBackupRestoreDrillTest(unittest.TestCase):
    def test_default_runtime_paths_include_structured_phrase_store(self) -> None:
        self.assertIn(
            "backend/data/frases_ecocardiograma_estruturado_teste.json",
            DRILL.DEFAULT_RUNTIME_PATHS,
        )
        self.assertIn(
            "backend/data/frases_ultrassom_abdominal.json",
            DRILL.DEFAULT_RUNTIME_PATHS,
        )

    def test_manifest_roundtrip_hash_validation(self) -> None:
        with tempfile.TemporaryDirectory() as app_dir:
            file_path = Path(app_dir) / "backend" / "data" / "frases.json"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text('{"ok": true}\n', encoding="utf-8")

            runtime_files = DRILL._collect_runtime_files(app_dir, ["backend/data/frases.json"])
            manifest = DRILL._build_manifest(runtime_files)

            with tempfile.TemporaryDirectory() as work_dir:
                archive_path = Path(work_dir) / "snapshot.tar.gz"
                restore_dir = Path(work_dir) / "restore"
                restore_dir.mkdir(parents=True, exist_ok=True)

                DRILL._archive_snapshot(runtime_files, str(archive_path))
                DRILL._extract_archive(str(archive_path), str(restore_dir))
                errors = DRILL._verify_restored_files(str(restore_dir), manifest)
                self.assertEqual(errors, [])

    def test_default_stamp_includes_app_slug(self) -> None:
        prod_stamp = DRILL._build_default_stamp("/var/www/fortcordis-v2")
        stage_stamp = DRILL._build_default_stamp("/var/www/fortcordis-stage")

        self.assertIn("fortcordis-v2", prod_stamp)
        self.assertIn("fortcordis-stage", stage_stamp)
        self.assertNotEqual(prod_stamp, stage_stamp)

    def test_verify_restored_files_detects_hash_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as app_dir:
            source_file = Path(app_dir) / "backend" / "data" / "patologias.json"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text('{"v": 1}\n', encoding="utf-8")

            runtime_files = DRILL._collect_runtime_files(app_dir, ["backend/data/patologias.json"])
            manifest = DRILL._build_manifest(runtime_files)

            with tempfile.TemporaryDirectory() as restore_dir:
                restored_file = Path(restore_dir) / "backend" / "data" / "patologias.json"
                restored_file.parent.mkdir(parents=True, exist_ok=True)
                restored_file.write_text('{"v": 2}\n', encoding="utf-8")
                errors = DRILL._verify_restored_files(restore_dir, manifest)
                self.assertTrue(any("Hash divergente" in item for item in errors))

    def test_collect_runtime_files_fails_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as app_dir:
            with self.assertRaises(RuntimeError) as ctx:
                DRILL._collect_runtime_files(app_dir, ["backend/fortcordis.db"])
            self.assertIn("ausentes", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
