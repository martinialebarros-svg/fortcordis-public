import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-assistente-secret-not-for-production")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services import atendimento_assistente_lote_provider as service
from app.services.atendimento_assistente import AssistenteError, OpenAIAtendimentoProvider, validar_arquivo
from tests.test_atendimento_assistente import CONTEXT, TRANSCRIPT, pdf_bytes, raw_output


def cached_exam(index=1):
    output = raw_output(True)
    output["campos"] = []
    name = f"{index:02d}_exame.pdf"
    output["fontes"][0]["arquivo"] = name
    output["achados_exames"][0]["arquivo"] = name
    return {"arquivo": {"nome": name, "mime": "application/pdf", "paginas": 2}, "analise": output}


def synthesis():
    return service.SinteseClinica.model_validate({key: raw_output()[key] for key in service.SinteseClinica.model_fields})


def write_audio(target, seconds=0.1):
    with wave.open(str(target), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(service.AUDIO_SAMPLE_RATE)
        output.writeframes(b"\0\0" * int(service.AUDIO_SAMPLE_RATE * seconds))


def wav_bytes(seconds=0.1):
    output = BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(service.AUDIO_SAMPLE_RATE)
        recording.writeframes(b"\0\0" * int(service.AUDIO_SAMPLE_RATE * seconds))
    return output.getvalue()


class PdfTimeoutTests(unittest.TestCase):
    def test_slow_pdf_completes_in_batch_without_extending_direct_analysis(self):
        pdf = pdf_bytes(2)
        output = cached_exam()["analise"]
        requests = []

        def respond(_transport, request):
            timeouts = request.extensions["timeout"]
            requests.append(timeouts)
            if timeouts["read"] < 480:
                raise httpx.ReadTimeout("synthetic delay", request=request)
            return httpx.Response(200, request=request, json={
                "id": "resp_synthetic", "object": "response", "created_at": 0,
                "status": "completed", "model": settings.ATENDIMENTO_IA_MODEL,
                "output": [{"id": "msg_synthetic", "type": "message", "status": "completed", "role": "assistant",
                            "content": [{"type": "output_text", "text": json.dumps(output), "annotations": []}]}],
            })

        with patch.object(httpx.HTTPTransport, "handle_request", respond), \
                patch.object(settings, "ATENDIMENTO_IA_ENABLED", True), \
                patch.object(settings, "ATENDIMENTO_IA_TIMEOUT_SECONDS", 180), \
                patch.object(settings, "OPENAI_API_KEY", "synthetic-only-key"):
            arquivo = validar_arquivo("exame.pdf", "application/pdf", pdf, 1)
            with self.assertRaises(AssistenteError) as error:
                OpenAIAtendimentoProvider().analisar(transcript="", context=CONTEXT, files=[arquivo], user_id=8)
            self.assertEqual(error.exception.status_code, 504)
            result = service.processar_exame(nome="exame.pdf", mime="application/pdf", content=pdf,
                                           indice=1, context=CONTEXT, user_id=8)

        self.assertEqual([request["read"] for request in requests], [180, 600])
        self.assertTrue(all(request["connect"] == 180 for request in requests))
        self.assertEqual(result["analise"]["achados_exames"][0]["valor"], "12,3")
        self.assertEqual(result["analise"]["achados_exames"][0]["unidade"], "g/dL")
        self.assertTrue(result["analise"]["revisao_obrigatoria"])

    def test_pdf_generation_budget_and_incomplete_response_are_distinguished(self):
        requests = []
        output = cached_exam()["analise"]

        def respond(_transport, request):
            body = json.loads(request.content)
            requests.append(body)
            complete = body["max_output_tokens"] == 32000
            return httpx.Response(200, request=request, json={
                "id": "resp_synthetic", "object": "response", "created_at": 0,
                "status": "completed" if complete else "incomplete", "model": settings.ATENDIMENTO_IA_MODEL,
                "incomplete_details": None if complete else {"reason": "max_output_tokens"},
                "usage": {"input_tokens": 10, "output_tokens": 17000 if complete else 16000,
                          "total_tokens": 17010 if complete else 16010,
                          "output_tokens_details": {"reasoning_tokens": 10134}},
                "output": [{"id": "msg_synthetic", "type": "message", "status": "completed" if complete else "incomplete", "role": "assistant",
                            "content": [{"type": "output_text", "text": json.dumps(output) if complete else '{"campos": [', "annotations": []}]}],
            })

        with patch.object(httpx.HTTPTransport, "handle_request", respond), \
                patch.object(settings, "ATENDIMENTO_IA_ENABLED", True), \
                patch.object(settings, "ATENDIMENTO_IA_REASONING_EFFORT", "max"), \
                patch.object(settings, "OPENAI_API_KEY", "synthetic-only-key"):
            arquivo = validar_arquivo("exame.pdf", "application/pdf", pdf_bytes(2), 1)
            with self.assertRaisesRegex(AssistenteError, "limite de geração") as error:
                OpenAIAtendimentoProvider().analisar(transcript="", context=CONTEXT, files=[arquivo], user_id=8)
            self.assertNotIn("formato", str(error.exception))
            result = service.processar_exame(nome="exame.pdf", mime="application/pdf", content=pdf_bytes(2), indice=1, context=CONTEXT, user_id=8)

        self.assertEqual([r["max_output_tokens"] for r in requests], [16000, 32000])
        self.assertTrue(all(r["store"] is False and r["reasoning"] == {"effort": "max"} for r in requests))
        self.assertEqual(result["analise"]["achados_exames"][0]["valor"], "12,3")
        self.assertEqual(result["analise"]["achados_exames"][0]["unidade"], "g/dL")
        self.assertTrue(result["analise"]["revisao_obrigatoria"])


class LoteProviderTests(unittest.TestCase):
    def setUp(self):
        parser = patch.object(service, "parse_structured_response", side_effect=lambda responses, **kwargs: responses.parse(**kwargs))
        parser.start()
        self.addCleanup(parser.stop)
        self.enabled = patch.object(service, "require_enabled")
        self.enabled.start()
        self.addCleanup(self.enabled.stop)
        self.provider = Mock()
        self.provider.client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=synthesis())
        self.provider.transcrever.side_effect = lambda **kw: {"texto": TRANSCRIPT, "modelo": "gpt-transcribe", "avisos": ["Revisar áudio."]}
        self.constructor = patch.object(service, "OpenAIAtendimentoProvider", return_value=self.provider)
        self.constructor.start()
        self.addCleanup(self.constructor.stop)

    def test_document_processed_once_with_stable_source_and_original_metadata(self):
        self.provider.analisar.return_value = cached_exam(3)["analise"]
        result = service.processar_exame(nome="exame.pdf", mime="application/pdf", content=pdf_bytes(2), indice=3, context=CONTEXT, user_id=8)
        self.assertEqual(result["arquivo"], {"nome": "03_exame.pdf", "mime": "application/pdf", "paginas": 2})
        args = self.provider.analisar.call_args.kwargs
        self.assertEqual(args["transcript"], "")
        self.assertEqual(args["context"], CONTEXT)
        self.assertEqual(args["files"][0].nome, "03_exame.pdf")

    def test_synthesis_receives_every_source_and_preserves_all_findings(self):
        exams = [cached_exam(1), cached_exam(2)]
        exams[1]["analise"]["achados_exames"][0]["valor"] = "14,1"
        original = copy.deepcopy(exams)
        result = service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=exams, user_id=8)
        self.assertEqual(result["campos"][0]["texto"], TRANSCRIPT)
        self.assertEqual([x["valor"] for x in result["achados_exames"]], ["12,3", "14,1"])
        self.assertEqual([x["arquivo"] for x in result["fontes"]], ["01_exame.pdf", "02_exame.pdf"])
        self.assertTrue(result["revisao_obrigatoria"])
        self.assertFalse(result["bloqueado_integracao"])
        self.assertEqual(exams, original)
        args = self.provider.client.responses.parse.call_args.kwargs
        payload = json.loads(args["input"][0]["content"][0]["text"])
        self.assertEqual(payload["transcricao"], TRANSCRIPT)
        self.assertEqual(payload["contexto_salvo"], CONTEXT)
        self.assertEqual(len(payload["exames"]["fontes"]), 2)
        self.assertFalse(args["store"])
        self.assertEqual(args["max_output_tokens"], 32000)
        self.assertEqual(service.OpenAIAtendimentoProvider.call_args.kwargs, {"read_timeout": 600})
        self.assertEqual(args["reasoning"], {"effort": settings.ATENDIMENTO_IA_REASONING_EFFORT})

    def test_combined_findings_are_never_truncated_to_single_request_limit(self):
        exams = [cached_exam(i) for i in range(1, 6)]
        for item in exams:
            item["analise"]["achados_exames"] *= 100
        result = service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=exams, user_id=8)
        self.assertEqual(len(result["achados_exames"]), 500)

    def test_synthesis_reconciles_global_gaps_without_promoting_isolated_document_notes(self):
        exam = cached_exam()
        missing_transcript = "A transcrição enviada está vazia; obter o relato do tutor."
        reference_notice = "Confirmar a referência do próprio laboratório."
        illegibility_notice = "Rodapé parcialmente ilegível: conferir o original."
        exam["analise"]["pendencias"] = [missing_transcript, reference_notice]
        exam["analise"]["avisos"] = [illegibility_notice]
        exam["analise"]["achados_exames"][0].update(
            confianca="baixa", referencia=None, alertas=["Unidade ilegível no documento."])
        original = copy.deepcopy(exam)
        reconciled = synthesis()
        reconciled.pendencias = ["Obter versão legível e referência do laboratório para 01_exame.pdf."]
        reconciled.avisos = ["A transcrição do conjunto foi considerada com os exames."]
        self.provider.client.responses.parse.return_value.output_parsed = reconciled

        result = service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=[exam], user_id=8)

        self.assertEqual(result["pendencias"], reconciled.pendencias)
        self.assertNotIn(missing_transcript, result["pendencias"])
        for original_note in (missing_transcript, reference_notice, illegibility_notice):
            matching = [notice for notice in result["avisos"] if original_note in notice]
            self.assertEqual(len(matching), 1)
            self.assertIn("01_exame.pdf", matching[0])
            self.assertIn("leitura isolada", matching[0])
            self.assertIn("sem acesso à transcrição do conjunto", matching[0])
        self.assertIn(reconciled.avisos[0], result["avisos"])
        self.assertEqual(result["fontes"][0]["identidade"], "compativel")
        finding = result["achados_exames"][0]
        self.assertIsNone(finding["valor"])
        self.assertIsNone(finding["unidade"])
        self.assertIsNone(finding["referencia"])
        self.assertIn("Unidade ilegível no documento.", finding["alertas"])
        self.assertEqual(finding["evidencia"], original["analise"]["achados_exames"][0]["evidencia"])
        payload = json.loads(self.provider.client.responses.parse.call_args.kwargs["input"][0]["content"][0]["text"])
        notes = payload["exames"]["leituras_isoladas"]
        self.assertEqual(notes[0]["arquivo"], "01_exame.pdf")
        self.assertEqual(notes[0]["pendencias"], original["analise"]["pendencias"])
        self.assertIn(illegibility_notice, notes[0]["avisos"])
        self.assertEqual(payload["transcricao"], TRANSCRIPT)
        self.assertEqual(exam, original)

    def test_document_notes_survive_even_when_synthesis_omits_them(self):
        exam = cached_exam()
        exam["analise"]["pendencias"] = ["Referência do laboratório ausente."]
        exam["analise"]["avisos"] = ["Data parcialmente ilegível."]
        result = service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=[exam], user_id=8)
        self.assertEqual(result["pendencias"], [])
        self.assertTrue(any("Referência do laboratório ausente." in notice for notice in result["avisos"]))
        self.assertTrue(any("Data parcialmente ilegível." in notice for notice in result["avisos"]))

    def test_synthesis_may_request_missing_transcript_when_batch_has_only_documents(self):
        output = synthesis()
        output.campos = []
        output.pendencias = ["A transcrição enviada está vazia; obter o relato do tutor."]
        self.provider.client.responses.parse.return_value.output_parsed = output
        result = service.sintetizar_lote(transcript="", context=CONTEXT, exames=[cached_exam()], user_id=8)
        self.assertEqual(result["pendencias"], output.pendencias)

    def test_missing_or_duplicate_source_is_rejected_before_synthesis(self):
        incomplete = cached_exam()
        incomplete["analise"]["fontes"] = []
        for exams in [[incomplete], [cached_exam(), cached_exam()]]:
            with self.subTest(exams=len(exams)), self.assertRaises(AssistenteError):
                service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=exams, user_id=8)
        self.provider.client.responses.parse.assert_not_called()

    def test_invalid_page_is_rejected_before_synthesis(self):
        exam = cached_exam()
        exam["analise"]["achados_exames"][0]["pagina"] = 3
        with self.assertRaises(AssistenteError):
            service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=[exam], user_id=8)
        self.provider.client.responses.parse.assert_not_called()

    def test_identity_is_revalidated_against_current_context_and_blocks_all_integration(self):
        context = copy.deepcopy(CONTEXT)
        context["paciente"]["nome"] = "Outro paciente"
        exam = cached_exam()
        exam["analise"]["avisos"] = ["Identificação exige conferência no original."]
        result = service.sintetizar_lote(transcript=TRANSCRIPT, context=context, exames=[exam], user_id=8)
        self.assertTrue(result["bloqueado_integracao"])
        self.assertEqual(result["campos"], [])
        self.assertEqual(result["sugestoes"], [])
        self.assertEqual(len(result["achados_exames"]), 1)
        self.assertTrue(any("Corrija ou remova" in item for item in result["pendencias"]))
        self.assertTrue(any("01_exame.pdf" in notice and "Identificação exige conferência" in notice for notice in result["avisos"]))
        self.provider.client.responses.parse.assert_not_called()

    def test_uncertain_measurement_stays_unusable_in_synthesis_and_review(self):
        exam = cached_exam()
        exam["analise"]["achados_exames"][0]["confianca"] = "baixa"
        result = service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=[exam], user_id=8)
        self.assertIsNone(result["achados_exames"][0]["valor"])
        self.assertIsNone(result["achados_exames"][0]["unidade"])
        args = self.provider.client.responses.parse.call_args.kwargs
        payload = json.loads(args["input"][0]["content"][0]["text"])
        self.assertIsNone(payload["exames"]["achados_exames"][0]["valor"])

    def test_synthesis_cannot_invent_literal_transcript_evidence(self):
        output = synthesis()
        output.campos[0].evidencia = "Texto ausente da transcrição"
        self.provider.client.responses.parse.return_value.output_parsed = output
        result = service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=[cached_exam()], user_id=8)
        self.assertEqual(result["campos"], [])

    def test_provider_failure_and_incomplete_response_leave_no_partial_synthesis(self):
        self.provider.client.responses.parse.side_effect = RuntimeError("private-provider-message")
        with self.assertRaises(AssistenteError) as captured:
            service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=[], user_id=8)
        self.assertNotIn("private-provider-message", str(captured.exception))
        self.provider.client.responses.parse.side_effect = None
        self.provider.client.responses.parse.return_value.status = "incomplete"
        with self.assertRaises(AssistenteError):
            service.sintetizar_lote(transcript=TRANSCRIPT, context=CONTEXT, exames=[], user_id=8)

    def test_full_decode_precedes_calls_and_chunks_cover_all_samples_in_order(self):
        def decode(source, target):
            write_audio(target, 2.5)
        samples = []
        def transcribe(**kwargs):
            with wave.open(BytesIO(kwargs["content"]), "rb") as chunk:
                samples.append(chunk.getnframes())
            return {"texto": f"Parte {len(samples)}", "modelo": "gpt-transcribe", "avisos": ["Revisar áudio."]}
        self.provider.transcrever.side_effect = transcribe
        with patch.object(service, "_decodificar_audio", side_effect=decode), patch.object(service, "AUDIO_CHUNK_SECONDS", 1):
            result = service.processar_audio(nome="origem.wav", mime="audio/wav", content=wav_bytes(), paciente_nome="Paciente Teste")
        self.assertEqual(samples, [16000, 16000, 8000])
        self.assertEqual(result["texto"], "Parte 1\n\nParte 2\n\nParte 3")
        self.assertIn("Revisar áudio.", result["avisos"])
        self.assertEqual(result["revisao_transcricao"]["estado"], "indisponivel")
        self.assertEqual(self.provider.transcrever.call_args.kwargs["paciente_nome"], "Paciente Teste")

    def test_overlong_audio_is_rejected_before_provider_and_temp_files_removed(self):
        paths = []
        def decode(source, target):
            paths.append(source.parent)
            write_audio(target, 1.1)
        with patch.object(service, "_decodificar_audio", side_effect=decode), patch.object(service, "AUDIO_MAX_SECONDS", 1):
            with self.assertRaises(AssistenteError) as captured:
                service.processar_audio(nome="origem.wav", mime="audio/wav", content=wav_bytes())
        self.assertEqual(captured.exception.status_code, 413)
        self.provider.transcrever.assert_not_called()
        self.assertFalse(paths[0].exists())

    def test_failed_fragment_does_not_return_incomplete_transcript(self):
        def decode(source, target):
            write_audio(target, 2.5)
        self.provider.transcrever.side_effect = [{"texto": "primeiro", "avisos": [], "modelo": "gpt-transcribe"}, AssistenteError("Falha temporária.", 502)]
        with patch.object(service, "_decodificar_audio", side_effect=decode), patch.object(service, "AUDIO_CHUNK_SECONDS", 1):
            with self.assertRaises(AssistenteError):
                service.processar_audio(nome="origem.wav", mime="audio/wav", content=wav_bytes())
        self.assertEqual(self.provider.transcrever.call_count, 2)

    def test_missing_ffmpeg_returns_actionable_failure_without_provider_request(self):
        with patch.object(service.shutil, "which", return_value=None), patch.dict(sys.modules, {"imageio_ffmpeg":None}):
            with self.assertRaises(AssistenteError) as captured:
                service.processar_audio(nome="origem.wav", mime="audio/wav", content=wav_bytes())
        self.assertEqual(captured.exception.status_code, 503)
        self.provider.transcrever.assert_not_called()

    def test_usable_system_ffmpeg_does_not_require_bundled_package(self):
        with patch.object(service.shutil,"which",return_value="/system/ffmpeg"), \
             patch.object(service.subprocess,"run",return_value=SimpleNamespace(returncode=0)), \
             patch.dict(sys.modules,{"imageio_ffmpeg":None}):
            self.assertEqual(service._resolver_ffmpeg(),"/system/ffmpeg")

    def test_unusable_system_ffmpeg_falls_back_to_checked_bundled_binary(self):
        bundled=SimpleNamespace(get_ffmpeg_exe=Mock(return_value="/bundled/ffmpeg"))
        with patch.object(service.shutil,"which",return_value="/system/ffmpeg"), \
             patch.object(service.subprocess,"run",side_effect=[OSError("wrong architecture"),SimpleNamespace(returncode=0)]) as run, \
             patch.dict(sys.modules,{"imageio_ffmpeg":bundled}):
            self.assertEqual(service._resolver_ffmpeg(),"/bundled/ffmpeg")
        bundled.get_ffmpeg_exe.assert_called_once()
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [["/system/ffmpeg","-version"],["/bundled/ffmpeg","-version"]])
        self.assertTrue(all(call.kwargs["timeout"]==5 for call in run.call_args_list))

    def test_nonexecutable_bundled_binary_returns_503_before_transcription(self):
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/"ffmpeg"
            binary.write_text("not executable",encoding="utf-8")
            binary.chmod(0o600)
            bundled=SimpleNamespace(get_ffmpeg_exe=lambda:str(binary))
            with patch.object(service.shutil,"which",return_value=None),patch.dict(sys.modules,{"imageio_ffmpeg":bundled}):
                with self.assertRaises(AssistenteError) as captured:
                    service.processar_audio(nome="origem.wav",mime="audio/wav",content=wav_bytes())
        self.assertEqual(captured.exception.status_code,503)
        self.assertNotIn(directory,str(captured.exception))
        self.provider.transcrever.assert_not_called()

    def test_bundled_lookup_failure_returns_503_without_provider_request(self):
        bundled=SimpleNamespace(get_ffmpeg_exe=Mock(side_effect=RuntimeError("private package path")))
        with patch.object(service.shutil,"which",return_value=None),patch.dict(sys.modules,{"imageio_ffmpeg":bundled}):
            with self.assertRaises(AssistenteError) as captured:
                service.processar_audio(nome="origem.wav",mime="audio/wav",content=wav_bytes())
        self.assertEqual(captured.exception.status_code,503)
        self.assertNotIn("private",str(captured.exception))
        self.provider.transcrever.assert_not_called()

    def test_decoder_disappearing_after_resolution_returns_503(self):
        with patch.object(service,"_resolver_ffmpeg",return_value="/missing/ffmpeg"), \
             patch.object(service.subprocess,"run",side_effect=FileNotFoundError("private path")):
            with self.assertRaises(AssistenteError) as captured:
                service.processar_audio(nome="origem.wav",mime="audio/wav",content=wav_bytes())
        self.assertEqual(captured.exception.status_code,503)
        self.assertNotIn("private",str(captured.exception))
        self.provider.transcrever.assert_not_called()

    def test_decoder_error_hides_paths_and_does_not_transcribe(self):
        with patch.object(service, "_resolver_ffmpeg", return_value="ffmpeg"), patch.object(service.subprocess, "run", return_value=SimpleNamespace(returncode=1, stderr=b"private audio path")):
            with self.assertRaises(AssistenteError) as captured:
                service.processar_audio(nome="origem.wav", mime="audio/wav", content=wav_bytes())
        self.assertNotIn("private", str(captured.exception))
        self.provider.transcrever.assert_not_called()

    def test_real_bundled_decoder_accepts_synthetic_audio_without_system_ffmpeg(self):
        with patch.object(service.shutil,"which",return_value=None),patch.dict(os.environ,{"IMAGEIO_FFMPEG_EXE":""}):
            result = service.processar_audio(nome="sintetico.wav", mime="audio/wav", content=wav_bytes(0.25))
        self.assertEqual(result["texto"], TRANSCRIPT)
        with wave.open(BytesIO(self.provider.transcrever.call_args.kwargs["content"]), "rb") as decoded:
            self.assertEqual(decoded.getnframes(), 4000)

    def test_real_long_webm_is_normalized_and_split_without_losing_duration(self):
        # Exercise the browser container and duration that motivated this feature.
        # Silence is synthetic; the transcription provider remains mocked.
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "sintetico-longo.webm"
            subprocess.run([
                service._resolver_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "1496",
                "-c:a", "libopus", "-b:a", "24k", str(original),
            ], capture_output=True, check=True, timeout=60)
            frames = []
            def transcribe(**kwargs):
                self.assertLess(len(kwargs["content"]), 24_000_000)
                with wave.open(BytesIO(kwargs["content"]), "rb") as chunk:
                    frames.append(chunk.getnframes())
                    self.assertEqual(chunk.getframerate(), 16000)
                    self.assertEqual(chunk.getnchannels(), 1)
                return {"texto": f"Parte sintética {len(frames)}", "modelo": "teste", "avisos": []}
            self.provider.transcrever.side_effect = transcribe
            result = service.processar_audio(nome=original.name, mime="audio/webm", content=original.read_bytes())
        self.assertEqual(frames, [480 * 16000, 480 * 16000, 480 * 16000, 56 * 16000])
        self.assertEqual(result["texto"], "\n\n".join(f"Parte sintética {index}" for index in range(1, 5)))


if __name__ == "__main__":
    unittest.main()
