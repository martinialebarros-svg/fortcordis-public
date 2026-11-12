"""Pure evaluation of the optional regional transition between appointments.

``agendamentos_dia`` is the original day's operational route, before replacing
the candidate's old ID on an update. Items contain ``id``, naive-local datetime
``inicio``/``fim`` and ``destino_operacional`` dictionaries. The operational base
is deliberately not a route stop. Cancelled/expired items are ignored defensively.

The caller still owns overlap, opening hours, first departure, normal travel
validation and insertion-detour checks. This helper only authorizes the extra
travel allowance and checks its full-day quota and additional safety margin.
It performs no I/O itself. Reuse ``cache_deslocamentos`` for all candidates in
one request; unchanged directed pairs then call the resolver only once.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence, Union


@dataclass(frozen=True)
class EstimativaDeslocamentoRegional:
    """A directed duration. Explicit confidence can represent a manual override.

    Google route/distance-matrix and ``manual`` sources are recognized for tuple
    resolvers. A typed resolver may attest another real route with ``confiavel``;
    heuristic/fallback/unknown sources are never eligible, even with that flag.
    Freshness/provider validity remains the resolver's responsibility.
    """

    duracao_min: Optional[int]
    fonte: str
    confiavel: bool = False


EstimativaResolvida = Union[EstimativaDeslocamentoRegional, tuple[Optional[int], str], None]
ResolvedorDeslocamento = Callable[[Mapping[str, Any], Mapping[str, Any]], EstimativaResolvida]
CacheDeslocamentosRegionais = MutableMapping[tuple[str, str], EstimativaDeslocamentoRegional]


@dataclass(frozen=True)
class TrechoTransicaoRegional:
    origem_id: Any
    destino_id: Any
    duracao_min: Optional[int]
    fonte: str
    confiavel: bool
    folga_min: int
    margem_necessaria_min: int
    longo: bool
    envolve_candidato: bool
    novo_trecho: bool


@dataclass(frozen=True)
class AvaliacaoTransicaoRegional:
    permitida: bool
    codigo: str
    transicoes_longas: int
    transicoes_longas_anteriores: int
    usa_transicao_regional: bool
    trecho_anterior: Optional[TrechoTransicaoRegional]
    trecho_proximo: Optional[TrechoTransicaoRegional]
    trechos: tuple[TrechoTransicaoRegional, ...]
    limite_trecho_min: int
    limite_trechos_dia: int
    margem_min: int

    def as_dict(self) -> dict[str, Any]:
        """Metadata without destination/address dictionaries or appointment times."""
        return asdict(self)


def _chave_destino(destino: Mapping[str, Any]) -> str:
    # Include coordinates and identity so an edited destination cannot reuse an
    # estimate for stale coordinates. The key remains request-local, never logged.
    return json.dumps(dict(destino), sort_keys=True, default=str, ensure_ascii=True)


def _mesmo_destino(origem: Mapping[str, Any], destino: Mapping[str, Any]) -> bool:
    tipo_origem = str(origem.get("tipo") or "clinica_parceira")
    tipo_destino = str(destino.get("tipo") or "clinica_parceira")
    try:
        identidade = int(origem.get("entity_id") or 0)
        identidade_destino = int(destino.get("entity_id") or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return identidade > 0 and tipo_origem == tipo_destino and identidade == identidade_destino


def _estimativa_normalizada(valor: EstimativaResolvida) -> EstimativaDeslocamentoRegional:
    if isinstance(valor, EstimativaDeslocamentoRegional):
        duracao, fonte, atestada = valor.duracao_min, valor.fonte, valor.confiavel
    elif isinstance(valor, tuple) and len(valor) == 2:
        duracao, fonte = valor
        atestada = False
    else:
        return EstimativaDeslocamentoRegional(None, "sem_estimativa")
    fonte = str(fonte or "indefinido").strip()
    try:
        numero = float(duracao) if duracao is not None and not isinstance(duracao, bool) else math.nan
        duracao_min = math.ceil(numero) if math.isfinite(numero) and numero > 0 else None
    except (TypeError, ValueError, OverflowError):
        duracao_min = None
    fonte_norm = fonte.lower()
    proibida = not fonte_norm or any(
        marcador in fonte_norm
        for marcador in ("heurist", "haversine", "fallback", "indefin", "unknown", "sem_", "indisponivel")
    )
    reconhecida = fonte_norm.startswith(("google_routes_api", "google_distance_matrix")) or fonte_norm in {
        "manual", "manual_override", "rota_manual",
    }
    return EstimativaDeslocamentoRegional(
        duracao_min, fonte, bool(duracao_min is not None and not proibida and (reconhecida or atestada)),
    )


def _resolver_estimativa(
    origem: Mapping[str, Any],
    destino: Mapping[str, Any],
    resolver: ResolvedorDeslocamento,
    cache: CacheDeslocamentosRegionais,
) -> EstimativaDeslocamentoRegional:
    if _mesmo_destino(origem, destino):
        return EstimativaDeslocamentoRegional(0, "mesmo_destino", True)
    chave = (_chave_destino(origem), _chave_destino(destino))
    if chave not in cache:
        cache[chave] = _estimativa_normalizada(resolver(origem, destino))
    return cache[chave]


def _ativo(item: Mapping[str, Any]) -> bool:
    return str(item.get("status") or "Agendado").strip().casefold() not in {"cancelado", "expirado"}


def _assinatura_trecho(origem: Mapping[str, Any], destino: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        origem.get("id"), destino.get("id"), origem["fim"], destino["inicio"],
        _chave_destino(origem["destino_operacional"]), _chave_destino(destino["destino_operacional"]),
    )


def avaliar_transicao_regional(
    agendamentos_dia: Sequence[Mapping[str, Any]],
    candidato: Mapping[str, Any],
    *,
    regras_rota: Mapping[str, Any],
    resolver_deslocamento: ResolvedorDeslocamento,
    agendamento_id_excluir: Optional[int] = None,
    cache_deslocamentos: Optional[CacheDeslocamentosRegionais] = None,
) -> Optional[AvaliacaoTransicaoRegional]:
    """Evaluate the complete resulting route, returning ``None`` when disabled.

    Existing fixed legs keep their previously accepted gaps/exceptional limits.
    A legacy route already above its quota may remain at, or reduce, that count;
    adding another long leg is rejected. New or changed long legs require a real
    route, the configured extra ceiling and the full regional margin. Unknown
    fixed legs prevent granting a new exception because its quota is unprovable.
    A new candidate leg without any duration is rejected, rather than treated
    as zero travel. Normal short-leg validation otherwise stays with the caller.
    """
    policy = regras_rota.get("route_policy") or {}
    if not policy.get("regional_transition_enabled", False):
        return None
    thresholds = regras_rota.get("thresholds") or {}
    normal = int(thresholds.get("max_neighbor_travel_min", 45))
    teto = int(policy.get("regional_transition_max_travel_min", 50))
    margem = int(policy.get("regional_transition_margin_min", 15))
    quota = int(policy.get("regional_transition_max_legs_per_day", 1))
    margem_normal = int(thresholds.get("safe_margin_min", 5))
    cache = cache_deslocamentos if cache_deslocamentos is not None else {}
    baseline = sorted((item for item in agendamentos_dia if _ativo(item)), key=lambda item: item["inicio"])
    excluir = agendamento_id_excluir if agendamento_id_excluir is not None else candidato.get("id")
    resultante = [item for item in baseline if excluir is None or item.get("id") != excluir]
    if _ativo(candidato):
        resultante.append(candidato)
    resultante.sort(key=lambda item: item["inicio"])

    assinaturas_anteriores = set()
    quantidade_anterior = 0
    for origem, destino in zip(baseline, baseline[1:]):
        assinaturas_anteriores.add(_assinatura_trecho(origem, destino))
        estimativa = _resolver_estimativa(origem["destino_operacional"], destino["destino_operacional"], resolver_deslocamento, cache)
        quantidade_anterior += int(normal > 0 and estimativa.duracao_min is not None and estimativa.duracao_min > normal)

    trechos = []
    anterior = proximo = None
    for origem, destino in zip(resultante, resultante[1:]):
        estimativa = _resolver_estimativa(origem["destino_operacional"], destino["destino_operacional"], resolver_deslocamento, cache)
        longo = normal > 0 and estimativa.duracao_min is not None and estimativa.duracao_min > normal
        trecho = TrechoTransicaoRegional(
            origem_id=origem.get("id"), destino_id=destino.get("id"),
            duracao_min=estimativa.duracao_min, fonte=estimativa.fonte, confiavel=estimativa.confiavel,
            folga_min=math.floor((destino["inicio"] - origem["fim"]).total_seconds() / 60),
            margem_necessaria_min=margem if longo else margem_normal,
            longo=longo, envolve_candidato=origem is candidato or destino is candidato,
            novo_trecho=_assinatura_trecho(origem, destino) not in assinaturas_anteriores,
        )
        trechos.append(trecho)
        if destino is candidato:
            anterior = trecho
        if origem is candidato:
            proximo = trecho

    quantidade = sum(int(trecho.longo) for trecho in trechos)
    novos_longos = [trecho for trecho in trechos if trecho.longo and trecho.novo_trecho]
    usa_regional = any(trecho.longo and trecho.envolve_candidato for trecho in trechos)
    codigo = "TRANSICAO_REGIONAL_APROVADA" if usa_regional else "SEM_TRANSICAO_REGIONAL"
    sem_duracao_nova = any(
        trecho.novo_trecho and trecho.envolve_candidato and trecho.duracao_min is None
        for trecho in trechos
    )
    if sem_duracao_nova or (novos_longos and any(not trecho.confiavel for trecho in trechos)):
        codigo = "TRANSICAO_REGIONAL_ROTA_NAO_CONFIAVEL"
    elif quantidade > max(quota, quantidade_anterior):
        codigo = "TRANSICAO_REGIONAL_COTA_EXCEDIDA"
    elif any(trecho.duracao_min > teto for trecho in novos_longos):
        codigo = "TRANSICAO_REGIONAL_LIMITE_EXCEDIDO"
    elif any(trecho.folga_min < trecho.duracao_min + margem for trecho in novos_longos):
        codigo = "TRANSICAO_REGIONAL_FOLGA_INSUFICIENTE"
    return AvaliacaoTransicaoRegional(
        permitida=codigo in {"TRANSICAO_REGIONAL_APROVADA", "SEM_TRANSICAO_REGIONAL"},
        codigo=codigo, transicoes_longas=quantidade, transicoes_longas_anteriores=quantidade_anterior,
        usa_transicao_regional=usa_regional, trecho_anterior=anterior, trecho_proximo=proximo,
        trechos=tuple(trechos), limite_trecho_min=teto, limite_trechos_dia=quota, margem_min=margem,
    )
