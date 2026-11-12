#!/usr/bin/env python3
"""Gate de promocao: barra `stage -> main` com criterio pendente no verify.md.

O gate SDD (`check_sdd_guardrail.py`) exige que `spec.md` e `verify.md` mudem
junto com o codigo, mas nao olha o *conteudo* do verify: uma promocao passava
com criterio de aceitacao ainda marcado `pendente`. Este script fecha isso.

Escopo deliberado -- so PRs que miram `main`:
no fluxo stage-first, criterio pendente e o estado normal de um PR de feature.
Muita coisa so pode ser verificada *depois* de chegar em stage, entao bloquear
PRs para `stage` inverteria o processo. A promocao e o momento em que a
pendencia deixa de ser normal e vira risco de producao.

So olha as features tocadas no diff da promocao. Varrer os 240 specs do repo
reprovaria toda promocao para sempre por pendencia historica alheia a entrega.

Classificacao de status (calibrada sobre os ~1600 status reais do repo, que
usam vocabulario livre -- `ok`, `passou`, `aprovado`, `local_pass`, ...):

- marcadores FORTES valem em qualquer posicao da celula, porque "pendente"
  quase nunca aparece de forma inocente. Isso pega os status que comecam bem e
  terminam mal, como "aprovado em stage; producao pendente".
- marcadores GENERICOS so valem no inicio da celula. "parcial" aparece em prosa
  tecnica legitima -- um `ok ... indice unico parcial de idempotency_key`
  descreve um indice do Postgres, nao um criterio pela metade.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

SPEC_ROOT = "docs/specs/"
SPEC_TEMPLATES_PREFIX = "docs/specs/templates/"
VERIFY_FILE = "verify.md"

MARCADORES_FORTES = re.compile(
    r"\b(pendente|pendentes|pendencia|pendencias|stage_pending|reprovado|falhou)\b"
)
MARCADORES_GENERICOS = re.compile(
    r"^(parcial|parcialmente|bloqueado|sem resposta|"
    r"nao testado|nao verificado|nao concluido|depois)\b"
)


def _normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_acento.strip().lower()


def status_e_pendente(status: str) -> bool:
    normalizado = _normalizar(status)
    if not normalizado:
        return False
    return bool(MARCADORES_FORTES.search(normalizado) or MARCADORES_GENERICOS.match(normalizado))


@dataclass
class Pendencia:
    feature: str
    identificador: str
    status: str


@dataclass
class ResultadoGate:
    passou: bool
    mensagens: List[str] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    pendencias: List[Pendencia] = field(default_factory=list)


def _celulas(linha: str) -> List[str]:
    return [c.strip() for c in linha.strip().strip("|").split("|")]


def _e_separador(celulas: Sequence[str]) -> bool:
    juntas = "".join(celulas)
    return bool(juntas) and set(juntas) <= set("-: ")


def extrair_pendencias(conteudo: str, feature: str) -> List[Pendencia]:
    """Le tabelas markdown e devolve as linhas cuja coluna Status esta pendente.

    So considera tabelas que tenham uma coluna `Status`: o verify.md costuma
    trazer tambem tabelas de etapas e de respostas, que nao sao criterios.
    """
    pendencias: List[Pendencia] = []
    idx_status = None
    idx_id = None

    for linha in conteudo.splitlines():
        if not linha.lstrip().startswith("|"):
            idx_status = None
            idx_id = None
            continue

        celulas = _celulas(linha)
        if _e_separador(celulas):
            continue

        if idx_status is None:
            cabecalho = [_normalizar(c) for c in celulas]
            if "status" in cabecalho:
                idx_status = cabecalho.index("status")
                idx_id = cabecalho.index("id") if "id" in cabecalho else None
            continue

        if idx_status >= len(celulas):
            continue

        status = celulas[idx_status]
        if not status_e_pendente(status):
            continue

        identificador = "(sem id)"
        if idx_id is not None and idx_id < len(celulas) and celulas[idx_id]:
            identificador = celulas[idx_id]
        pendencias.append(Pendencia(feature=feature, identificador=identificador, status=status))

    return pendencias


def features_tocadas(arquivos: Sequence[str]) -> List[str]:
    features = set()
    for caminho in arquivos:
        normalizado = caminho.replace("\\", "/").lstrip("./")
        if not normalizado.startswith(SPEC_ROOT):
            continue
        if normalizado.startswith(SPEC_TEMPLATES_PREFIX):
            continue
        partes = normalizado[len(SPEC_ROOT):].split("/")
        if len(partes) >= 2 and partes[0]:
            features.add(partes[0])
    return sorted(features)


def avaliar(
    arquivos: Sequence[str],
    repo_root: str,
    permitir_pendencia: bool = False,
) -> ResultadoGate:
    features = features_tocadas(arquivos)
    if not features:
        return ResultadoGate(
            passou=True,
            mensagens=["Nenhuma feature de docs/specs no diff: gate dispensado."],
        )

    pendencias: List[Pendencia] = []
    for feature in features:
        caminho = os.path.join(repo_root, SPEC_ROOT, feature, VERIFY_FILE)
        if not os.path.isfile(caminho):
            continue
        with open(caminho, encoding="utf-8") as stream:
            pendencias.extend(extrair_pendencias(stream.read(), feature))

    if not pendencias:
        return ResultadoGate(
            passou=True,
            mensagens=[f"{len(features)} feature(s) no diff, nenhum criterio pendente."],
            features=features,
        )

    if permitir_pendencia:
        return ResultadoGate(
            passou=True,
            mensagens=[
                f"{len(pendencias)} criterio(s) pendente(s), liberados pela label de excecao.",
                "A pendencia continua real: registre no PR por que a promocao segue assim.",
            ],
            features=features,
            pendencias=pendencias,
        )

    return ResultadoGate(
        passou=False,
        mensagens=[
            f"{len(pendencias)} criterio(s) de aceitacao ainda pendente(s) nas features promovidas.",
            "Feche a verificacao, ou aplique a label de excecao no PR se a promocao for consciente.",
        ],
        features=features,
        pendencias=pendencias,
    )


def _git_diff_changed_files(base_sha: str, head_sha: str) -> List[str]:
    saida = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...{head_sha}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [linha.strip() for linha in saida.splitlines() if linha.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate de promocao: barra criterio pendente no verify.md das features promovidas."
    )
    parser.add_argument("--base-sha", required=True, help="SHA base para diff.")
    parser.add_argument("--head-sha", required=True, help="SHA head para diff.")
    parser.add_argument("--repo-root", default=".", help="Raiz do repositorio (default: atual).")
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="Libera a promocao mesmo com pendencia (acionado pela label de excecao).",
    )
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    os.chdir(repo_root)

    try:
        arquivos = _git_diff_changed_files(args.base_sha, args.head_sha)
    except Exception as exc:
        print(f"[promotion-verify] FAILED: {exc}")
        return 1

    resultado = avaliar(arquivos, repo_root, permitir_pendencia=args.allow_pending)

    print(f"[promotion-verify] base={args.base_sha} head={args.head_sha}")
    if resultado.features:
        print(f"[promotion-verify] features promovidas: {', '.join(resultado.features)}")

    if resultado.pendencias:
        print("[promotion-verify] criterios pendentes:")
        por_feature: Dict[str, List[Pendencia]] = {}
        for pendencia in resultado.pendencias:
            por_feature.setdefault(pendencia.feature, []).append(pendencia)
        for feature in sorted(por_feature):
            print(f"  {SPEC_ROOT}{feature}/{VERIFY_FILE}")
            for pendencia in por_feature[feature]:
                print(f"    - {pendencia.identificador}: {pendencia.status}")

    for mensagem in resultado.mensagens:
        print(f"[promotion-verify] {mensagem}")

    if resultado.passou:
        print("[promotion-verify] PASSED")
        return 0

    print("[promotion-verify] FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
