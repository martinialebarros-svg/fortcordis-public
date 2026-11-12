"""Inspect completion metadata before the SDK parses a clinical response.

The SDK attempts to parse output text even when generation stopped mid-JSON.
Keep its strict schema parser, but distinguish incomplete output from an invalid
completed response. No response text or validation input belongs in diagnostics.
"""
from __future__ import annotations

import logging
from typing import Any, NoReturn, get_args

from pydantic import ValidationError
from pydantic_core import ErrorType

logger = logging.getLogger(__name__)

_STATUSES = frozenset({"completed", "incomplete", "failed", "cancelled", "queued", "in_progress"})
_INCOMPLETE_REASONS = frozenset({"max_output_tokens", "content_filter"})
_ERROR_TYPES = frozenset(get_args(ErrorType))
_MESSAGES = {
    "output_limit": "A IA atingiu o limite de geração antes de concluir a resposta.",
    "incomplete": "A IA não concluiu a resposta.",
    "refusal": "A IA não forneceu uma resposta estruturada para esta solicitação.",
    "invalid_format": "A resposta concluída da IA não passou na validação de formato.",
    "invalid_response": "A IA não forneceu uma resposta estruturada válida.",
}


class StructuredResponseError(ValueError):
    """Safe failure reason; contains no provider body or clinical values."""

    def __init__(self, reason: str) -> None:
        if reason not in _MESSAGES:
            raise ValueError("Motivo de falha estruturada desconhecido.")
        self.reason = reason
        super().__init__(_MESSAGES[reason])


def _counter(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def _metadata(body: dict) -> dict:
    status = body.get("status")
    details = body.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, dict) else None
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    output_details = usage.get("output_tokens_details")
    output_details = output_details if isinstance(output_details, dict) else {}
    return {
        "status": status if isinstance(status, str) and status in _STATUSES else "unknown",
        "incomplete_reason": reason if isinstance(reason, str) and reason in _INCOMPLETE_REASONS else ("unknown" if reason is not None else None),
        "output_tokens": _counter(usage.get("output_tokens")),
        "reasoning_tokens": _counter(output_details.get("reasoning_tokens")),
    }


def _schema_fields(schema: Any) -> set[str]:
    """Only application-defined field names may appear in validation locations."""
    names: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    if hasattr(schema, "model_json_schema"):
        visit(schema.model_json_schema())
    return names


def _validation_summary(exc: ValidationError, schema: Any) -> list[dict]:
    fields = _schema_fields(schema)
    # Unknown property names can themselves contain clinical data. Redact them,
    # as well as all values, context, messages and array indices.
    return [{
        "type": error["type"] if error["type"] in _ERROR_TYPES else "validation_error",
        "loc": [part if isinstance(part, str) and part in fields else ("[]" if type(part) is int else "?")
                for part in error["loc"][:12]],
    } for error in exc.errors(include_input=False, include_context=False, include_url=False)[:8]]


def _reject(reason: str, metadata: dict, validation: list[dict] | None = None) -> NoReturn:
    logger.warning(
        "Resposta estruturada da IA rejeitada: reason=%s status=%s incomplete_reason=%s output_tokens=%s reasoning_tokens=%s validation=%s",
        reason, metadata.get("status", "unknown"), metadata.get("incomplete_reason"),
        metadata.get("output_tokens"), metadata.get("reasoning_tokens"), validation or [],
    )
    raise StructuredResponseError(reason) from None


def parse_structured_response(responses: Any, **kwargs: Any) -> Any:
    """Make one unchanged SDK request and parse only completed, non-refused output.

    Transport/provider exceptions propagate to the caller's existing handler.
    The raw body is held only in memory; diagnostics never include its content.
    """
    raw = responses.with_raw_response.parse(**kwargs)
    try:
        body = raw.http_response.json()
    except ValueError:
        _reject("invalid_response", {})
    if not isinstance(body, dict):
        _reject("invalid_response", {})
    metadata = _metadata(body)
    if metadata["status"] != "completed" or body.get("incomplete_details") is not None:
        _reject("output_limit" if metadata["incomplete_reason"] == "max_output_tokens" else "incomplete", metadata)
    outputs = body.get("output")
    if not isinstance(outputs, list) or any(not isinstance(output, dict) for output in outputs):
        _reject("invalid_response", metadata)
    for output in outputs:
        if output.get("type") != "message":
            continue
        if output.get("status") != "completed":
            _reject("incomplete", metadata)
        content = output.get("content")
        if not isinstance(content, list) or any(not isinstance(item, dict) for item in content):
            _reject("invalid_response", metadata)
        if any(item.get("type") == "refusal" for item in content):
            _reject("refusal", metadata)
    try:
        response = raw.parse()
    except ValidationError as exc:
        _reject("invalid_format", metadata, _validation_summary(exc, kwargs.get("text_format")))
    if getattr(response, "output_parsed", None) is None:
        _reject("invalid_response", metadata)
    return response
