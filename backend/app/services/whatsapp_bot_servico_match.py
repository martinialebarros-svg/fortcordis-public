"""Casamento entre o que o cliente PEDE e o que o catalogo VENDE.

Motivacao (defeito real observado no piloto): a selecao de servico era
`alvo in nome`, substring pura, ordenada por nome. A pergunta "quanto custa
o eco" casava com seis servicos e o corte alfabetico em tres devolvia
`Consulta + Eco` (R$ 410), `Consulta + Eco + Eletro` (R$ 480) e
`Eco + Eletro` (R$ 250) -- decapitando justamente `Ecocardiograma`
(R$ 180), que e o servico perguntado. O cliente recebia cotacao mais cara
que a real, com aparencia de resposta correta.

Desenho: pergunta e nome de servico viram o MESMO tipo de objeto -- um
conjunto de procedimentos canonicos. Sinonimo ("eco", "ecodopplercardiograma",
"ultrassom do coracao") e combinacao ("consulta com eco") passam a ser
resolvidos pela mesma regra, em vez de por duas heuristicas separadas.

Fronteira de palavra e obrigatoria, nao cosmetica: "eco" e substring de
"preco" (sem acento, depois de normalizar) e "pa" e substring de "para",
"pacote", "espaco". Casamento ingenuo transformaria "qual o preco da
consulta" num pedido de ecocardiograma. Coberto por teste.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

_VOCAB_PATH = Path(__file__).resolve().parents[2] / "data" / "whatsapp_bot_servico_sinonimos.json"

# Grau de aderencia entre o conjunto pedido e o conjunto do servico.
AFINIDADE_EXATA = 3      # conjuntos iguais: e exatamente isto que a pessoa pediu
AFINIDADE_CONTEM = 2     # o servico contem tudo que foi pedido, mais alguma coisa
AFINIDADE_PARCIAL = 1    # ha interseccao, mas o servico nao cobre o pedido inteiro
AFINIDADE_NENHUMA = 0


def _normalizar(value: Any) -> str:
    raw = str(value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", raw)
    sem_acento = "".join(char for char in decomposed if not unicodedata.combining(char))
    # "+" e "/" separam procedimentos no catalogo ("Eco + Eletro"); viram espaco
    # para que a fronteira de palavra enxergue cada termo isolado.
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", sem_acento)).strip()


@lru_cache(maxsize=1)
def _vocabulario() -> dict[str, Any]:
    with _VOCAB_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _compilar(mapa: dict[str, list[str]]) -> list[tuple[str, re.Pattern[str]]]:
    """Termos mais longos primeiro: "ecodopplercardiograma" antes de "eco".

    Sem isso o termo curto casaria primeiro e o resultado seria o mesmo
    procedimento, mas a ordem deixa o comportamento previsivel e o teste
    de cobertura de vocabulario legivel.
    """
    compilados: list[tuple[str, re.Pattern[str]]] = []
    for canonico, termos in mapa.items():
        for termo in sorted(termos, key=len, reverse=True):
            alvo = _normalizar(termo)
            if not alvo:
                continue
            compilados.append((canonico, re.compile(rf"(?<![a-z0-9]){re.escape(alvo)}(?![a-z0-9])")))
    return compilados


@lru_cache(maxsize=1)
def _padroes_pedido() -> list[tuple[str, re.Pattern[str]]]:
    return _compilar(_vocabulario()["procedimentos"])


@lru_cache(maxsize=1)
def _padroes_catalogo() -> list[tuple[str, re.Pattern[str]]]:
    bruto = dict(_vocabulario()["_nomes_no_catalogo"])
    bruto.pop("_nota", None)
    return _compilar(bruto)


def procedimentos_do_pedido(texto: Optional[str]) -> frozenset[str]:
    """Procedimentos canonicos citados pelo cliente, na linguagem dele."""
    alvo = _normalizar(texto)
    if not alvo:
        return frozenset()
    return frozenset(canonico for canonico, padrao in _padroes_pedido() if padrao.search(alvo))


def procedimentos_do_servico(nome: Optional[str]) -> frozenset[str]:
    """Procedimentos que compoem um servico do catalogo, pelo nome cadastrado."""
    alvo = _normalizar(nome)
    if not alvo:
        return frozenset()
    return frozenset(canonico for canonico, padrao in _padroes_catalogo() if padrao.search(alvo))


def afinidade(pedido: frozenset[str], servico: frozenset[str]) -> int:
    if not pedido or not servico:
        return AFINIDADE_NENHUMA
    if pedido == servico:
        return AFINIDADE_EXATA
    if pedido < servico:
        return AFINIDADE_CONTEM
    if pedido & servico:
        return AFINIDADE_PARCIAL
    return AFINIDADE_NENHUMA


def ordenar_candidatos(
    servicos: Iterable[Any],
    *,
    pedido: frozenset[str],
    nome_de: Any = lambda s: getattr(s, "nome", ""),
) -> list[tuple[Any, int, frozenset[str]]]:
    """Ordena por aderencia ao pedido; empate desfeito pelo servico mais simples.

    O criterio de desempate ("menos procedimentos primeiro") importa: entre
    `Consulta + Eco` e `Consulta + Eco + Eletro`, quem pediu "consulta com
    eco" deve ver primeiro o que nao inclui exame extra. Nunca ordenar por
    nome -- era exatamente o alfabetico que escondia `Ecocardiograma`.
    """
    pontuados: list[tuple[Any, int, frozenset[str]]] = []
    for servico in servicos:
        composicao = procedimentos_do_servico(nome_de(servico))
        grau = afinidade(pedido, composicao) if pedido else AFINIDADE_NENHUMA
        pontuados.append((servico, grau, composicao))

    if pedido:
        pontuados = [item for item in pontuados if item[1] != AFINIDADE_NENHUMA]

    pontuados.sort(
        key=lambda item: (
            -item[1],
            len(item[2]) if item[2] else 99,
            _normalizar(nome_de(item[0])),
        )
    )
    return pontuados
