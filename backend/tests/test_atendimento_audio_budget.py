"""Synthetic wall-clock regressions for bounded audio preparation.

The fake decoder honors the supplied process timeout and writes a complete WAV
only when it finishes in time. No sleeps, external media or provider calls.
"""
import os
import socket
import subprocess
import unittest
import wave
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "synthetic-audio-budget-test-secret")

from app.services import atendimento_audio as audio
from app.services.atendimento_assistente import AssistenteError


def wav_bytes(samples):
    stream = BytesIO()
    with wave.open(stream, "wb") as recording:
        recording.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        recording.writeframes(samples)
    return stream.getvalue()


class AudioPreparationBudgetTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.now = 100.0
        self.decode_seconds = 1.0
        self.process_timeouts = []
        self.temporary_paths = []
        self.sent_samples = []
        self.sent_timeouts = []
        # Distinct PCM regions expose dropped, reordered or duplicated frames.
        self.samples = b"\x01\x00" * 16000 + b"\xff\x7f" * 16000 + b"\x02\x00" * 8000
        self.provider = Mock()
        self.provider.transcrever.side_effect = self.transcribe
        self.provider_factory = Mock(return_value=self.provider)
        stack.enter_context(patch.object(audio.time, "monotonic", side_effect=lambda: self.now))
        stack.enter_context(patch.object(audio.settings, "ATENDIMENTO_IA_TIMEOUT_SECONDS", 180))
        stack.enter_context(patch.object(audio, "get_ffmpeg_exe", return_value="synthetic-ffmpeg"))
        stack.enter_context(patch.object(audio.subprocess, "run", side_effect=self.decode))
        stack.enter_context(patch.object(socket, "socket", side_effect=AssertionError("Network forbidden in audio budget tests")))
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden in audio budget tests")))

    def decode(self, command, *, timeout, **_kwargs):
        target = Path(command[-1])
        self.temporary_paths.append(target.parent)
        self.process_timeouts.append(timeout)
        self.provider_factory.assert_not_called()
        self.now += min(self.decode_seconds, timeout)
        if self.decode_seconds > timeout:
            # A timed-out decoder may leave bytes; they must never reach IA.
            target.write_bytes(b"RIFF-partial-synthetic-output")
            raise subprocess.TimeoutExpired(command, timeout, stderr=b"private-source-path")
        target.write_bytes(wav_bytes(self.samples))
        return SimpleNamespace(returncode=0, stderr=b"")

    def transcribe(self, **kwargs):
        self.sent_timeouts.append(kwargs["timeout"])
        with wave.open(BytesIO(kwargs["content"]), "rb") as recording:
            self.assertEqual(recording.getparams()[:3], (1, 2, 16000))
            self.sent_samples.append(recording.readframes(recording.getnframes()))
        return {"texto": f"Parte {len(self.sent_samples)}", "modelo": "mock", "avisos": []}

    def run_transcription(self):
        return audio.transcrever_gravacao(
            nome="synthetic.wav", mime="audio/wav", content=wav_bytes(self.samples),
            paciente_nome="Paciente Sintético", provider_factory=self.provider_factory,
        )

    def assert_temporary_files_removed(self):
        self.assertTrue(self.temporary_paths)
        self.assertTrue(all(not path.exists() for path in self.temporary_paths))

    def test_preparation_over_25_seconds_keeps_all_frames_and_remaining_budget(self):
        self.decode_seconds = 30.0
        with patch.object(audio, "CHUNK_MAX_SECONDS", 1):
            result = self.run_transcription()
        self.assertEqual(self.process_timeouts, [60])
        self.assertEqual(len(self.sent_samples), 3)
        self.assertEqual(b"".join(self.sent_samples), self.samples)
        self.assertTrue(all(len(part) <= 16000 * 2 for part in self.sent_samples))
        self.assertEqual(self.sent_timeouts, [150.0] * 3)
        self.assertEqual(result["texto"], "Parte 1\n\nParte 2\n\nParte 3")
        self.assert_temporary_files_removed()

    def test_lower_configured_budget_bounds_preparation_and_provider(self):
        self.decode_seconds = 4.0
        with patch.object(audio.settings, "ATENDIMENTO_IA_TIMEOUT_SECONDS", 12):
            result = self.run_transcription()
        self.assertEqual(self.process_timeouts, [12])
        self.assertEqual(self.sent_timeouts, [8.0])
        self.assertEqual(b"".join(self.sent_samples), self.samples)
        self.assertEqual(result["texto"], "Parte 1")
        self.assert_temporary_files_removed()

    def test_decoder_timeout_removes_partial_output_without_provider_call(self):
        self.decode_seconds = 61.0
        with self.assertRaises(AssistenteError) as raised:
            self.run_transcription()
        self.assertEqual(raised.exception.status_code, 504)
        self.assertIn("preparo do áudio demorou", str(raised.exception))
        self.assertNotIn("private-source-path", str(raised.exception))
        self.provider_factory.assert_not_called()
        self.provider.transcrever.assert_not_called()
        self.assert_temporary_files_removed()

    def test_budget_exhausted_by_preparation_sends_no_audio(self):
        self.decode_seconds = 10.0
        with patch.object(audio.settings, "ATENDIMENTO_IA_TIMEOUT_SECONDS", 10):
            with self.assertRaises(AssistenteError) as raised:
                self.run_transcription()
        self.assertEqual(raised.exception.status_code, 504)
        self.assertIn("transcrição demorou", str(raised.exception))
        self.provider.transcrever.assert_not_called()
        self.assertEqual(self.sent_samples, [])
        self.assert_temporary_files_removed()

    def test_budget_exhausted_after_first_fragment_does_not_return_partial_text(self):
        def consume_remaining_budget(**kwargs):
            result = self.transcribe(**kwargs)
            self.now += kwargs["timeout"]
            return result
        self.provider.transcrever.side_effect = consume_remaining_budget
        with patch.object(audio.settings, "ATENDIMENTO_IA_TIMEOUT_SECONDS", 10), \
                patch.object(audio, "CHUNK_MAX_SECONDS", 1):
            with self.assertRaises(AssistenteError) as raised:
                self.run_transcription()
        self.assertEqual(raised.exception.status_code, 504)
        self.assertNotIn("Parte 1", str(raised.exception))
        self.assertEqual(self.provider.transcrever.call_count, 1)
        self.assertEqual(self.sent_timeouts, [9.0])
        self.assertLess(len(self.sent_samples[0]), len(self.samples))
        self.assert_temporary_files_removed()


if __name__ == "__main__":
    unittest.main()
