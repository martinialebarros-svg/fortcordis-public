"""Prepare a complete recording for bounded transcription requests."""

import io
import math
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from app.core.config import settings
from app.services.atendimento_assistente import AssistenteError, TRANSCRICAO_MAX_CHARS
from app.services.atendimento_transcricao_revisao import TrechoTranscricao, revisar_trechos

AUDIO_MAX_SECONDS = 30 * 60
CHUNK_MAX_SECONDS = 8 * 60
SAMPLE_RATE = 16_000
SAMPLE_BYTES = 2
# Long WebM recordings can take over 25 seconds on the production CPU. This
# allowance still consumes the shared request budget; it is not extra time.
DECODE_TIMEOUT_SECONDS = 60
TRANSCRIPTION_BUDGET_SECONDS = 180
DEMUXERS = {
    "audio/webm": "matroska",
    "audio/mp4": "mov",
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
}


def _decode(content: bytes, mime: str, directory: Path, *, timeout: float = DECODE_TIMEOUT_SECONDS) -> Path:
    try:
        binary = get_ffmpeg_exe()
    except RuntimeError as exc:
        raise AssistenteError("O preparo de áudio está indisponível neste ambiente.", 503) from exc

    original = directory / "original"
    original.write_bytes(content)
    normalized = directory / "normalizado.wav"
    command = [
        binary, "-nostdin", "-hide_banner", "-v", "error", "-xerror",
        "-max_alloc", "67108864", "-threads", "1", "-protocol_whitelist", "file",
        "-err_detect", "explode", "-f", DEMUXERS[mime], "-i", str(original),
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        # Decode at most one extra second to detect overlong inputs without truncating them silently.
        "-t", str(AUDIO_MAX_SECONDS + 1),
        # Browser timestamps can regress after resampling. Keep every decoded
        # sample in order, using the sample count for the normalized WAV clock.
        "-af", f"aresample={SAMPLE_RATE},asetpts=N/SR/TB",
        "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-map_metadata", "-1", "-map_chapters", "-1", "-c:a", "pcm_s16le", str(normalized),
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=timeout, check=False)
    except OSError as exc:
        raise AssistenteError("O preparo de áudio está indisponível neste ambiente.", 503) from exc
    except subprocess.TimeoutExpired as exc:
        raise AssistenteError("O preparo do áudio demorou demais. Tente novamente com o original.", 504) from exc
    if result.returncode != 0 or result.stderr:
        raise AssistenteError("Não foi possível ler todo o áudio. Confira e selecione o arquivo original novamente.")
    return normalized


def _quiet_cut(recording: wave.Wave_read, low: int, high: int, target: int) -> int:
    # Choose a low-energy boundary without dropping, overlapping or reordering any samples.
    step = SAMPLE_RATE // 10
    half_window = step // 2
    low = max(low, half_window)
    high = min(high, recording.getnframes() - half_window)
    if high - low < step:
        return target
    offset = low - half_window
    recording.setpos(offset)
    window = recording.readframes(high - low + step)

    def score(cut: int) -> tuple[int, int]:
        start = (cut - low) * SAMPLE_BYTES
        data = window[start:start + step * SAMPLE_BYTES]
        energy = sum(value * value for (value,) in struct.iter_unpack("<h", data))
        return energy, abs(target - cut)

    return min(range(low, high + 1, step), key=score)


def _wav_chunk(samples: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as chunk:
        chunk.setparams((1, SAMPLE_BYTES, SAMPLE_RATE, 0, "NONE", "not compressed"))
        chunk.writeframes(samples)
    return output.getvalue()


def transcrever_gravacao(*, nome: str, mime: str, content: bytes, paciente_nome: str | None,
                         provider_factory) -> dict:
    # Share a budget across all upstream requests. The proxy allows 210 seconds.
    deadline = time.monotonic() + min(TRANSCRIPTION_BUDGET_SECONDS, settings.ATENDIMENTO_IA_TIMEOUT_SECONDS)
    with tempfile.TemporaryDirectory(prefix="fortcordis-transcricao-") as directory:
        path = _decode(content, mime, Path(directory), timeout=min(DECODE_TIMEOUT_SECONDS, _time_left(deadline)))
        try:
            recording = wave.open(str(path), "rb")
        except (OSError, EOFError, wave.Error) as exc:
            raise AssistenteError("O áudio preparado não pôde ser lido. Confira o original.") from exc

        with recording:
            total = recording.getnframes()
            if not total:
                raise AssistenteError("O arquivo não contém uma faixa de áudio.")
            if total > AUDIO_MAX_SECONDS * SAMPLE_RATE:
                raise AssistenteError("Envie uma gravação de até 30 minutos.", 413)
            provider = provider_factory()
            max_frames = CHUNK_MAX_SECONDS * SAMPLE_RATE
            transcripts: list[str] = []
            notices: list[str] = []
            chunks: list[TrechoTranscricao] = []
            model = settings.ATENDIMENTO_IA_TRANSCRIPTION_MODEL
            length = 0
            count = math.ceil(total / max_frames)
            start = 0
            for remaining in range(count, 0, -1):
                target = start + (total - start) // remaining
                low = max(target - 6 * SAMPLE_RATE, total - (remaining - 1) * max_frames)
                high = min(target + 6 * SAMPLE_RATE, start + max_frames)
                end = total if remaining == 1 else _quiet_cut(recording, low, high, target)
                recording.setpos(start)
                samples = recording.readframes(end - start)
                if len(samples) != (end - start) * SAMPLE_BYTES:
                    raise AssistenteError("A leitura do áudio ficou incompleta. Confira o original.")
                result = provider.transcrever(
                    nome=f"trecho-{count - remaining + 1:02d}.wav", mime="audio/wav",
                    content=_wav_chunk(samples), paciente_nome=paciente_nome, timeout=_time_left(deadline),
                )
                text = result["texto"]
                chunks.append(TrechoTranscricao(count - remaining + 1, start, end, text))
                start = end
                model = result.get("modelo", model)
                length += len(text) + (2 if transcripts else 0)
                if length > TRANSCRICAO_MAX_CHARS:
                    raise AssistenteError("A transcrição completa excedeu o limite de 80.000 caracteres.", 413)
                transcripts.append(text)
                notices.extend(result["avisos"])

            def load_chunk(chunk: TrechoTranscricao) -> bytes:
                recording.setpos(chunk.inicio_frame)
                samples = recording.readframes(chunk.fim_frame - chunk.inicio_frame)
                if len(samples) != (chunk.fim_frame - chunk.inicio_frame) * SAMPLE_BYTES:
                    raise AssistenteError("Não foi possível reler todo o trecho para conferência.")
                return _wav_chunk(samples)

            # Obtain every primary chunk before spending any remaining request
            # budget on optional comparison. The original text is never replaced.
            review = revisar_trechos(provider=provider, trechos=chunks, carregar_audio=load_chunk,
                                    sample_rate=SAMPLE_RATE, deadline=deadline)
            notices.extend(review["avisos"])

    return {
        "texto": "\n\n".join(transcripts),
        "modelo": model,
        "avisos": list(dict.fromkeys(notices)) + ([
            "A gravação foi transcrita em trechos na ordem original. Confira as transições com o áudio."
        ] if len(chunks) > 1 else []),
        "revisao_transcricao": review,
    }


def _time_left(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AssistenteError("A transcrição demorou demais. O áudio original continua disponível.", 504)
    return remaining
