"""Processamento por fonte e síntese clínica com evidências preservadas."""
from __future__ import annotations

import hashlib
import io
import json
from copy import deepcopy
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from pydantic import Field, ValidationError

from app.core.config import settings
from app.services.atendimento_ia_response import StructuredResponseError, parse_structured_response
from app.schemas.atendimento_assistente import (
    AchadoExame,
    AnaliseClinica,
    CampoSugerido,
    StrictOutput,
    SugestaoConduta,
)
from app.services.atendimento_assistente import (
    ARQUIVOS_MAX_COUNT,
    INSTRUCTIONS,
    TRANSCRICAO_MAX_CHARS,
    ArquivoAnalise,
    AssistenteError,
    OpenAIAtendimentoProvider,
    _esforco_analise,
    _provider_error,
    require_enabled,
    validar_arquivo,
    validar_audio,
    validar_resultado,
)
from app.services.atendimento_transcricao_revisao import TrechoTranscricao, revisar_trechos

AUDIO_MAX_SECONDS = 30 * 60
AUDIO_CHUNK_SECONDS = 8 * 60
AUDIO_SAMPLE_RATE = 16000
AUDIO_DECODE_TIMEOUT_SECONDS = 120
AUDIO_REVIEW_BUDGET_SECONDS = 180
# The generation allowance includes reasoning and the structured answer. These
# larger bounds belong only to the durable worker, never the synchronous route.
PDF_READ_TIMEOUT_SECONDS = 600
BATCH_ANALYSIS_MAX_OUTPUT_TOKENS = 32000


class SinteseClinica(StrictOutput):
    campos: list[CampoSugerido] = Field(max_length=30)
    sugestoes: list[SugestaoConduta] = Field(max_length=15)
    pendencias: list[str] = Field(max_length=40)
    avisos: list[str] = Field(max_length=40)


class AchadoExameLote(AchadoExame):
    alertas: list[str] = Field(max_length=30)


class AnaliseClinicaLote(AnaliseClinica):
    # Every finding already accepted for each of the five documents survives.
    achados_exames: list[AchadoExameLote] = Field(max_length=500)
    pendencias: list[str] = Field(max_length=500)
    avisos: list[str] = Field(max_length=500)


SINTESE_INSTRUCTIONS = INSTRUCTIONS + """
Você recebe a transcrição integral e a extração revisável de CADA exame do lote.
Cruze essas fontes com o contexto salvo para compreender o atendimento como um conjunto.
A extração dos exames é uma leitura assistida, sujeita a erro, e contém suas evidências,
páginas, datas, identidade e confiança. Preserve essas limitações ao justificar propostas.
Cada leitura em exames.leituras_isoladas recebeu somente seu documento, sem acesso à
transcrição do conjunto. Suas pendências e avisos descrevem aquela etapa, não o estado
atual do lote. Reavalie essas notas usando a transcrição integral, todos os exames e o
contexto salvo. Produza pendencias e avisos globais somente após essa reconciliação;
uma alegação anterior de transcrição ausente não comprova sua ausência neste conjunto.
Mantenha pendências documentais ainda relevantes, incluindo referências ausentes,
ilegibilidade e identidade, identificando a fonte. As notas originais de cada documento
continuarão visíveis separadamente como histórico da leitura isolada.
Destaque informações convergentes, divergências entre relato e exames e lacunas relevantes.
Não conclua que a ausência de achado na extração prova normalidade no documento original.
Os objetos fontes e achados_exames serão preservados pelo sistema. Nesta resposta produza
apenas campos, sugestoes, pendencias e avisos. Campos devem usar fonte='transcricao' com
um trecho literal dessa transcrição. Resultados dos exames continuam na revisão individual
com sua fonte original, sem duplicação em campos de texto. Nas justificativas, identifique
os arquivos e páginas que sustentam cada proposta. Não invente números, doses ou achados.
Quando o sistema fornecer revisoes_veterinarias de raça, a identificação original da IA
continua no histórico, mas o veterinário confirmou explicitamente o mesmo paciente e
classificou a divergência conferida como somente de raça. Para essas fontes, use essa
confirmação humana para a síntese; ela não confirma qual é a raça e não resolve outro
tipo de divergência. Raça pendente não é uma raça: não escolha entre cadastro e exames,
não deduza raça de imagens ou achados e não baseie conduta, referência ou predisposição
em raça presumida. Registre a raça como pendência de revisão veterinária.
"""


def _ffmpeg_utilizavel(binary: str | None) -> bool:
    if not binary:
        return False
    try:
        result = subprocess.run([binary, "-version"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _resolver_ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if _ffmpeg_utilizavel(binary):
        return binary
    try:
        # The pinned dependency supplies its own executable, including on hosts
        # without a system FFmpeg. Its explicit env override still needs checking.
        from imageio_ffmpeg import get_ffmpeg_exe
        binary = get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError) as exc:
        raise AssistenteError("O preparo de áudio está indisponível neste ambiente. Verifique a instalação do FFmpeg do backend.", 503) from exc
    if not _ffmpeg_utilizavel(binary):
        raise AssistenteError("O preparo de áudio está indisponível neste ambiente. Verifique a instalação do FFmpeg do backend.", 503)
    return binary


def _decodificar_audio(source: Path, target: Path) -> None:
    binary = _resolver_ffmpeg()
    # The one-second sentinel bounds decompression while detecting overlong input.
    # Decoder failure is checked before any fragment is sent to the provider.
    command = [
        binary, "-nostdin", "-hide_banner", "-v", "error", "-xerror",
        "-max_alloc", "67108864", "-threads", "1",
        "-protocol_whitelist", "file,pipe", "-err_detect", "explode",
        "-i", str(source), "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-t", str(AUDIO_MAX_SECONDS + 1),
        # Use decoded sample order rather than possibly regressing browser
        # timestamps. No samples are dropped or synthesized to repair the clock.
        "-af", f"aresample={AUDIO_SAMPLE_RATE},asetpts=N/SR/TB",
        "-ac", "1", "-ar", str(AUDIO_SAMPLE_RATE),
        "-map_metadata", "-1", "-map_chapters", "-1", "-c:a", "pcm_s16le", str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=AUDIO_DECODE_TIMEOUT_SECONDS, check=False)
    except OSError as exc:
        raise AssistenteError("O preparo de áudio está indisponível neste ambiente. Verifique a instalação do FFmpeg do backend.", 503) from exc
    except subprocess.TimeoutExpired as exc:
        raise AssistenteError("Não foi possível preparar o áudio. Confira o original e tente retomar este arquivo.", 422) from exc
    if result.returncode != 0 or result.stderr.strip():
        # Decoder messages can contain paths and metadata. Do not expose them.
        raise AssistenteError("O áudio não pôde ser decodificado integralmente. Confira o arquivo original.", 422)


def processar_audio(*, nome: str, mime: str, content: bytes, paciente_nome: str | None = None) -> dict:
    require_enabled()
    safe_name, _ = validar_audio(nome, mime, content)
    with tempfile.TemporaryDirectory(prefix="fortcordis-audio-lote-") as directory:
        root = Path(directory)
        source = root / ("original" + Path(safe_name).suffix)
        source.write_bytes(content)
        normalized = root / "normalizado.wav"
        _decodificar_audio(source, normalized)
        try:
            recording = wave.open(str(normalized), "rb")
        except (OSError, EOFError, wave.Error) as exc:
            raise AssistenteError("O áudio preparado não pôde ser lido. Confira o original.", 422) from exc
        with recording:
            rate = recording.getframerate()
            frames = recording.getnframes()
            if not frames or rate != AUDIO_SAMPLE_RATE or recording.getnchannels() != 1 or recording.getsampwidth() != 2:
                raise AssistenteError("O áudio preparado não contém uma faixa de voz válida.", 422)
            if frames > AUDIO_MAX_SECONDS * rate:
                raise AssistenteError("Cada áudio do lote pode conter até 30 minutos.", 413)
            provider = OpenAIAtendimentoProvider()
            transcripts: list[str] = []
            notices: list[str] = []
            chunks: list[TrechoTranscricao] = []
            chunk_frames = AUDIO_CHUNK_SECONDS * rate
            for index, start in enumerate(range(0, frames, chunk_frames), start=1):
                expected = min(chunk_frames, frames - start)
                samples = recording.readframes(expected)
                if len(samples) != expected * 2:
                    raise AssistenteError("A leitura do áudio ficou incompleta. Confira o original.", 422)
                chunk = root / f"trecho-{index:02d}.wav"
                with wave.open(str(chunk), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(rate)
                    output.writeframes(samples)
                result = provider.transcrever(nome=chunk.name, mime="audio/wav", content=chunk.read_bytes(), paciente_nome=paciente_nome)
                transcripts.append(result["texto"])
                chunks.append(TrechoTranscricao(index, start, start + expected, result["texto"]))
                notices.extend(result["avisos"])
                if sum(map(len, transcripts)) + 2 * (len(transcripts) - 1) > TRANSCRICAO_MAX_CHARS:
                    raise AssistenteError("A transcrição deste áudio excede 80.000 caracteres. Revise o material antes de continuar.", 413)
                chunk.unlink()

            def load_chunk(chunk: TrechoTranscricao) -> bytes:
                recording.setpos(chunk.inicio_frame)
                samples = recording.readframes(chunk.fim_frame - chunk.inicio_frame)
                if len(samples) != (chunk.fim_frame - chunk.inicio_frame) * 2:
                    raise AssistenteError("Não foi possível reler todo o trecho para conferência.")
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as output:
                    output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                    output.writeframes(samples)
                return buffer.getvalue()

            # The durable worker has a separate bounded advisory phase, started
            # only after all primary chunks succeeded. It does not repeat them.
            review = revisar_trechos(
                provider=provider, trechos=chunks, carregar_audio=load_chunk, sample_rate=rate,
                deadline=time.monotonic() + min(AUDIO_REVIEW_BUDGET_SECONDS, settings.ATENDIMENTO_IA_TIMEOUT_SECONDS),
            )
            notices.extend(f"Áudio {safe_name}: {notice}" for notice in review["avisos"])
    return {
        "texto": "\n\n".join(transcripts),
        "modelo": settings.ATENDIMENTO_IA_TRANSCRIPTION_MODEL,
        "avisos": list(dict.fromkeys(notices)),
        "revisao_transcricao": review,
    }


def processar_exame(*, nome: str, mime: str, content: bytes, indice: int, context: dict, user_id: int) -> dict:
    require_enabled()
    arquivo = validar_arquivo(nome, mime, content, indice)
    read_timeout = PDF_READ_TIMEOUT_SECONDS if arquivo.mime == "application/pdf" else None
    analise = OpenAIAtendimentoProvider(read_timeout=read_timeout).analisar(
        transcript="", context=context, files=[arquivo], user_id=user_id,
        max_output_tokens=BATCH_ANALYSIS_MAX_OUTPUT_TOKENS if arquivo.mime == "application/pdf" else 16000,
    )
    return {
        "arquivo": {"nome": arquivo.nome, "mime": arquivo.mime, "paginas": arquivo.paginas},
        "analise": analise,
    }


def _evidencias_exames(exames: list[dict], context: dict) -> tuple[list[ArquivoAnalise], dict, list[dict]]:
    if len(exames) > ARQUIVOS_MAX_COUNT:
        raise AssistenteError("Envie até cinco exames por lote.", 413)
    files: list[ArquivoAnalise] = []
    isolated_notes: list[dict] = []
    combined = {"campos": [], "fontes": [], "achados_exames": [], "sugestoes": [], "pendencias": [], "avisos": []}
    try:
        for exame in exames:
            metadata = exame["arquivo"]
            if not isinstance(metadata["nome"], str) or not metadata["nome"] or type(metadata["paginas"]) is not int or not 1 <= metadata["paginas"] <= 30:
                raise ValueError("Metadados da fonte inválidos.")
            file = ArquivoAnalise(metadata["nome"], metadata["mime"], b"", metadata["paginas"])
            analysis = AnaliseClinicaLote.model_validate({key: exame["analise"][key] for key in AnaliseClinica.model_fields})
            if len(analysis.achados_exames) > 100:
                raise ValueError("Limite de achados por exame excedido.")
            validated = validar_resultado(analysis, transcript="", context=context, files=[file])
            files.append(file)
            for key in ("fontes", "achados_exames"):
                combined[key].extend(validated[key])
            notes = {"arquivo": file.nome, **{
                key: list(dict.fromkeys(validated[key])) for key in ("pendencias", "avisos")}}
            isolated_notes.append(notes)
            # Preserve every source limitation, but never present a document-only
            # gap as a current global gap. No content/keyword filtering is applied.
            sections = []
            for key, label in (("pendencias", "Pendências registradas"), ("avisos", "Avisos registrados")):
                if notes[key]:
                    sections.append(f"{label}: " + " | ".join(notes[key]))
            if sections:
                combined["avisos"].append(
                    f"Histórico da leitura isolada de {file.nome} (sem acesso à transcrição do conjunto). "
                    + " ".join(sections))
        if len({file.nome for file in files}) != len(files):
            raise ValueError("Fontes duplicadas.")
        AnaliseClinicaLote.model_validate(combined)
    except (KeyError, TypeError, ValueError) as exc:
        raise AssistenteError("Os resultados dos exames estão incompletos ou inválidos. Reprocesse as fontes indicadas.", 502) from exc
    return files, combined, isolated_notes


def sintetizar_lote(*, transcript: str, context: dict, exames: list[dict], user_id: int,
                   revisoes_raca: dict[str, dict] | None = None) -> dict:
    require_enabled()
    if len(transcript) > TRANSCRICAO_MAX_CHARS:
        raise AssistenteError("A transcrição conjunta excede 80.000 caracteres.", 413)
    if not transcript.strip() and not exames:
        raise AssistenteError("O lote precisa de uma transcrição ou exame concluído.", 422)
    files, combined, isolated_notes = _evidencias_exames(exames, context)
    checked = validar_resultado(AnaliseClinicaLote.model_validate(combined), transcript=transcript,
                               context=context, files=files, revisoes_raca=revisoes_raca)
    if checked["bloqueado_integracao"]:
        return checked
    synthesis_context = deepcopy(context)
    reviews = [{"arquivo": source["arquivo"], **source["revisao_raca"]}
               for source in checked["fontes"] if source.get("revisao_raca")]
    if reviews:
        # Snapshot validation still uses the unchanged authoritative context.
        # Only the inference input treats breed as unresolved.
        synthesis_context["paciente"]["raca"] = None
        synthesis_context["paciente"]["raca_estado"] = "pendente_revisao_veterinaria"
    payload = {
        "contexto_salvo": synthesis_context,
        "transcricao": transcript,
        "exames": {"fontes": combined["fontes"], "achados_exames": combined["achados_exames"],
                   "leituras_isoladas": isolated_notes},
    }
    if reviews:
        payload["revisoes_veterinarias"] = reviews
    provider = OpenAIAtendimentoProvider(read_timeout=PDF_READ_TIMEOUT_SECONDS if files else None)
    try:
        response = parse_structured_response(provider.client.responses,
            model=settings.ATENDIMENTO_IA_MODEL,
            reasoning={"effort": _esforco_analise(com_arquivos=bool(files))},
            instructions=SINTESE_INSTRUCTIONS,
            input=[{"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)}]}],
            text_format=SinteseClinica,
            max_output_tokens=BATCH_ANALYSIS_MAX_OUTPUT_TOKENS if files else 16000,
            store=False,
            safety_identifier=hashlib.sha256(f"fortcordis-atendimento:{user_id}".encode()).hexdigest(),
        )
        if getattr(response, "status", "completed") != "completed" or getattr(response, "output_parsed", None) is None:
            raise AssistenteError("A IA não concluiu a síntese do conjunto. Retome a análise para tentar novamente.", 502)
        synthesis = SinteseClinica.model_validate(response.output_parsed).model_dump()
        combined["campos"] = synthesis["campos"]
        combined["sugestoes"] = synthesis["sugestoes"]
        combined["pendencias"] = list(dict.fromkeys(synthesis["pendencias"]))
        combined["avisos"] = list(dict.fromkeys(combined["avisos"] + synthesis["avisos"]))
        output = AnaliseClinicaLote.model_validate(combined)
    except AssistenteError:
        raise
    except StructuredResponseError as exc:
        raise AssistenteError(str(exc) + " Retome a análise para tentar novamente; as fontes concluídas estão preservadas.", 502) from exc
    except ValidationError as exc:
        raise AssistenteError("A síntese não passou na validação de formato. Retome a análise para tentar novamente.", 502) from exc
    except Exception as exc:
        raise _provider_error(exc) from exc
    return validar_resultado(output, transcript=transcript, context=context, files=files, revisoes_raca=revisoes_raca)
