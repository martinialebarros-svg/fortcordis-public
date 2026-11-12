import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import ai_echo_stage_canary


class AIEchoStageCanaryTest(unittest.TestCase):
    def test_synthetic_audio_fixture_is_small_m4a(self) -> None:
        fixture = REPO_ROOT / "backend" / "evals" / "ai_echo_canary_pt_br.m4a"
        payload = fixture.read_bytes()
        self.assertGreater(len(payload), 1024)
        self.assertLess(len(payload), 1024 * 1024)
        self.assertEqual(payload[4:8], b"ftyp")

    def test_multipart_contains_only_artificial_audio_fixture(self) -> None:
        payload = b"artificial-audio"
        body, content_type = ai_echo_stage_canary._multipart_audio(payload)
        self.assertIn(payload, body)
        self.assertIn(b'ai-echo-canary.m4a', body)
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))

    def test_remaining_normal_regression_has_no_personal_identifiers(self) -> None:
        transcript = ai_echo_stage_canary.REMAINING_NORMAL_REGRESSION_TRANSCRIPT
        self.assertIn("regurgitação leve", transcript)
        self.assertIn("Demais parâmetros", transcript)
        self.assertIn("classificado como B1", transcript)
        self.assertNotIn("Disfunção diastólica", transcript)
        self.assertNotIn("@", transcript)
        self.assertNotRegex(transcript, r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
        self.assertNotRegex(transcript, r"\b\d{4,5}-?\d{4}\b")

    def test_advanced_stage_c_transcript_has_no_personal_identifiers(self) -> None:
        transcript = ai_echo_stage_canary.ADVANCED_MITRAL_STAGE_C_TRANSCRIPT
        self.assertIn("Endocardiose mitral estágio C", transcript)
        self.assertIn("dois vírgula cinco", transcript)
        self.assertIn("congestão venosa pulmonar", transcript)
        self.assertNotIn("@", transcript)
        self.assertNotRegex(transcript, r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")


if __name__ == "__main__":
    unittest.main()
