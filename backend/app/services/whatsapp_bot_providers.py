"""Provider de geracao do chatbot de atendimento (Fase 4).

Molde: `ai_echo_providers.py` (Protocol + factory por string + erro unico com
`code`). Diferencas deliberadas em relacao ao assistente IA interno:

- `store=False` e historico enviado explicitamente. O assistente interno usa
  `store=True` + `previous_response_id`, o que deixaria dado de tutor e de
  paciente retido no servidor do provider.
- `safety_identifier` derivado da identidade do WhatsApp, nao de um usuario
  admin.
- Teto de 2 rodadas de tools (o assistente permite 7). O orquestrador decide
  o fallback seguro quando o modelo excede esse teto.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from app.core.config import settings
from app.schemas.whatsapp_bot import WhatsAppBotReplyOutput

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 2

# O worker roda a cada WHATSAPP_BOT_SCHEDULER_POLL_SECONDS (default 5s) e o
# job tem debounce proprio; um timeout generoso aqui so atrasaria a deteccao
# de provider travado. 60s e o mesmo teto que o ai-echo usa para
# estruturacao (AI_ECHO_PROVIDER_TIMEOUT_SECONDS default 90) reduzido, ja que
# resposta de WhatsApp e curta.
PROVIDER_TIMEOUT_SECONDS = 60


class WhatsAppBotProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_unavailable") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GeneratedReply:
    """Saida do provider, com o metadado que o registro da RF-026 exige."""

    output: Optional[WhatsAppBotReplyOutput]
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    continuation_input: list[Any] = field(default_factory=list)


class WhatsAppBotReplyProvider(Protocol):
    def generate(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        tools: list[dict[str, Any]],
        safety_scope: str,
        continuation_input: Optional[list[Any]] = None,
    ) -> GeneratedReply:
        ...


def _safe_provider_error(exc: Exception) -> WhatsAppBotProviderError:
    """Classificacao por substring, sem importar tipos do SDK.

    Ordem copiada do ai-echo, inclusive a decisao de checar quota ANTES de
    rate limit (um 429 de quota esgotada nao pode virar "tente mais tarde").
    """
    nome = type(exc).__name__.lower()
    mensagem = str(exc).lower()
    if "timeout" in nome or "timeout" in mensagem:
        return WhatsAppBotProviderError("Tempo esgotado ao gerar a resposta.", code="provider_timeout")
    if any(t in mensagem for t in ("authentication", "api key", "401")):
        return WhatsAppBotProviderError("Provider de IA nao configurado.", code="provider_not_configured")
    if any(t in mensagem for t in ("insufficient_quota", "current quota", "run out of credits", "no balance left")):
        return WhatsAppBotProviderError("Cota do provider de IA esgotada.", code="provider_quota_exhausted")
    if "rate" in nome or "429" in mensagem:
        return WhatsAppBotProviderError("Provider de IA sob limite de uso.", code="provider_rate_limited")
    return WhatsAppBotProviderError("Provider de IA indisponivel.", code="provider_unavailable")


class OpenAIWhatsAppBotProvider:
    """Implementacao real. Nao herda o Protocol (conformidade estrutural)."""

    def __init__(self) -> None:
        from openai import OpenAI

        self.model = str(settings.WHATSAPP_BOT_MODEL or "").strip()
        self.client = OpenAI(
            api_key=str(settings.OPENAI_API_KEY or "").strip(),
            timeout=float(PROVIDER_TIMEOUT_SECONDS),
            max_retries=1,
        )

    def generate(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        tools: list[dict[str, Any]],
        safety_scope: str,
        continuation_input: Optional[list[Any]] = None,
    ) -> GeneratedReply:
        safety_identifier = hashlib.sha256(
            f"fortcordis-whatsapp-bot:{safety_scope}".encode("utf-8")
        ).hexdigest()[:64]
        try:
            request_input: list[Any] = list(continuation_input or [])
            if not request_input:
                request_input = [
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, default=str),
                    }
                ]

            response = self.client.responses.parse(
                model=self.model,
                instructions=instructions,
                input=request_input,
                text_format=WhatsAppBotReplyOutput,
                tools=tools or None,
                parallel_tool_calls=False,
                max_output_tokens=1200,
                safety_identifier=safety_identifier,
                store=False,
            )
        except Exception as exc:  # noqa: BLE001 - classificado abaixo
            raise _safe_provider_error(exc) from exc

        response_output = list(getattr(response, "output", None) or [])
        tool_calls = [
            {
                "call_id": getattr(item, "call_id", None),
                "name": getattr(item, "name", None),
                "arguments": getattr(item, "arguments", "{}"),
            }
            for item in response_output
            if getattr(item, "type", None) == "function_call"
        ]
        parsed = getattr(response, "output_parsed", None)
        if parsed is None and not tool_calls:
            raise WhatsAppBotProviderError(
                "Resposta do provider fora do formato esperado.", code="invalid_structured_output"
            )
        usage = getattr(response, "usage", None)
        return GeneratedReply(
            output=parsed,
            model=self.model,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            tool_calls=tool_calls,
            # Com `store=False`, o proximo turno precisa reenviar a entrada e
            # todos os itens de saida (inclusive reasoning/function_call).
            continuation_input=[*request_input, *response_output],
        )


def get_whatsapp_bot_reply_provider() -> WhatsAppBotReplyProvider:
    """Factory por string, no padrao do ai-echo (sem singleton, sem cache).

    E este ponto que os testes trocam por um fake.
    """
    provider = str(settings.AI_PROVIDER or "").strip().lower()
    if provider == "openai":
        return OpenAIWhatsAppBotProvider()
    raise WhatsAppBotProviderError(
        f"Provider de IA nao suportado: {provider or 'vazio'}", code="unsupported_provider"
    )
