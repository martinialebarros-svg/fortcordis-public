"""Metricas de observacao do chatbot de atendimento (Fase 6, P6.3/P6.5).

Objetivo: transformar `whatsapp_bot_respostas` em numeros que autorizem (ou
nao) o modo `auto`. O plan.md e explicito: "decisao de release documentada com
numeros, nao com impressao".

Decisoes de desenho que importam para a leitura correta do painel:

- Somente leitura. Nenhuma linha e criada, alterada ou apagada aqui.
- "Aceite" e medido sobre rascunhos JA DECIDIDOS (enviado ou descartado).
  Rascunho pendente nao entra no denominador, senao a taxa comeca baixa e
  sobe sozinha conforme a equipe trabalha, o que nao mede qualidade.
- "Editado" e derivado de `texto_enviado != texto_gerado`. O endpoint de
  envio grava `feedback="positivo"` mesmo quando o atendente reescreveu o
  texto, portanto o feedback sozinho superestima o aceite limpo.
- A faixa de horario usa a janela operacional da agenda
  (`is_within_operating_window`), a mesma fonte do texto de handoff (RF-033).
  Isso mantem "dentro/fora do expediente" consistente com o que o cliente
  ouve, e nao um horario comercial legado paralelo.
- Custo: com as taxas em 0.0 (default), `custo_configurado` e False e o
  valor nao e apresentado como se fosse zero real.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.whatsapp_bot import WhatsAppBotResposta
from app.services.assistente_ia_tools import (
    LOCAL_TZ,
    _agenda_configuration_rules,
    _agenda_day_window,
)
from app.services.whatsapp_bot_handoff_service import (
    _parse_hhmm,
    is_within_operating_window,
)

logger = logging.getLogger(__name__)

JANELA_PADRAO_DIAS = 7

# Decisoes que representam um rascunho oferecido a equipe.
_DECISOES_RASCUNHO = ("draft", "sent")


@dataclass(frozen=True)
class _Classificacao:
    aceito: bool
    editado: bool
    descartado: bool
    pendente: bool


def _classificar(resposta: WhatsAppBotResposta) -> _Classificacao:
    if resposta.motivo == "enviado_auto":
        return _Classificacao(aceito=False, editado=False, descartado=False, pendente=False)
    if resposta.decisao == "sent":
        gerado = (resposta.texto_gerado or "").strip()
        enviado = (resposta.texto_enviado or "").strip()
        return _Classificacao(
            aceito=True,
            editado=bool(enviado) and enviado != gerado,
            descartado=False,
            pendente=False,
        )
    if resposta.decisao == "draft" and resposta.feedback == "negativo":
        return _Classificacao(aceito=False, editado=False, descartado=True, pendente=False)
    if resposta.decisao == "draft":
        return _Classificacao(aceito=False, editado=False, descartado=False, pendente=True)
    return _Classificacao(aceito=False, editado=False, descartado=False, pendente=False)


def _percentil(valores: list[int], fracao: float) -> Optional[int]:
    if not valores:
        return None
    ordenados = sorted(valores)
    indice = max(0, min(len(ordenados) - 1, int(round(fracao * (len(ordenados) - 1)))))
    return ordenados[indice]


def _taxa(numerador: int, denominador: int) -> Optional[float]:
    if denominador <= 0:
        return None
    return round(numerador / denominador, 4)


def _bucket_vazio() -> dict[str, Any]:
    return {
        "rascunhos_oferecidos": 0,
        "enviados_auto": 0,
        "aceitos": 0,
        "aceitos_sem_edicao": 0,
        "aceitos_editados": 0,
        "descartados": 0,
        "pendentes": 0,
        "decididos": 0,
        "bloqueados": 0,
        "handoffs": 0,
        "suprimidos": 0,
        "bloqueios_por_motivo": {},
        "handoff_por_motivo": {},
        "supressao_por_motivo": {},
        "latencias_ms": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }


def _acumular(bucket: dict[str, Any], resposta: WhatsAppBotResposta) -> None:
    motivo = str(resposta.motivo or "sem_motivo")
    if resposta.decisao == "sent" and motivo == "enviado_auto":
        bucket["enviados_auto"] += 1
    elif resposta.decisao in _DECISOES_RASCUNHO:
        classificacao = _classificar(resposta)
        bucket["rascunhos_oferecidos"] += 1
        if classificacao.aceito:
            bucket["aceitos"] += 1
            if classificacao.editado:
                bucket["aceitos_editados"] += 1
            else:
                bucket["aceitos_sem_edicao"] += 1
        elif classificacao.descartado:
            bucket["descartados"] += 1
        elif classificacao.pendente:
            bucket["pendentes"] += 1
    elif resposta.decisao == "blocked":
        bucket["bloqueados"] += 1
        bucket["bloqueios_por_motivo"][motivo] = bucket["bloqueios_por_motivo"].get(motivo, 0) + 1
    elif resposta.decisao == "handoff":
        bucket["handoffs"] += 1
        bucket["handoff_por_motivo"][motivo] = bucket["handoff_por_motivo"].get(motivo, 0) + 1
    elif resposta.decisao == "suppressed":
        bucket["suprimidos"] += 1
        bucket["supressao_por_motivo"][motivo] = bucket["supressao_por_motivo"].get(motivo, 0) + 1

    if resposta.latencia_ms is not None:
        bucket["latencias_ms"].append(int(resposta.latencia_ms))
    bucket["input_tokens"] += int(resposta.input_tokens or 0)
    bucket["output_tokens"] += int(resposta.output_tokens or 0)


def _custo_configurado() -> bool:
    return bool(
        float(settings.WHATSAPP_BOT_INPUT_COST_PER_MILLION or 0) > 0
        or float(settings.WHATSAPP_BOT_OUTPUT_COST_PER_MILLION or 0) > 0
    )


def _finalizar(bucket: dict[str, Any]) -> dict[str, Any]:
    latencias = bucket.pop("latencias_ms")
    decididos = bucket["aceitos"] + bucket["descartados"]
    bucket["decididos"] = decididos

    # Contencao (P6.5): respostas que resolveram sem jogar para humano.
    total_com_decisao_do_bot = (
        bucket["rascunhos_oferecidos"] + bucket["enviados_auto"] + bucket["bloqueados"] + bucket["handoffs"]
    )

    bucket["taxa_aceite"] = _taxa(bucket["aceitos"], decididos)
    bucket["taxa_aceite_sem_edicao"] = _taxa(bucket["aceitos_sem_edicao"], decididos)
    bucket["taxa_edicao_entre_aceitos"] = _taxa(bucket["aceitos_editados"], bucket["aceitos"])
    bucket["taxa_descarte"] = _taxa(bucket["descartados"], decididos)
    bucket["taxa_bloqueio"] = _taxa(
        bucket["bloqueados"], bucket["rascunhos_oferecidos"] + bucket["enviados_auto"] + bucket["bloqueados"]
    )
    bucket["taxa_contencao"] = _taxa(bucket["rascunhos_oferecidos"] + bucket["enviados_auto"], total_com_decisao_do_bot)

    bucket["latencia_p50_ms"] = _percentil(latencias, 0.50)
    bucket["latencia_p95_ms"] = _percentil(latencias, 0.95)
    bucket["amostras_latencia"] = len(latencias)

    entrada = float(settings.WHATSAPP_BOT_INPUT_COST_PER_MILLION or 0)
    saida = float(settings.WHATSAPP_BOT_OUTPUT_COST_PER_MILLION or 0)
    configurado = _custo_configurado()
    bucket["custo_configurado"] = configurado
    if configurado:
        total = (bucket["input_tokens"] / 1_000_000) * entrada + (
            bucket["output_tokens"] / 1_000_000
        ) * saida
        bucket["custo_total"] = round(total, 6)
        conversas = bucket.get("conversas_distintas") or 0
        bucket["custo_por_conversa"] = round(total / conversas, 6) if conversas else None
    else:
        bucket["custo_total"] = None
        bucket["custo_por_conversa"] = None
    return bucket


class _ClassificadorDeFaixa:
    """Classifica dentro/fora do expediente sem repetir consulta por linha.

    `is_within_operating_window` recarrega `Configuracao` e reparseia o JSON da
    agenda a cada chamada. Numa janela de uma semana isso seria uma consulta e
    um parse por resposta agregada. Aqui as regras sao lidas UMA vez e a janela
    do dia e memoizada por data - o resultado tem que ser identico ao da funcao
    original, o que e travado por teste.
    """

    def __init__(self, db: Session) -> None:
        self._ok = True
        self._por_data: dict[Any, Optional[tuple[tuple[int, int], tuple[int, int]]]] = {}
        try:
            self._exceptions, self._weekly, self._holidays = _agenda_configuration_rules(db)
        except Exception:
            logger.exception("Falha ao carregar regras da agenda para a metrica do bot.")
            self._ok = False

    def _janela(self, dia) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
        if dia in self._por_data:
            return self._por_data[dia]
        janela = _agenda_day_window(
            dia,
            exceptions=self._exceptions,
            weekly=self._weekly,
            holidays=self._holidays,
        )
        resultado = None
        if janela.get("ativo"):
            inicio = _parse_hhmm(janela.get("inicio"))
            fim = _parse_hhmm(janela.get("fim"))
            if inicio is not None and fim is not None:
                resultado = (inicio, fim)
        self._por_data[dia] = resultado
        return resultado

    def classificar(self, criado: Optional[datetime]) -> str:
        if criado is None:
            return "desconhecido"
        if not self._ok:
            return "desconhecido"
        if criado.tzinfo is None:
            criado = criado.replace(tzinfo=timezone.utc)
        referencia = criado.astimezone(LOCAL_TZ)
        try:
            janela = self._janela(referencia.date())
        except Exception:
            logger.exception("Falha ao classificar faixa de horario da metrica do bot.")
            return "desconhecido"
        if janela is None:
            return "fora_expediente"
        (hi, mi), (hf, mf) = janela
        inicio_dt = referencia.replace(hour=hi, minute=mi, second=0, microsecond=0)
        fim_dt = referencia.replace(hour=hf, minute=mf, second=0, microsecond=0)
        return "expediente" if inicio_dt <= referencia <= fim_dt else "fora_expediente"


def _persona(resposta: WhatsAppBotResposta) -> str:
    valor = str(resposta.match_type or "").strip().lower()
    return valor if valor in ("tutor", "clinica") else "nao_resolvido"


def coletar_metricas_observacao(
    db: Session, *, dias: int = JANELA_PADRAO_DIAS, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Agrega a janela de observacao da Fase 6.

    Somente leitura. `dias` limita a janela; o default de 7 casa com o
    requisito de "pelo menos uma semana de trafego real" antes de qualquer
    decisao sobre `auto`.
    """
    now = now or datetime.now(timezone.utc)
    dias_normalizado = max(1, min(90, int(dias)))
    inicio = now - timedelta(days=dias_normalizado)

    respostas: Iterable[WhatsAppBotResposta] = (
        db.query(WhatsAppBotResposta)
        .filter(WhatsAppBotResposta.created_at >= inicio)
        .order_by(WhatsAppBotResposta.id.asc())
        .all()
    )

    classificador = _ClassificadorDeFaixa(db)
    geral = _bucket_vazio()
    por_persona: dict[str, dict[str, Any]] = {}
    por_faixa: dict[str, dict[str, Any]] = {}
    por_persona_faixa: dict[str, dict[str, Any]] = {}
    por_clinica: dict[str, dict[str, Any]] = {}
    conversas_geral: set[str] = set()
    conversas_por_chave: dict[str, set[str]] = {}
    prompt_versions: dict[str, int] = {}
    modelos: dict[str, int] = {}

    total = 0
    for resposta in respostas:
        total += 1
        persona = _persona(resposta)
        faixa = classificador.classificar(resposta.created_at)
        combinada = f"{persona}:{faixa}"

        _acumular(geral, resposta)
        _acumular(por_persona.setdefault(persona, _bucket_vazio()), resposta)
        _acumular(por_faixa.setdefault(faixa, _bucket_vazio()), resposta)
        _acumular(por_persona_faixa.setdefault(combinada, _bucket_vazio()), resposta)

        # Fase 4 do piloto: sem quebra por clinica o retorno nao e atribuivel -
        # tres clinicas boas escondem uma ruim. So respostas com clinica de
        # origem entram; o resto ja esta no agregado e em `por_persona`.
        if resposta.clinica_id:
            _acumular(por_clinica.setdefault(str(resposta.clinica_id), _bucket_vazio()), resposta)

        identidade = str(resposta.wa_identity or "")
        if identidade:
            conversas_geral.add(identidade)
            chaves = [persona, faixa, combinada]
            if resposta.clinica_id:
                chaves.append(f"clinica:{resposta.clinica_id}")
            for chave in chaves:
                conversas_por_chave.setdefault(chave, set()).add(identidade)

        if resposta.prompt_version:
            prompt_versions[resposta.prompt_version] = (
                prompt_versions.get(resposta.prompt_version, 0) + 1
            )
        if resposta.modelo:
            modelos[resposta.modelo] = modelos.get(resposta.modelo, 0) + 1

    geral["conversas_distintas"] = len(conversas_geral)
    for chave, bucket in (
        list(por_persona.items())
        + list(por_faixa.items())
        + list(por_persona_faixa.items())
        + [(f"clinica:{chave}", bucket) for chave, bucket in por_clinica.items()]
    ):
        bucket["conversas_distintas"] = len(conversas_por_chave.get(chave) or set())

    return {
        "gerado_em": now.isoformat(),
        "janela_dias": dias_normalizado,
        "inicio_janela": inicio.isoformat(),
        "total_respostas": total,
        "geral": _finalizar(geral),
        "por_persona": {chave: _finalizar(bucket) for chave, bucket in por_persona.items()},
        "por_faixa_horario": {chave: _finalizar(bucket) for chave, bucket in por_faixa.items()},
        "por_clinica": {chave: _finalizar(bucket) for chave, bucket in por_clinica.items()},
        "por_persona_e_faixa": {
            chave: _finalizar(bucket) for chave, bucket in por_persona_faixa.items()
        },
        "prompt_versions": prompt_versions,
        "modelos": modelos,
        "pronto_para_decidir_auto": _pronto_para_decidir(
            now=now, inicio=inicio, geral=geral, total=total, por_persona=por_persona
        ),
    }


MIN_DECIDIDOS_POR_PERSONA = 20


def _pronto_para_decidir(
    *,
    now: datetime,
    inicio: datetime,
    geral: dict[str, Any],
    total: int,
    por_persona: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Checklist explicito: nunca inferir autorizacao de `auto` do numero.

    Este bloco responde "os dados JA PERMITEM decidir?", nao "deve ligar".
    A decisao continua exigindo autorizacao humana registrada no verify.md.
    """
    decididos_geral = geral["aceitos"] + geral["descartados"]
    decididos_por_persona = {
        persona: bucket["aceitos"] + bucket["descartados"]
        for persona, bucket in por_persona.items()
        if persona in ("tutor", "clinica")
    }
    personas_com_amostra = sorted(
        persona
        for persona, decididos in decididos_por_persona.items()
        if decididos >= MIN_DECIDIDOS_POR_PERSONA
    )
    return {
        "tem_uma_semana_de_dados": (now - inicio) >= timedelta(days=7) and total > 0,
        "tem_rascunho_decidido": decididos_geral > 0,
        "decididos_por_persona": decididos_por_persona,
        "min_decididos_por_persona": MIN_DECIDIDOS_POR_PERSONA,
        "personas_com_amostra_suficiente": personas_com_amostra,
        "amostra_suficiente_nas_duas_personas": personas_com_amostra == ["clinica", "tutor"],
        "observacao": (
            "Checklist informativo. `auto` exige autorizacao humana explicita "
            "registrada no verify.md; nenhum campo aqui autoriza a mudanca."
        ),
    }
