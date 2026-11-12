"""Synthetic WebM regression: repeated timestamps must not discard valid PCM."""
import os
import subprocess
import tempfile
import unittest
import wave
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "synthetic-audio-timestamps-test-secret")

from imageio_ffmpeg import get_ffmpeg_exe

from app.services import atendimento_audio as direct
from app.services import atendimento_assistente_lote_provider as batch
from app.services.atendimento_assistente import AssistenteError


def _vint(data, position, *, identifier=False):
    for length in range(1, 9):
        if data[position] & (1 << (8 - length)):
            break
    else:
        raise AssertionError("Invalid synthetic EBML integer")
    value = int.from_bytes(data[position:position + length], "big")
    return (value if identifier else value & ((1 << (7 * length)) - 1)), length


def _block_timestamps(data, start=0, end=None):
    """Locate only SimpleBlock timestamps in our generated Segment/Clusters."""
    end = len(data) if end is None else end
    position = start
    while position < end:
        tag, tag_length = _vint(data, position, identifier=True)
        size, size_length = _vint(data, position + tag_length)
        body = position + tag_length + size_length
        next_position = min(end, body + size)
        if tag in (0x18538067, 0x1F43B675):  # Segment, Cluster
            yield from _block_timestamps(data, body, next_position)
        elif tag == 0xA3:  # SimpleBlock: track integer, signed timestamp, flags, payload
            _, track_length = _vint(data, body)
            yield body + track_length
        position = next_position


def _pcm(content):
    with wave.open(BytesIO(content), "rb") as recording:
        assert recording.getparams()[:3] == (1, 2, 16000)
        return recording.readframes(recording.getnframes())


class AudioTimestampTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="synthetic-webm-clock-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.fixtures = {}
        for frame_duration in ("2.5", "20"):
            original = cls.root / f"synthetic-{frame_duration}.webm"
            subprocess.run([
                get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-v", "error",
                "-f", "lavfi", "-i", "sine=frequency=431:sample_rate=48000",
                "-t", "2.4", "-c:a", "libopus", "-frame_duration", frame_duration,
                "-b:a", "24k", str(original),
            ], capture_output=True, check=True, timeout=15)
            content = original.read_bytes()
            repeated = bytearray(content)
            positions = list(_block_timestamps(content))
            assert len(positions) > 2
            for position in positions:
                # Only container timestamps change. The Opus packets are intact.
                repeated[position:position + 2] = b"\0\0"
            cls.fixtures[frame_duration] = (content, bytes(repeated))

    def decode(self, content, *, pipeline):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if pipeline == "direct":
                target = direct._decode(content, "audio/webm", root)
            else:
                source, target = root / "original.webm", root / "normalized.wav"
                source.write_bytes(content)
                batch._decodificar_audio(source, target)
            return _pcm(target.read_bytes())

    def test_repeated_webm_timestamps_preserve_every_sample_in_both_decoders(self):
        for frame_duration, (original, repeated) in self.fixtures.items():
            for pipeline in ("direct", "batch"):
                with self.subTest(frame_duration=frame_duration, pipeline=pipeline):
                    reference = self.decode(original, pipeline=pipeline)
                    actual = self.decode(repeated, pipeline=pipeline)
                    self.assertEqual(len(reference), 38400 * 2)
                    self.assertEqual(actual, reference)

    def test_direct_single_request_receives_normalized_wav_not_broken_container(self):
        original, repeated = self.fixtures["2.5"]
        provider = Mock()
        expected = {"texto": "Sintético", "avisos": ["Confira o áudio."], "modelo": "mock"}
        provider.transcrever.return_value = expected
        result = direct.transcrever_gravacao(nome="synthetic.webm", mime="audio/webm", content=repeated,
                                            paciente_nome="Paciente Sintético", provider_factory=lambda: provider)
        provider.transcrever.assert_called_once()
        sent = provider.transcrever.call_args.kwargs
        self.assertEqual(sent["mime"], "audio/wav")
        self.assertTrue(sent["nome"].endswith(".wav"))
        self.assertEqual(sent["paciente_nome"], "Paciente Sintético")
        self.assertEqual(result["texto"], expected["texto"])
        self.assertEqual(result["modelo"], expected["modelo"])
        self.assertIn(expected["avisos"][0], result["avisos"])
        self.assertEqual(result["revisao_transcricao"]["estado"], "indisponivel")
        self.assertEqual(_pcm(sent["content"]), self.decode(original, pipeline="direct"))

    def test_segmented_requests_keep_all_samples_in_original_order(self):
        original, repeated = self.fixtures["2.5"]
        reference = self.decode(original, pipeline="direct")
        for pipeline in ("direct", "batch"):
            with self.subTest(pipeline=pipeline):
                samples = []
                provider = Mock()
                def transcribe(**kwargs):
                    samples.append(_pcm(kwargs["content"]))
                    return {"texto": f"Parte {len(samples)}", "avisos": [], "modelo": "mock"}
                provider.transcrever.side_effect = transcribe
                if pipeline == "direct":
                    with patch.object(direct, "CHUNK_MAX_SECONDS", 1):
                        direct.transcrever_gravacao(nome="synthetic.webm", mime="audio/webm", content=repeated,
                                                   paciente_nome=None, provider_factory=lambda: provider)
                else:
                    with patch.object(batch, "require_enabled"), patch.object(batch, "AUDIO_CHUNK_SECONDS", 1), \
                            patch.object(batch, "OpenAIAtendimentoProvider", return_value=provider):
                        batch.processar_audio(nome="synthetic.webm", mime="audio/webm", content=repeated)
                self.assertEqual(len(samples), 3)
                self.assertEqual(b"".join(samples), reference)
                self.assertTrue(all(len(part) <= 16000 * 2 for part in samples))

    def test_truncated_or_corrupt_webm_still_fails_before_any_provider_call(self):
        _, repeated = self.fixtures["2.5"]
        corrupt_packet = bytearray(repeated)
        payload = next(_block_timestamps(corrupt_packet)) + 3  # timestamp + flags
        corrupt_packet[payload:payload + 2] = b"\xff\x00"  # invalid Opus frame count
        for content in (repeated[:-50], bytes(corrupt_packet), b"\x1aE\xdf\xa3invalid"):
            for pipeline in ("direct", "batch"):
                with self.subTest(pipeline=pipeline, bytes=len(content)):
                    provider_factory = Mock()
                    with self.assertRaises(AssistenteError) as raised:
                        if pipeline == "direct":
                            direct.transcrever_gravacao(nome="synthetic.webm", mime="audio/webm", content=content,
                                                       paciente_nome=None, provider_factory=provider_factory)
                        else:
                            with patch.object(batch, "require_enabled"), \
                                    patch.object(batch, "OpenAIAtendimentoProvider", provider_factory):
                                batch.processar_audio(nome="synthetic.webm", mime="audio/webm", content=content)
                    self.assertEqual(raised.exception.status_code, 422)
                    provider_factory.assert_not_called()

    def test_sample_count_still_enforces_duration_despite_repeated_timestamps(self):
        _, repeated = self.fixtures["2.5"]
        for pipeline in ("direct", "batch"):
            with self.subTest(pipeline=pipeline):
                provider_factory = Mock()
                with self.assertRaises(AssistenteError) as raised:
                    if pipeline == "direct":
                        with patch.object(direct, "AUDIO_MAX_SECONDS", 1):
                            direct.transcrever_gravacao(nome="synthetic.webm", mime="audio/webm", content=repeated,
                                                       paciente_nome=None, provider_factory=provider_factory)
                    else:
                        with patch.object(batch, "require_enabled"), patch.object(batch, "AUDIO_MAX_SECONDS", 1), \
                                patch.object(batch, "OpenAIAtendimentoProvider", provider_factory):
                            batch.processar_audio(nome="synthetic.webm", mime="audio/webm", content=repeated)
                self.assertEqual(raised.exception.status_code, 413)
                provider_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
