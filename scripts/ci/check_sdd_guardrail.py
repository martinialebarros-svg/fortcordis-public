#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Set, Tuple

CODE_PREFIXES = ("backend/", "frontend/", "scripts/")
SPEC_ROOT = "docs/specs/"
SPEC_TEMPLATES_PREFIX = "docs/specs/templates/"
REQUIRED_SPEC_FILES = ("intent.md", "spec.md", "plan.md", "verify.md")
MANDATORY_CHANGED_DOCS = ("spec.md", "verify.md")


@dataclass
class GuardrailResult:
    passed: bool
    messages: List[str]
    code_files: List[str]
    spec_feature_files: Dict[str, Set[str]]
    qualified_features: List[str]


def _normalize_path(path: str) -> str:
    return str(path or "").replace("\\", "/").lstrip("./")


def _is_code_change(path: str) -> bool:
    normalized = _normalize_path(path)
    if normalized.startswith(SPEC_ROOT):
        return False
    return normalized.startswith(CODE_PREFIXES)


def _parse_spec_change(path: str) -> Tuple[str, str] | None:
    normalized = _normalize_path(path)
    if not normalized.startswith(SPEC_ROOT):
        return None
    if normalized.startswith(SPEC_TEMPLATES_PREFIX):
        return None
    parts = normalized.split("/")
    if len(parts) < 4:
        return None
    _, _, feature_slug, file_name = parts[0], parts[1], parts[2], parts[3]
    if not feature_slug or not file_name:
        return None
    return feature_slug, file_name


def _git_diff_changed_files(base_sha: str, head_sha: str) -> List[str]:
    command = [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=ACMRD",
        f"{base_sha}..{head_sha}",
    ]
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            "Falha ao obter arquivos alterados via git diff: "
            f"{process.stderr.strip() or 'erro desconhecido'}"
        )

    changed = []
    for line in process.stdout.splitlines():
        normalized = _normalize_path(line.strip())
        if normalized:
            changed.append(normalized)
    return sorted(set(changed))


def evaluate_guardrail(changed_files: Sequence[str], repo_root: str) -> GuardrailResult:
    normalized_files = sorted({_normalize_path(path) for path in changed_files if path})
    code_files = [path for path in normalized_files if _is_code_change(path)]

    feature_files: Dict[str, Set[str]] = defaultdict(set)
    for path in normalized_files:
        parsed = _parse_spec_change(path)
        if parsed is None:
            continue
        feature_slug, file_name = parsed
        feature_files[feature_slug].add(file_name)

    messages: List[str] = []
    qualified_features: List[str] = []

    if not code_files:
        messages.append("Sem mudancas de codigo (backend/frontend/scripts): guardrail SDD dispensado.")
        return GuardrailResult(
            passed=True,
            messages=messages,
            code_files=[],
            spec_feature_files=dict(feature_files),
            qualified_features=[],
        )

    if not feature_files:
        messages.append(
            "Mudancas de codigo detectadas, mas nenhum artefato SDD foi alterado em docs/specs/<feature>/."
        )
        messages.append(
            "Exigido: atualizar ao menos uma feature com spec.md + verify.md no mesmo ciclo."
        )
        return GuardrailResult(
            passed=False,
            messages=messages,
            code_files=code_files,
            spec_feature_files={},
            qualified_features=[],
        )

    missing_structure: Dict[str, List[str]] = {}
    for feature_slug in sorted(feature_files.keys()):
        feature_dir = os.path.join(repo_root, "docs", "specs", feature_slug)
        missing = [
            required_file
            for required_file in REQUIRED_SPEC_FILES
            if not os.path.isfile(os.path.join(feature_dir, required_file))
        ]
        if missing:
            missing_structure[feature_slug] = missing
            continue

        changed_docs = feature_files[feature_slug]
        if all(required_doc in changed_docs for required_doc in MANDATORY_CHANGED_DOCS):
            qualified_features.append(feature_slug)

    if missing_structure:
        for feature_slug, missing in sorted(missing_structure.items()):
            messages.append(
                f"Feature docs/specs/{feature_slug} sem estrutura obrigatoria: faltando {', '.join(missing)}."
            )

    if not qualified_features:
        messages.append(
            "Mudancas de codigo exigem atualizacao SDD com spec.md + verify.md no mesmo diretorio de feature."
        )
        messages.append(
            "Nenhuma feature qualificada encontrada neste diff."
        )
        for feature_slug, changed_docs in sorted(feature_files.items()):
            changed_list = ", ".join(sorted(changed_docs))
            messages.append(f"- docs/specs/{feature_slug}: alterados [{changed_list}]")

        return GuardrailResult(
            passed=False,
            messages=messages,
            code_files=code_files,
            spec_feature_files=dict(feature_files),
            qualified_features=[],
        )

    messages.append(
        "Guardrail SDD aprovado: mudancas de codigo acompanhadas por spec+verify em feature SDD valida."
    )
    messages.append(f"Features qualificadas: {', '.join(sorted(qualified_features))}")

    return GuardrailResult(
        passed=len(missing_structure) == 0,
        messages=messages,
        code_files=code_files,
        spec_feature_files=dict(feature_files),
        qualified_features=sorted(qualified_features),
    )


def _format_list(prefix: str, values: Iterable[str]) -> List[str]:
    items = list(values)
    if not items:
        return [f"{prefix}: (vazio)"]
    lines = [f"{prefix}:"]
    lines.extend([f"  - {item}" for item in items])
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate CI para forcar fluxo Spec Driven Development.")
    parser.add_argument("--base-sha", required=True, help="SHA base para diff.")
    parser.add_argument("--head-sha", required=True, help="SHA head para diff.")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Raiz do repositorio (default: diretorio atual).",
    )
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    os.chdir(repo_root)

    try:
        changed_files = _git_diff_changed_files(args.base_sha, args.head_sha)
    except Exception as exc:
        print(f"[sdd-guardrail] FAILED: {exc}")
        return 1

    result = evaluate_guardrail(changed_files, repo_root)

    print(f"[sdd-guardrail] base={args.base_sha} head={args.head_sha}")
    for line in _format_list("[sdd-guardrail] changed_files", changed_files):
        print(line)
    for line in _format_list("[sdd-guardrail] code_files", result.code_files):
        print(line)
    if result.spec_feature_files:
        print("[sdd-guardrail] spec_features:")
        for feature_slug in sorted(result.spec_feature_files.keys()):
            docs_changed = ", ".join(sorted(result.spec_feature_files[feature_slug]))
            print(f"  - {feature_slug}: {docs_changed}")
    else:
        print("[sdd-guardrail] spec_features: (vazio)")

    for message in result.messages:
        print(f"[sdd-guardrail] {message}")

    if result.passed:
        print("[sdd-guardrail] PASSED")
        return 0
    print("[sdd-guardrail] FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
