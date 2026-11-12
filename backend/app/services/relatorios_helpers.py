from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.financeiro import Transacao
from app.services.logistica_service import (
    BUFFER_MINUTOS,
    VELOCIDADE_MEDIA_KMH,
)

LOCAL_TZ = timezone(timedelta(hours=-3))
DEFAULT_KM_MESMA_CIDADE = 12.0
DEFAULT_KM_OUTRA_CIDADE = 42.0
MIN_DURACAO_MINUTOS = 5
TOP_LIMIT = 10
SECOES_EXPORT_ORDENADAS = [
    "resumo",
    "logistica",
    "producao",
    "financeiro",
    "rentabilidade",
    "alertas",
    "insights",
    "sugestoes",
]
SECOES_EXPORT_ALIASES = {
    "all": "todas",
    "tudo": "todas",
    "todas": "todas",
    "resumo": "resumo",
    "logistica": "logistica",
    "logistica_operacional": "logistica",
    "producao": "producao",
    "operacional": "producao",
    "financeiro": "financeiro",
    "finance": "financeiro",
    "rentabilidade": "rentabilidade",
    "alertas": "alertas",
    "insights": "insights",
    "avancados": "insights",
    "sugestoes": "sugestoes",
}


def parse_iso_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} invalida. Use o formato YYYY-MM-DD.",
        ) from exc


def coerce_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(LOCAL_TZ).replace(tzinfo=None)

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                return parsed
            return parsed.astimezone(LOCAL_TZ).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def to_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cidade_estado(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def mesma_cidade(origem: Clinica, destino: Clinica) -> bool:
    cidade_origem = _cidade_estado(origem.cidade)
    cidade_destino = _cidade_estado(destino.cidade)
    estado_origem = _cidade_estado(origem.estado)
    estado_destino = _cidade_estado(destino.estado)
    if not cidade_origem or not cidade_destino:
        return False
    if cidade_origem != cidade_destino:
        return False
    if estado_origem and estado_destino and estado_origem != estado_destino:
        return False
    return True


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    raio_terra_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return raio_terra_km * c


def estimar_distancia_duracao_local(
    origem: Optional[Clinica],
    destino: Optional[Clinica],
    *,
    perfil: str,
) -> tuple[float, int, str]:
    if not origem or not destino:
        return 0.0, 0, "indefinido"
    if origem.id == destino.id:
        return 0.0, 0, "mesma_clinica"

    lat1 = safe_float(origem.latitude)
    lon1 = safe_float(origem.longitude)
    lat2 = safe_float(destino.latitude)
    lon2 = safe_float(destino.longitude)

    if None not in (lat1, lon1, lat2, lon2):
        distancia_km = haversine_km(float(lat1), float(lon1), float(lat2), float(lon2))
        fonte = "heuristica_haversine"
    elif mesma_cidade(origem, destino):
        distancia_km = DEFAULT_KM_MESMA_CIDADE
        fonte = "heuristica_mesma_cidade"
    else:
        distancia_km = DEFAULT_KM_OUTRA_CIDADE
        fonte = "heuristica_regional"

    velocidade = VELOCIDADE_MEDIA_KMH.get(perfil, VELOCIDADE_MEDIA_KMH["comercial"])
    buffer_min = BUFFER_MINUTOS.get(perfil, BUFFER_MINUTOS["comercial"])
    duracao_base = (distancia_km / max(1.0, velocidade)) * 60.0
    duracao_min = max(MIN_DURACAO_MINUTOS, int(math.ceil(duracao_base + buffer_min)))

    return round(max(0.0, float(distancia_km)), 2), duracao_min, fonte


def selecionar_clinica_base(
    clinica_base_id: Optional[int],
    clinica_map: dict[int, Clinica],
    agendamentos_periodo: list[Any],
    clinicas_ativas: list[Clinica],
) -> tuple[Optional[int], Optional[str], str]:
    if clinica_base_id and clinica_base_id in clinica_map:
        base = clinica_map[clinica_base_id]
        return int(base.id), str(base.nome or f"Clinica #{base.id}"), "parametro"

    contagem: dict[int, int] = {}
    for ag in agendamentos_periodo:
        status = str(ag.status or "").strip()
        if status == "Cancelado":
            continue
        if ag.clinica_id:
            cid = int(ag.clinica_id)
            contagem[cid] = contagem.get(cid, 0) + 1

    if contagem:
        base_id = max(contagem, key=contagem.get)
        base = clinica_map.get(base_id)
        if base:
            return int(base.id), str(base.nome or f"Clinica #{base.id}"), "mais_agendamentos_periodo"

    if clinicas_ativas:
        base = clinicas_ativas[0]
        return int(base.id), str(base.nome or f"Clinica #{base.id}"), "primeira_clinica_ativa"

    return None, None, "indefinida"


@dataclass(slots=True)
class AgendamentoAgregado:
    id: int
    clinica_id: Optional[int]
    servico_id: Optional[int]
    status: Optional[str]
    inicio: Optional[datetime]
    fim: Optional[datetime]
    created_at: Optional[datetime]


def carregar_agendamentos_periodo_enxuto(query_agendamentos) -> list[AgendamentoAgregado]:
    rows = (
        query_agendamentos.with_entities(
            Agendamento.id,
            Agendamento.clinica_id,
            Agendamento.servico_id,
            Agendamento.status,
            Agendamento.inicio,
            Agendamento.fim,
            Agendamento.created_at,
        )
        .order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
        .all()
    )
    return [
        AgendamentoAgregado(
            id=int(row.id),
            clinica_id=int(row.clinica_id) if row.clinica_id is not None else None,
            servico_id=int(row.servico_id) if row.servico_id is not None else None,
            status=row.status,
            inicio=row.inicio,
            fim=row.fim,
            created_at=row.created_at,
        )
        for row in rows
    ]


def sum_transacoes(
    db: Session,
    *,
    tipo: str,
    status_list: list[str],
    data_inicio: date,
    data_fim: date,
    clinica_ids_filter: Optional[list[int]] = None,
) -> float:
    if clinica_ids_filter is not None and len(clinica_ids_filter) == 0:
        return 0.0

    total = (
        db.query(func.sum(Transacao.valor_final))
        .filter(
            Transacao.tipo == tipo,
            Transacao.status.in_(status_list),
            func.date(Transacao.data_transacao) >= data_inicio.isoformat(),
            func.date(Transacao.data_transacao) <= data_fim.isoformat(),
        )
    )
    if clinica_ids_filter is not None:
        total = total.filter(Transacao.clinica_id.in_(clinica_ids_filter))
    total = total.scalar()
    return to_float(total)


def formatar_moeda_brl(valor: Any) -> str:
    numero = to_float(valor)
    inteiro, casas = f"{numero:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{casas}"


def formatar_numero(valor: Any, casas: int = 2) -> str:
    numero = to_float(valor)
    return f"{numero:.{casas}f}"


def normalizar_pesos_rateio(peso_km: Any, peso_atendimento: Any) -> tuple[float, float]:
    km = max(0.0, to_float(peso_km))
    atendimento = max(0.0, to_float(peso_atendimento))
    total = km + atendimento
    if total <= 0:
        return 0.7, 0.3
    return round(km / total, 6), round(atendimento / total, 6)


def normalizar_secoes_export(secoes_raw: Optional[str]) -> list[str]:
    if not secoes_raw:
        return list(SECOES_EXPORT_ORDENADAS)

    bruto = str(secoes_raw).replace(";", ",").replace("|", ",")
    tokens = [item.strip().lower() for item in bruto.split(",") if item.strip()]
    if not tokens:
        return list(SECOES_EXPORT_ORDENADAS)

    resolvidas: set[str] = set()
    invalidas: list[str] = []
    for token in tokens:
        mapped = SECOES_EXPORT_ALIASES.get(token)
        if mapped is None:
            invalidas.append(token)
            continue
        if mapped == "todas":
            return list(SECOES_EXPORT_ORDENADAS)
        resolvidas.add(mapped)

    if invalidas:
        raise HTTPException(
            status_code=422,
            detail=(
                "Secoes invalidas em 'secoes': "
                + ", ".join(sorted(set(invalidas)))
                + ". Use: "
                + ", ".join(SECOES_EXPORT_ORDENADAS)
            ),
        )

    selecionadas = [secao for secao in SECOES_EXPORT_ORDENADAS if secao in resolvidas]
    if not selecionadas:
        return list(SECOES_EXPORT_ORDENADAS)
    return selecionadas
