"""Literal primary ASR and blind review contracts; entirely synthetic content."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "synthetic-review-test-key")

from app.services import atendimento_assistente as service


class ReviewProviderTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        factory = patch.object(service, "OpenAI", return_value=self.client)
        self.openai = factory.start()
        self.addCleanup(factory.stop)
        self.provider = service.OpenAIAtendimentoProvider()

    def test_primary_preserves_unusual_names_doses_units_and_uncertainty(self):
        text = "Bento, não Nébula. [incerto: fármaco X] 0,05 mg, não 5 mg. [inaudível]"
        self.client.audio.transcriptions.create.return_value = SimpleNamespace(text=text)
        result = self.provider.transcrever(nome="ficticio.wav", mime="audio/wav", content=b"synthetic", paciente_nome="Nébula")
        self.assertEqual(result["texto"], text)
        args = self.client.audio.transcriptions.create.call_args.kwargs
        self.assertIn("não calcule doses", args["prompt"])
        self.assertIn("não acrescente nomes ausentes", args["prompt"])
        self.assertIn("[inaudível]", args["prompt"])
        self.assertIn("[incerto: palavra ouvida]", args["prompt"])
        self.assertEqual(self.openai.call_args.kwargs["max_retries"], 0)

    def test_review_is_blind_to_registered_name_primary_and_vocabulary(self):
        self.client.audio.transcriptions.create.side_effect = [
            SimpleNamespace(text="Nébula recebe 0,05 mg."), SimpleNamespace(text="Bento recebe 0,5 mg.")]
        primary = self.provider.transcrever(nome="ficticio.wav", mime="audio/wav", content=b"same-wav", paciente_nome="Nébula")
        review = self.provider.transcrever_revisao(nome="ficticio.wav", mime="audio/wav", content=b"same-wav", timeout=7.5)
        first, second = [call.kwargs for call in self.client.audio.transcriptions.create.call_args_list]
        self.assertEqual(second["file"], first["file"])
        self.assertEqual(second["extra_body"], {"languages": ["pt"]})
        self.assertNotIn("Nébula", str(second))
        self.assertNotIn(primary["texto"], str(second))
        self.assertNotIn("logprobs", second)
        self.assertEqual(second["timeout"], 7.5)
        self.assertEqual(primary["texto"], "Nébula recebe 0,05 mg.")
        self.assertEqual(review["texto"], "Bento recebe 0,5 mg.")

    def test_primary_does_not_insert_absent_name(self):
        text = "Tutora relata melhora, sem medicação."
        self.client.audio.transcriptions.create.return_value = SimpleNamespace(text=text)
        self.assertEqual(self.provider.transcrever(nome="ficticio.wav", mime="audio/wav", content=b"synthetic", paciente_nome="Nébula")["texto"], text)

    def test_invalid_review_and_provider_error_do_not_retry(self):
        for response in [SimpleNamespace(text=""), SimpleNamespace(text="x" * (service.TRANSCRICAO_MAX_CHARS + 1))]:
            self.client.audio.transcriptions.create.reset_mock()
            self.client.audio.transcriptions.create.return_value = response
            with self.assertRaises(service.AssistenteError):
                self.provider.transcrever_revisao(nome="ficticio.wav", mime="audio/wav", content=b"synthetic", timeout=1)
            self.assertEqual(self.client.audio.transcriptions.create.call_count, 1)
        self.client.audio.transcriptions.create.reset_mock()
        self.client.audio.transcriptions.create.side_effect = TimeoutError("synthetic")
        with self.assertRaises(service.AssistenteError):
            self.provider.transcrever_revisao(nome="ficticio.wav", mime="audio/wav", content=b"synthetic", timeout=1)
        self.assertEqual(self.client.audio.transcriptions.create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
