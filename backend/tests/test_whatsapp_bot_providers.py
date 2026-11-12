import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-provider-test-secret-key-1234567890")

from app.schemas.whatsapp_bot import WhatsAppBotReplyOutput
from app.services.whatsapp_bot_providers import OpenAIWhatsAppBotProvider


class OpenAIWhatsAppBotProviderTest(unittest.TestCase):
    def _provider(self, *responses):
        provider = OpenAIWhatsAppBotProvider.__new__(OpenAIWhatsAppBotProvider)
        provider.model = "fake-model"
        provider.client = SimpleNamespace(
            responses=SimpleNamespace(parse=Mock(side_effect=list(responses)))
        )
        return provider

    def test_function_call_retorna_continuacao_stateless(self) -> None:
        call = SimpleNamespace(
            type="function_call",
            call_id="call-1",
            name="consultar_preco_tabela",
            arguments='{"servico_nome":"Eco","regiao":"fortaleza"}',
        )
        response = SimpleNamespace(
            output=[call],
            output_parsed=None,
            usage=SimpleNamespace(input_tokens=30, output_tokens=5),
        )
        provider = self._provider(response)

        gerado = provider.generate(
            instructions="instrucoes",
            payload={"mensagem": "quanto custa?"},
            tools=[{"type": "function", "name": "consultar_preco_tabela"}],
            safety_scope="5585999990001",
        )

        self.assertIsNone(gerado.output)
        self.assertEqual(gerado.tool_calls[0]["call_id"], "call-1")
        self.assertEqual(gerado.tool_calls[0]["name"], "consultar_preco_tabela")
        self.assertEqual(gerado.continuation_input[-1], call)
        request_input = provider.client.responses.parse.call_args.kwargs["input"]
        self.assertEqual(request_input[0]["role"], "user")

    def test_turno_final_reenvia_continuacao_e_parseia_schema(self) -> None:
        parsed = WhatsAppBotReplyOutput(
            texto="Atendimento automatico da FortCordis.",
            intent="formas_contato",
            fontes=["consultar_dados_institucionais"],
        )
        response = SimpleNamespace(
            output=[SimpleNamespace(type="message")],
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=50, output_tokens=20),
        )
        provider = self._provider(response)
        continuation = [
            {"role": "user", "content": "mensagem"},
            {"type": "function_call_output", "call_id": "call-1", "output": "{}"},
        ]

        gerado = provider.generate(
            instructions="instrucoes",
            payload={"ignorado": True},
            tools=[],
            safety_scope="5585999990001",
            continuation_input=continuation,
        )

        self.assertEqual(gerado.output, parsed)
        self.assertEqual(provider.client.responses.parse.call_args.kwargs["input"], continuation)
        self.assertEqual(gerado.input_tokens, 50)
        self.assertEqual(gerado.output_tokens, 20)


if __name__ == "__main__":
    unittest.main()
