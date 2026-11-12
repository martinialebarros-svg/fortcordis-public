"""Simulacao de resposta do bot (Fase 6, painel de configuracao).

Permite ver o que o bot responderia a uma pergunta, sem enviar nada e sem
contaminar as metricas.

Duas decisoes que importam:

- **Nao persiste.** `gerar_resposta` normalmente tem seu resultado gravado em
  `whatsapp_bot_respostas` pelo worker. Aqui nada e gravado: se a simulacao
  entrasse na tabela, ela apareceria como rascunho na central e entraria no
  denominador de aceite das metricas - contaminando exatamente o numero que
  autoriza o modo `auto`.
- **Nao envia.** `gerar_resposta` nao tem caminho de envio nesta fase, mas a
  simulacao tambem nao passa por `_process_job`, portanto nao toca conversa,
  nao pausa nada e nao cria job.

Custa tokens de verdade: e uma chamada real ao provider.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.services.whatsapp_bot_generation import gerar_resposta

logger = logging.getLogger(__name__)

# Identidade sintetica usada apenas para a simulacao. Nunca casa cadastro real
# (fora do formato de telefone valido do resolvedor), entao o contexto resolve
# como `not_found` e nenhum dado de cliente entra na simulacao.
_IDENTIDADE_SIMULACAO = "000000000000"


def simular_resposta(
    db: Session,
    *,
    mensagem: str,
    persona: str,
    historico: Optional[list[dict[str, Any]]] = None,
    solicitado_por_id: Optional[int] = None,
) -> dict[str, Any]:
    """Executa o pipeline de geracao em modo somente-leitura."""
    texto = str(mensagem or "").strip()
    if len(texto) < 3:
        raise ValueError("Mensagem muito curta para simular.")
    if persona not in ("tutor", "clinica"):
        raise ValueError("Persona invalida para simulacao.")

    resultado = gerar_resposta(
        db,
        wa_identity=_IDENTIDADE_SIMULACAO,
        corpo_mensagem=texto,
        modo="suggest",
        persona_forcada=persona,
        # Sem isso a memoria de conversa seria intestavel pelo painel: so
        # daria para verifica-la numa conversa real de WhatsApp.
        historico=historico,
    )

    return {
        "simulacao": True,
        "persona": persona,
        "mensagem": texto,
        "historico_usado": len(historico or []),
        "decisao": resultado.decisao,
        "motivo": resultado.motivo,
        "texto_gerado": resultado.texto_gerado,
        "modelo": resultado.modelo,
        "prompt_version": resultado.prompt_version,
        "tools_usadas": resultado.tools_usadas,
        "input_tokens": resultado.input_tokens,
        "output_tokens": resultado.output_tokens,
        "latencia_ms": resultado.latencia_ms,
        "observacao": (
            "Simulacao: nada foi enviado ao cliente e nada foi gravado em "
            "whatsapp_bot_respostas, para nao contaminar as metricas de aceite."
        ),
    }
