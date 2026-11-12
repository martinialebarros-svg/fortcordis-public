from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from openai import OpenAI
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.ai_echo import EchoClinicalStructureOutput
from app.services.ai_echo_context import safe_measurement_context, safe_reference_context
from app.services.ai_echo_prompt import (
    build_clinical_structuring_instructions,
    build_transcription_prompt,
)


class AIEchoProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_unavailable") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str
    confidence: float | None
    model: str


@dataclass(frozen=True)
class StructuringResult:
    output: EchoClinicalStructureOutput
    model: str
    provider_response_id: str | None
    input_tokens: int | None
    output_tokens: int | None


class SpeechToTextProvider(Protocol):
    def transcribe(
        self,
        *,
        file_name: str,
        content_type: str,
        audio_bytes: bytes,
        vocabulary: list[dict[str, Any]],
    ) -> TranscriptionResult: ...


class ClinicalStructuringProvider(Protocol):
    def structure(
        self,
        *,
        transcript: str,
        phrase_preferences: list[dict[str, Any]],
        safety_user_id: int,
        current_measurements: dict[str, str] | None = None,
        exam_context: dict[str, Any] | None = None,
        reference_context: dict[str, Any] | None = None,
    ) -> StructuringResult: ...


def _safe_provider_error(exc: Exception) -> AIEchoProviderError:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timeout" in message:
        return AIEchoProviderError(
            "O serviço de inteligência artificial excedeu o tempo de resposta. Tente novamente.",
            code="provider_timeout",
        )
    if "authentication" in name or "api key" in message or "401" in message:
        return AIEchoProviderError(
            "O serviço de inteligência artificial não está configurado para este ambiente.",
            code="provider_not_configured",
        )
    if (
        "insufficient_quota" in message
        or "current quota" in message
        or "run out of credits" in message
        or "no balance left" in message
    ):
        return AIEchoProviderError(
            "A cota do serviço de inteligência artificial foi esgotada. "
            "O laudo manual continua disponível.",
            code="provider_quota_exhausted",
        )
    if "rate" in name or "429" in message:
        return AIEchoProviderError(
            "O limite temporário do serviço de inteligência artificial foi atingido. Tente mais tarde.",
            code="provider_rate_limited",
        )
    return AIEchoProviderError(
        "O serviço de inteligência artificial está indisponível no momento. "
        "O laudo manual continua disponível.",
        code="provider_unavailable",
    )


class OpenAISpeechToTextProvider:
    def __init__(self) -> None:
        self.model = str(settings.AI_TRANSCRIPTION_MODEL or "").strip()
        self.client = OpenAI(
            api_key=str(settings.OPENAI_API_KEY or "").strip(),
            timeout=float(settings.AI_ECHO_PROVIDER_TIMEOUT_SECONDS),
            max_retries=1,
        )

    def transcribe(
        self,
        *,
        file_name: str,
        content_type: str,
        audio_bytes: bytes,
        vocabulary: list[dict[str, Any]],
    ) -> TranscriptionResult:
        try:
            response = self.client.audio.transcriptions.create(
                model=self.model,
                file=(file_name, audio_bytes, content_type),
                language="pt",
                response_format="json",
                prompt=build_transcription_prompt(vocabulary),
            )
        except Exception as exc:
            raise _safe_provider_error(exc) from exc
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise AIEchoProviderError(
                "Não foi possível compreender o áudio. Grave novamente em um ambiente mais silencioso.",
                code="empty_transcription",
            )
        return TranscriptionResult(
            text=text,
            language="pt-BR",
            confidence=None,
            model=self.model,
        )


class OpenAIClinicalStructuringProvider:
    def __init__(self) -> None:
        self.model = str(settings.AI_STRUCTURING_MODEL or "").strip()
        self.client = OpenAI(
            api_key=str(settings.OPENAI_API_KEY or "").strip(),
            timeout=float(settings.AI_ECHO_PROVIDER_TIMEOUT_SECONDS),
            max_retries=1,
        )

    def structure(
        self,
        *,
        transcript: str,
        phrase_preferences: list[dict[str, Any]],
        safety_user_id: int,
        current_measurements: dict[str, str] | None = None,
        exam_context: dict[str, Any] | None = None,
        reference_context: dict[str, Any] | None = None,
    ) -> StructuringResult:
        safety_identifier = hashlib.sha256(
            f"fortcordis-echo:{safety_user_id}".encode("utf-8")
        ).hexdigest()[:64]
        reasoning_effort = str(
            settings.AI_ECHO_REASONING_EFFORT or "low"
        ).strip().lower()
        allowed_reasoning_efforts = {
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }
        if reasoning_effort not in allowed_reasoning_efforts:
            reasoning_effort = "low"
        try:
            response = self.client.responses.parse(
                model=self.model,
                instructions=build_clinical_structuring_instructions(
                    phrase_preferences=phrase_preferences
                ),
                input=json.dumps(
                    {
                        "language": "pt-BR",
                        "transcript": transcript,
                        "exam_context": exam_context or {},
                        "reference_context": safe_reference_context(
                            reference_context, current_measurements=current_measurements,
                            species=(exam_context or {}).get("species"),
                        ),
                        "current_measurements": safe_measurement_context(
                            current_measurements,
                            species=(exam_context or {}).get("species"),
                            reference_context=reference_context,
                        ),
                    },
                    ensure_ascii=False,
                ),
                text_format=EchoClinicalStructureOutput,
                reasoning={"effort": reasoning_effort},
                max_output_tokens=int(settings.AI_ECHO_MAX_OUTPUT_TOKENS),
                safety_identifier=safety_identifier,
                store=False,
            )
        except ValidationError as exc:
            raise AIEchoProviderError(
                "A resposta clínica veio fora do formato seguro esperado. "
                "Tente gerar as sugestões novamente.",
                code="invalid_structured_output",
            ) from exc
        except Exception as exc:
            raise _safe_provider_error(exc) from exc

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise AIEchoProviderError(
                "A resposta clínica veio incompleta e foi descartada com segurança.",
                code="invalid_structured_output",
            )
        try:
            output = EchoClinicalStructureOutput.model_validate(parsed)
        except Exception as exc:
            raise AIEchoProviderError(
                "A resposta clínica não corresponde ao formato seguro esperado.",
                code="invalid_structured_output",
            ) from exc

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None
        return StructuringResult(
            output=output,
            model=self.model,
            provider_response_id=str(getattr(response, "id", "") or "") or None,
            input_tokens=int(input_tokens) if input_tokens is not None else None,
            output_tokens=int(output_tokens) if output_tokens is not None else None,
        )


def get_speech_to_text_provider() -> SpeechToTextProvider:
    provider = str(settings.AI_PROVIDER or "").strip().lower()
    if provider == "openai":
        return OpenAISpeechToTextProvider()
    raise AIEchoProviderError(
        "O provedor de transcrição configurado não é suportado.",
        code="unsupported_provider",
    )


def get_clinical_structuring_provider() -> ClinicalStructuringProvider:
    provider = str(settings.AI_PROVIDER or "").strip().lower()
    if provider == "openai":
        return OpenAIClinicalStructuringProvider()
    raise AIEchoProviderError(
        "O provedor de estruturação configurado não é suportado.",
        code="unsupported_provider",
    )
