"""Offline, synthetic safety regressions for advisory audio uncertainty."""
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "synthetic-transcription-review-secret")

from app.services import atendimento_audio as direct
from app.services import atendimento_assistente_lote_provider as batch
from app.services import atendimento_assistente_lotes as jobs
from app.services import atendimento_transcricao_revisao as review
from app.services.atendimento_assistente import AssistenteError


def wav_bytes(samples):
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        recording.writeframes(samples)
    return output.getvalue()


def pcm(content):
    with wave.open(io.BytesIO(content), "rb") as recording:
        return recording.readframes(recording.getnframes())


class ComparisonTests(unittest.TestCase):
    def test_names_numbers_units_signs_and_negations_are_not_normalized_away(self):
        pairs = [
            ("Nina recebeu o tutor", "menina recebeu o doutor"),
            ("Dose de 0,5 mg/kg", "Dose de 5 mg"),
            ("Dose de 1/2 comprimido", "Dose de 12 comprimido"),
            ("O valor é −2", "O valor é 2"),
            ("Não dar remédio", "Dar remédio"),
            ("Pressão < 90", "Pressão > 90"),
            ("Dose 0,5", "Dose 0.5"),
            ("Dose .5 mg", "Dose 5 mg"),
            ("Dose ,5 mg", "Dose 5 mg"),
            ("Diluição 1:1000", "Diluição 1 1000"),
            ("Contagem 10^3", "Contagem 10 3"),
        ]
        for original, alternative in pairs:
            with self.subTest(original=original):
                result, limited = review.comparar_leituras(original, alternative)
                self.assertTrue(result)
                self.assertFalse(limited)
                self.assertEqual(result[0]["texto_original"], original)
                self.assertEqual(result[0]["leitura_alternativa"], alternative)

    def test_cosmetic_case_and_punctuation_do_not_create_replacement_suggestions(self):
        result, limited = review.comparar_leituras("Tutor: relata tosse.", "tutor relata tosse!")
        self.assertEqual(result, [])
        self.assertFalse(limited)

    def test_missing_spoken_name_is_an_insertion_disagreement_not_a_replacement(self):
        result, limited = review.comparar_leituras("Paciente está bem.", "Nébula está bem.")
        self.assertFalse(limited)
        self.assertEqual(result[0]["texto_original"], "Paciente está bem")
        self.assertEqual(result[0]["leitura_alternativa"], "Nébula está bem")

    def test_empty_reading_cannot_be_considered_agreement(self):
        provider = SimpleNamespace(transcrever_revisao=lambda **kw: {"texto": "  "})
        result = self.call_review(provider)
        self.assertEqual(result["estado"], "indisponivel")
        self.assertEqual(result["trechos_revisados"], 0)

    def call_review(self, provider, text="Sem nomes."):
        return review.revisar_trechos(provider=provider,
            trechos=[review.TrechoTranscricao(1, 0, 16000, text)],
            carregar_audio=lambda chunk: b"synthetic", sample_rate=16000,
            deadline=review.time.monotonic() + 20)

    def test_markers_survive_missing_secondary_provider(self):
        result = self.call_review(SimpleNamespace(), "Usa [inaudível] e [incerto: cinco] mg.")
        self.assertEqual(result["estado"], "indisponivel")
        self.assertEqual(result["trechos"][0]["marcacoes_incerteza"], ["[inaudível]", "[incerto: cinco]"])
        self.assertTrue(any("palavras incertas" in notice for notice in result["avisos"]))

    def test_tokens_disagreement_and_excerpt_caps_are_explicit(self):
        with patch.object(review, "MAX_TOKENS", 3):
            result = self.call_review(SimpleNamespace(transcrever_revisao=lambda **kw: {"texto": "um dois três quatro"}))
        self.assertEqual(result["estado"], "parcial")
        self.assertTrue(result["trechos"][0]["limitado"])
        self.assertTrue(any("limite de tamanho" in value for value in result["avisos"]))
        first = " ".join(f"a{index} fim comum segue trecho" for index in range(30))
        second = " ".join(f"b{index} fim comum segue trecho" for index in range(30))
        with patch.object(review, "MAX_DIVERGENCIAS", 2):
            differences, limited = review.comparar_leituras(first, second)
        self.assertTrue(limited)
        self.assertLessEqual(len(differences), 2)
        with patch.object(review, "MAX_FRAGMENT_CHARS", 8):
            differences, limited = review.comparar_leituras("Nome da pessoa distinto", "Nome da paciente alternativo")
        self.assertTrue(limited)
        self.assertTrue(differences[0]["texto_original"].endswith("…"))

    def test_alternative_only_gets_audio_and_budget_not_primary_or_patient(self):
        reader = Mock(return_value={"texto": "Outro nome e 3 mg."})
        result = self.call_review(SimpleNamespace(transcrever_revisao=reader), "Nome sintético e 2 mg.")
        self.assertEqual(set(reader.call_args.kwargs), {"nome", "mime", "content", "timeout"})
        self.assertEqual(result["estado"], "concluida")
        self.assertEqual(result["trechos"][0]["inicio_segundos"], 0)
        self.assertEqual(result["trechos"][0]["fim_segundos"], 1)
        self.assertTrue(any("erros em comum" in value for value in result["avisos"]))

    def test_repeated_words_keep_distant_name_and_dose_changes_visible(self):
        tokens = "tutor relata que paciente fica bem e não apresenta tosse hoje".split() * 100
        original, alternative = list(tokens), list(tokens)
        original[25], alternative[25] = "Nina", "menina"
        original[950], alternative[950] = "0,5", "5"
        differences, limited = review.comparar_leituras(" ".join(original), " ".join(alternative))
        self.assertFalse(limited)
        self.assertEqual(len(differences), 2)
        self.assertIn("Nina", differences[0]["texto_original"])
        self.assertIn("menina", differences[0]["leitura_alternativa"])
        self.assertIn("0,5", differences[1]["texto_original"])
        self.assertIn("5", differences[1]["leitura_alternativa"])
        self.assertTrue(all(len(item["texto_original"]) < 100 for item in differences))

    def test_pathological_repetition_is_limited_before_quadratic_comparison(self):
        repeated = " ".join(["mesma"] * 6000)
        with patch.object(review, "SequenceMatcher") as matcher:
            differences, limited = review.comparar_leituras(repeated, repeated)
        self.assertEqual(differences, [])
        self.assertTrue(limited)
        matcher.assert_not_called()


class PipelineReviewTests(unittest.TestCase):
    def setUp(self):
        self.samples = b"\x01\x00" * 16000 + b"\x02\x00" * 16000 + b"\x03\x00" * 8000
        self.primary = ["Nina tem tosse.", "Não dar medicamento de 0,5 mg.", "Tutor relata [inaudível]."]
        self.alternatives = ["Menina tem tosse.", "Dar medicamento de 5 mg.", "Doutor relata falta de ar."]
        self.events = []
        self.primary_samples = []
        self.review_samples = []
        self.now = 100.0
        self.provider = SimpleNamespace(transcrever=self.transcribe, transcrever_revisao=self.reread)

    def transcribe(self, **kwargs):
        self.events.append("primary")
        self.primary_samples.append(pcm(kwargs["content"]))
        return {"texto": self.primary[len(self.primary_samples) - 1], "modelo": "fake", "avisos": []}

    def reread(self, **kwargs):
        self.events.append("review")
        self.review_samples.append(pcm(kwargs["content"]))
        self.assertNotIn("paciente_nome", kwargs)
        self.assertNotIn("texto", kwargs)
        return {"texto": self.alternatives[len(self.review_samples) - 1]}

    def run_direct(self):
        def decode(content, mime, directory, **kwargs):
            path = directory / "synthetic.wav"
            path.write_bytes(wav_bytes(self.samples))
            return path
        with patch.object(direct, "_decode", side_effect=decode), \
                patch.object(direct, "CHUNK_MAX_SECONDS", 1), \
                patch.object(direct.time, "monotonic", side_effect=lambda: self.now), \
                patch.object(direct.settings, "ATENDIMENTO_IA_TIMEOUT_SECONDS", 180):
            return direct.transcrever_gravacao(nome="synthetic.wav", mime="audio/wav", content=b"synthetic",
                                              paciente_nome="Paciente Teste", provider_factory=lambda: self.provider)

    def run_batch(self):
        def decode(source, target):
            target.write_bytes(wav_bytes(self.samples))
        with patch.object(batch, "require_enabled"), \
                patch.object(batch, "_decodificar_audio", side_effect=decode), \
                patch.object(batch, "AUDIO_CHUNK_SECONDS", 1), \
                patch.object(batch, "OpenAIAtendimentoProvider", return_value=self.provider), \
                patch.object(batch.time, "monotonic", side_effect=lambda: self.now):
            return batch.processar_audio(nome="synthetic.wav", mime="audio/wav", content=wav_bytes(self.samples),
                                         paciente_nome="Paciente Teste")

    def assert_complete_review(self, result):
        self.assertEqual(result["texto"], "\n\n".join(self.primary))
        self.assertEqual(self.events, ["primary"] * 3 + ["review"] * 3)
        self.assertEqual(b"".join(self.primary_samples), self.samples)
        self.assertEqual(self.review_samples, self.primary_samples)
        metadata = result["revisao_transcricao"]
        self.assertEqual(metadata["estado"], "concluida")
        self.assertEqual(metadata["trechos_revisados"], 3)
        self.assertEqual(metadata["trechos"][-1]["fim_segundos"], 2.5)
        self.assertTrue(all(chunk["divergencias"] for chunk in metadata["trechos"]))
        for first, second in zip(metadata["trechos"], metadata["trechos"][1:]):
            self.assertEqual(first["fim_segundos"], second["inicio_segundos"])
        self.assertTrue(any("alternativas não corrigem" in value for value in result["avisos"]))

    def test_direct_all_primary_chunks_precede_review_and_source_is_exact(self):
        self.assert_complete_review(self.run_direct())

    def test_batch_all_primary_chunks_precede_review_and_source_is_exact(self):
        self.assert_complete_review(self.run_batch())

    def test_direct_secondary_timeout_keeps_full_primary_and_marks_unreviewed_chunks(self):
        def limited_reread(**kwargs):
            if self.review_samples:
                self.now += kwargs["timeout"]
                raise AssistenteError("private-provider-timeout", 504)
            return self.reread(**kwargs)
        self.provider.transcrever_revisao = limited_reread
        result = self.run_direct()
        self.assertEqual(result["texto"], "\n\n".join(self.primary))
        self.assertEqual(result["revisao_transcricao"]["estado"], "parcial")
        self.assertEqual(result["revisao_transcricao"]["trechos_revisados"], 1)
        self.assertNotIn("private-provider-timeout", json.dumps(result))
        self.assertEqual(len(self.review_samples), 1)
        self.assertEqual(result["revisao_transcricao"]["trechos"][2]["marcacoes_incerteza"], ["[inaudível]"])

    def test_no_secondary_budget_preserves_primary_without_starting_review(self):
        def exhaust_after_primary(**kwargs):
            result = self.transcribe(**kwargs)
            if len(self.primary_samples) == 3:
                self.now += kwargs["timeout"]
            return result
        self.provider.transcrever = exhaust_after_primary
        result = self.run_direct()
        self.assertEqual(result["texto"], "\n\n".join(self.primary))
        self.assertEqual(result["revisao_transcricao"]["estado"], "indisponivel")
        self.assertFalse(self.review_samples)

    def test_primary_failure_never_starts_review_or_returns_partial_text(self):
        def fail_primary(**kwargs):
            if self.primary_samples:
                raise AssistenteError("Primary failed", 502)
            return self.transcribe(**kwargs)
        self.provider.transcrever = fail_primary
        for run in (self.run_direct, self.run_batch):
            self.primary_samples = []
            with self.assertRaises(AssistenteError):
                run()
            self.assertFalse(self.review_samples)


class BatchSerializationTests(unittest.TestCase):
    def test_reviews_are_exposed_per_completed_audio_and_never_on_deleted_job(self):
        metadata = {"estado": "indisponivel", "trechos": []}
        files = [SimpleNamespace(id="audio-one", nome="synthetic.wav", tipo="audio", tamanho=10,
                                 status="completed", erro=None,
                                 resultado_json=json.dumps({"texto": "Texto literal.", "revisao_transcricao": metadata})),
                 SimpleNamespace(id="old-audio", nome="old.wav", tipo="audio", tamanho=10,
                                 status="completed", erro=None, resultado_json=json.dumps({"texto": "Antigo."})),
                 SimpleNamespace(id="failed-audio", nome="failed.wav", tipo="audio", tamanho=10,
                                 status="failed", erro="erro", resultado_json=None)]
        from datetime import datetime
        job = SimpleNamespace(id="batch", atendimento_id=1, paciente_id=2, status="completed",
                              erro=None, expires_at=datetime(2030, 1, 1), resultado_json=None, transcricao="Manual.")
        with patch.object(jobs, "_files", return_value=files), \
                patch.object(jobs, "_serialize_race_review", return_value=(None, None)):
            result = jobs.serialize(None, job)
            self.assertEqual(result["transcricao"], "Manual.\n\nTexto literal.\n\nAntigo.")
            self.assertEqual(result["revisoes_transcricao"], [{"arquivo_id": "audio-one", "nome": "synthetic.wav", "revisao_transcricao": metadata}])
            job.status = "deleting"
            deleted = jobs.serialize(None, job)
            self.assertEqual(deleted["revisoes_transcricao"], [])
            self.assertEqual(deleted["transcricao"], "")


if __name__ == "__main__":
    unittest.main()
