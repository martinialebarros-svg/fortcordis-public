"""Schemas do chatbot de atendimento do WhatsApp (Fase 4).

A allowlist de intent da RF-019 vive aqui como `Literal`: com
`text_format=WhatsAppBotReplyOutput` na chamada ao provider, o modelo nao
consegue EMITIR uma intent fora da lista - deixa de ser trabalho do
validador de saida. O que o validador ainda checa e se a intent emitida e
elegivel a `auto` NAQUELA persona (RF-019) e se o texto respeita os
guardrails clinicos (RF-022).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Teto de sanidade do schema. O teto real da RF-025
# (WHATSAPP_BOT_MAX_REPLY_CHARS, default 900) e aplicado no guardrail, para
# ser sobreponivel em teste sem mexer no schema.
REPLY_HARD_MAX_CHARS = 4000

WhatsAppBotIntent = Literal[
    # Institucional - elegivel a `auto` nas duas personas.
    "horario_funcionamento",
    "endereco",
    "clinica_proxima",
    "area_atendimento",
    "formas_contato",
    "preco_servico",
    "status_laudo",
    # Especificas de persona.
    "solicitar_agendamento",
    "como_agendar",           # tutor
    "como_solicitar_exame",   # clinica
    # Bloco comum que SEMPRE vira rascunho (RF-019), mesmo com o dado
    # disponivel no contexto.
    "ordem_servico",
    "cobranca",
    "valor_em_aberto",
    "repasse_negociacao",
    # Fallback: qualquer coisa que o modelo nao consiga classificar.
    "outro",
]

WhatsAppBotPersona = Literal["tutor", "clinica"]


class WhatsAppBotStrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WhatsAppBotColetaAgendamento(WhatsAppBotStrictSchema):
    exame: str | None = Field(default=None, max_length=120)
    paciente: str | None = Field(default=None, max_length=120)
    tutor: str | None = Field(default=None, max_length=120)
    preferencia: str | None = Field(default=None, max_length=160)


class WhatsAppBotReplyOutput(WhatsAppBotStrictSchema):
    """Saida estruturada exigida do provider.

    `fontes` e declaratorio: e o que o MODELO afirma ter usado. O guardrail
    nao confia nisso - compara contra as tools que de fato rodaram no turno
    (RF-020). Serve para detectar divergencia, nao para autorizar.
    """

    intent: WhatsAppBotIntent
    texto: str = Field(min_length=1, max_length=REPLY_HARD_MAX_CHARS)
    fontes: list[str] = Field(default_factory=list)
    precisa_humano: bool = False
    solicitacao_agendamento: WhatsAppBotColetaAgendamento | None = None
