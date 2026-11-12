import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_DIR / "scripts" / "ci" / "check_sdd_guardrail.py"
SPEC = importlib.util.spec_from_file_location("check_sdd_guardrail", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar guardrail SDD: {SCRIPT_PATH}")
SDD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SDD
SPEC.loader.exec_module(SDD)


class SddGuardrailTest(unittest.TestCase):
    def _create_feature_dir(self, repo_root: Path, slug: str, files: list[str]) -> None:
        feature_dir = repo_root / "docs" / "specs" / slug
        feature_dir.mkdir(parents=True, exist_ok=True)
        for file_name in files:
            (feature_dir / file_name).write_text("# test\n", encoding="utf-8")

    def test_passes_when_no_code_files_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            result = SDD.evaluate_guardrail(
                ["docs/specs/feature-x/spec.md"],
                str(repo_root),
            )
            self.assertTrue(result.passed)
            self.assertEqual(result.code_files, [])

    def test_fails_when_code_changes_without_sdd_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            result = SDD.evaluate_guardrail(
                ["backend/app/main.py"],
                str(repo_root),
            )
            self.assertFalse(result.passed)
            self.assertIn("nenhum artefato SDD".lower(), " ".join(result.messages).lower())

    def test_passes_with_spec_and_verify_changed_in_valid_feature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._create_feature_dir(
                repo_root,
                "feature-y",
                ["intent.md", "spec.md", "plan.md", "verify.md"],
            )
            changed = [
                "backend/app/main.py",
                "docs/specs/feature-y/spec.md",
                "docs/specs/feature-y/verify.md",
            ]
            result = SDD.evaluate_guardrail(changed, str(repo_root))
            self.assertTrue(result.passed)
            self.assertIn("feature-y", result.qualified_features)

    def test_fails_when_feature_structure_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._create_feature_dir(
                repo_root,
                "feature-z",
                ["intent.md", "spec.md", "plan.md"],
            )
            changed = [
                "frontend/app/page.tsx",
                "docs/specs/feature-z/spec.md",
                "docs/specs/feature-z/verify.md",
            ]
            result = SDD.evaluate_guardrail(changed, str(repo_root))
            self.assertFalse(result.passed)
            joined = " ".join(result.messages).lower()
            self.assertIn("estrutura obrigatoria", joined)

    def test_fails_when_only_plan_changed_for_code_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._create_feature_dir(
                repo_root,
                "feature-plan-only",
                ["intent.md", "spec.md", "plan.md", "verify.md"],
            )
            changed = [
                "scripts/deploy_prod_vps.sh",
                "docs/specs/feature-plan-only/plan.md",
            ]
            result = SDD.evaluate_guardrail(changed, str(repo_root))
            self.assertFalse(result.passed)
            self.assertEqual(result.qualified_features, [])


if __name__ == "__main__":
    unittest.main()
