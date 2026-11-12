"""Prontidao do bot por intent e persona (Fase 6, painel de configuracao).

Responde uma pergunta que hoje nao tem resposta em lugar nenhum do produto:
*o bot consegue responder isso agora?* E, quando nao consegue, *o que falta?*

Sem isso, cadastrar conteudo e trabalho as cegas: o admin preenche a base, o
bot continua dizendo que nao sabe, e nada no sistema explica o motivo. Foi
exatamente o que a regressao do piso de relevancia produziu por tres fases.

Custo: ZERO chamada de LLM. Cada intent e verificada rodando a TOOL que a
sustenta (`_FONTE_EXIGIDA_POR_INTENT`), todas somente leitura.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.services.whatsapp_bot_gates import is_whatsapp_bot_enabled
from app.services.whatsapp_bot_guardrails import (
    _FONTE_EXIGIDA_POR_INTENT,
    INTENTS_ATENDIDAS_POR_PERSONA,
    INTENTS_AUTO_POR_PERSONA,
)
from app.services.whatsapp_bot_tools import (
    TOOLS_POR_PERSONA,
    WhatsAppBotToolContext,
    execute_bot_tool,
)

logger = logging.getLogger(__name__)

# Pergunta representativa por intent, usada só para sondar a fonte. Não é
# enviada a modelo nenhum: serve de consulta para a tool de conhecimento e de
# rótulo legível no painel.
PERGUNTA_SONDA: dict[str, str] = {
    "clinica_proxima": "qual clinica parceira fica perto de mim?",
    "horario_funcionamento": "qual o horario de funcionamento?",
    "endereco": "qual o endereco de voces?",
    "formas_contato": "como falo com voces?",
    "preco_servico": "quanto custa o ecocardiograma?",
    "status_laudo": "o laudo do meu pet ja saiu?",
    "area_atendimento": "voces atendem na minha regiao?",
    "como_agendar": "como faco para agendar uma consulta?",
    "como_solicitar_exame": "como solicito um exame para um paciente?",
}

ROTULO_INTENT: dict[str, str] = {
    "clinica_proxima": "Indicar clinica parceira perto do cliente",
    "horario_funcionamento": "Horario de funcionamento",
    "endereco": "Endereco",
    "formas_contato": "Formas de contato",
    "preco_servico": "Preco de servico (tabela)",
    "status_laudo": "Status de laudo (pronto / ainda nao)",
    "area_atendimento": "Area de atendimento",
    "como_agendar": "Como agendar",
    "como_solicitar_exame": "Como solicitar exame",
}

# Campo do cadastro institucional que cada intent exige de fato. A tool
# `consultar_dados_institucionais` sustenta duas intents com dados diferentes:
# ficar so no `ok` dela reporta verde sem endereco e sem telefone.
_CAMPO_EXIGIDO_POR_INTENT: dict[str, str] = {
    "endereco": "tem_endereco",
    "formas_contato": "tem_contato",
}

FALTA_CAMPO_INSTITUCIONAL: dict[str, str] = {
    "tem_endereco": (
        "Endereco vazio em Configuracoes > Empresa. Cidade e estado nao bastam: "
        "o cliente precisa do logradouro para chegar."
    ),
    "tem_contato": (
        "Telefone e e-mail vazios em Configuracoes > Empresa. Preencha ao menos "
        "um para o bot poder dizer como falar com uma pessoa."
    ),
}

# Onde o admin resolve cada falta. Texto de produto, nao de log.
COMO_RESOLVER: dict[str, str] = {
    "consultar_dados_institucionais": (
        "Preencha endereco, telefone e e-mail em Configuracoes > Empresa."
    ),
    "consultar_horario_funcionamento": (
        "Preencha a agenda semanal em Configuracoes > Agendamento."
    ),
    "consultar_preco_tabela": (
        "Cadastre servicos ativos com preco comercial maior que zero na regiao "
        "atendida. Para tutor, a regiao sondada e `domiciliar` (tabela 3): a "
        "tabela praticada com clinicas nao e informada ao consumidor final."
    ),
    "consultar_status_laudo": (
        "Depende de exame cadastrado no escopo da conversa; nao ha o que "
        "configurar previamente."
    ),
    "buscar_clinica_parceira": (
        "Cadastre clinicas parceiras ativas com bairro e endereco preenchidos "
        "em Clinicas."
    ),
    "buscar_conhecimento_institucional": (
        "Cadastre um documento na base com categoria comecando por "
        "'institucional' ou 'atendimento' e com a fonte preenchida."
    ),
}


def _diagnostico_do_resultado(nome_tool: str, resultado: dict[str, Any]) -> Optional[str]:
    """Traduz a falha da tool em algo acionavel para quem le o painel."""
    if resultado.get("ok"):
        return None
    descartados = resultado.get("descartados") or {}
    if descartados.get("categoria"):
        return (
            f"{descartados['categoria']} documento(s) encontrado(s), mas com "
            "categoria fora da audiencia do bot (o default 'manual' nao vale). "
            "Use categoria comecando por 'institucional' ou 'atendimento'."
        )
    if descartados.get("sem_fonte"):
        return (
            f"{descartados['sem_fonte']} documento(s) encontrado(s) sem o campo "
            "Fonte preenchido. O bot precisa citar fonte, entao descarta."
        )
    if descartados.get("pouco_relevante"):
        return (
            f"{descartados['pouco_relevante']} documento(s) encontrado(s), mas "
            "pouco relevante(s) para a pergunta. Inclua no texto os termos que o "
            "cliente usaria."
        )
    return COMO_RESOLVER.get(nome_tool) or str(resultado.get("error") or "Fonte indisponivel.")


def _sondar_intent(
    ctx: WhatsAppBotToolContext, persona: str, intent: str
) -> dict[str, Any]:
    fontes = _FONTE_EXIGIDA_POR_INTENT.get(intent) or frozenset()
    nome_tool = next(iter(sorted(fontes)), None)

    item: dict[str, Any] = {
        "intent": intent,
        "rotulo": ROTULO_INTENT.get(intent, intent),
        "pergunta_exemplo": PERGUNTA_SONDA.get(intent),
        "tool": nome_tool,
        "auto_elegivel": intent in (INTENTS_AUTO_POR_PERSONA.get(persona) or frozenset()),
    }

    if nome_tool is None:
        item.update({"pronto": False, "diagnostico": "Intent sem fonte declarada."})
        return item
    if nome_tool not in (TOOLS_POR_PERSONA.get(persona) or {}):
        item.update({"pronto": False, "diagnostico": "Ferramenta indisponivel nesta persona."})
        return item

    argumentos: dict[str, Any] = {}
    if nome_tool == "buscar_conhecimento_institucional":
        argumentos["consulta"] = PERGUNTA_SONDA.get(intent) or intent
    if nome_tool == "consultar_preco_tabela" and persona == "tutor":
        # Tutor so pode ser cotado em `domiciliar`: as tabelas 1 e 2 sao
        # preco praticado com clinica parceira e nao vao para o consumidor
        # final. Sondar `fortaleza` daria verde por uma fonte que a persona
        # nao tem direito de usar - falso verde da mesma familia do de
        # 2026-08-23. Se a tabela domiciliar estiver vazia, o painel fica
        # vermelho, e esta certo: o bot nao consegue responder preco a tutor.
        argumentos["regiao"] = "domiciliar"

    try:
        resultado = execute_bot_tool(ctx, nome_tool, argumentos)
    except Exception:
        logger.exception("Falha ao sondar prontidao da intent %s.", intent)
        item.update({"pronto": False, "diagnostico": "Falha ao consultar a fonte."})
        return item

    pronto = bool(resultado.get("ok"))

    # Uma tool, duas intents: `consultar_dados_institucionais` pode estar `ok`
    # com endereco e sem telefone, ou o contrario. Sem esta checagem por campo
    # a prontidao volta a dar o falso verde que stage exibiu em 2026-08-23.
    campo_exigido = _CAMPO_EXIGIDO_POR_INTENT.get(intent)
    if pronto and campo_exigido and not resultado.get(campo_exigido):
        item.update({
            "pronto": False,
            "diagnostico": FALTA_CAMPO_INSTITUCIONAL[campo_exigido],
        })
        return item

    item["pronto"] = pronto
    item["diagnostico"] = None if pronto else _diagnostico_do_resultado(nome_tool, resultado)
    return item


def coletar_prontidao(
    db: Session, *, tutor_id_exemplo: Optional[int] = None, clinica_id_exemplo: Optional[int] = None
) -> dict[str, Any]:
    """Prontidao das duas personas.

    `status_laudo` depende de dado da conversa real (o exame do cliente), nao
    de configuracao previa. Sondamos com um escopo de exemplo quando informado;
    sem ele, a intent e reportada como dependente de conversa em vez de
    falsamente pronta ou falsamente quebrada.
    """
    resultado: dict[str, Any] = {
        "bot_ativo": is_whatsapp_bot_enabled(),
        "personas": {},
    }

    escopos = {
        "tutor": ("tutor", tutor_id_exemplo or 0, None),
        "clinica": ("clinica", None, clinica_id_exemplo or 0),
    }

    for persona, (match_type, tutor_id, clinica_id) in escopos.items():
        # Escopo sintetico: id 0 nunca casa registro real, entao as tools de
        # dado do cliente devolvem vazio sem vazar nada de ninguem. As tools
        # institucionais nao dependem do escopo.
        ctx = WhatsAppBotToolContext(
            db=db,
            match_type=match_type,  # type: ignore[arg-type]
            tutor_id=tutor_id if match_type == "tutor" else None,
            clinica_id=clinica_id if match_type == "clinica" else None,
        )
        itens = []
        # Sonda tudo que o bot ATENDE. Uma intent fora do `auto` continua
        # precisando de fonte sa - so nao sai sem revisao humana.
        for intent in sorted(INTENTS_ATENDIDAS_POR_PERSONA.get(persona) or frozenset()):
            item = _sondar_intent(ctx, persona, intent)
            if intent == "status_laudo" and not item.get("pronto"):
                item["diagnostico"] = (
                    "Depende do exame do cliente na conversa real; nao ha "
                    "configuracao previa. Verifique com uma conversa de teste."
                )
                item["depende_da_conversa"] = True
            itens.append(item)

        prontos = [i for i in itens if i.get("pronto")]
        resultado["personas"][persona] = {
            "itens": itens,
            "total": len(itens),
            "prontos": len(prontos),
            "pendentes": len(itens) - len(prontos),
        }

    total = sum(p["total"] for p in resultado["personas"].values())
    prontos = sum(p["prontos"] for p in resultado["personas"].values())
    resultado["resumo"] = {
        "total": total,
        "prontos": prontos,
        "pendentes": total - prontos,
        "observacao": (
            "Prontidao mede se a FONTE existe, nao se a resposta e boa. "
            "Qualidade so aparece na observacao em `suggest`."
        ),
    }
    return resultado
