#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


TARGET_REL_PATH = "backend/data/frases_ecocardiograma_estruturado_teste.json"
RUNTIME_BACKUP_REL_DIR = "backend/data/runtime_backups/frases_ecocardiograma_estruturado_teste"


@dataclass
class SnapshotInfo:
    path: Path
    presets_count: int
    frases_count: int
    aspectos_count: int
    has_token: bool
    labels_sample: list[str]
    mtime: float
    source: str


def _load_json(path: Path) -> Optional[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _parse_snapshot(path: Path, token: str, source: str) -> Optional[SnapshotInfo]:
    payload = _load_json(path)
    if payload is None:
        return None

    presets = payload.get("presets") or []
    aspectos = payload.get("aspectos") or []
    if not isinstance(presets, list) or not isinstance(aspectos, list):
        return None

    labels: list[str] = []
    has_token = False
    token_cf = token.casefold()
    for item in presets:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if label:
            labels.append(label)
            if token_cf and token_cf in label.casefold():
                has_token = True

    frases_count = 0
    for aspecto in aspectos:
        if not isinstance(aspecto, dict):
            continue
        frases = aspecto.get("frases") or []
        if isinstance(frases, list):
            frases_count += len(frases)

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0

    return SnapshotInfo(
        path=path,
        presets_count=len(presets),
        frases_count=frases_count,
        aspectos_count=len(aspectos),
        has_token=has_token,
        labels_sample=labels[:8],
        mtime=mtime,
        source=source,
    )


def _iter_candidates(app_dir: Path, backup_root: Path, token: str) -> Iterable[SnapshotInfo]:
    current = app_dir / TARGET_REL_PATH
    if current.exists():
        info = _parse_snapshot(current, token=token, source="current")
        if info:
            yield info

    runtime_dir = app_dir / RUNTIME_BACKUP_REL_DIR
    if runtime_dir.exists():
        for path in sorted(runtime_dir.glob("*.json"), reverse=True):
            info = _parse_snapshot(path, token=token, source="runtime_backup")
            if info:
                yield info

    if backup_root.exists():
        for runtime_dir in sorted(backup_root.glob("*__runtime"), reverse=True):
            candidate = runtime_dir / TARGET_REL_PATH
            if not candidate.exists():
                continue
            info = _parse_snapshot(candidate, token=token, source="deploy_snapshot")
            if info:
                yield info


def _sort_key(item: SnapshotInfo) -> tuple[int, int, int, float]:
    return (
        1 if item.has_token else 0,
        item.presets_count,
        item.frases_count,
        item.mtime,
    )


def _fmt_dt(ts: float) -> str:
    if ts <= 0:
        return "-"
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _print_summary(title: str, item: SnapshotInfo) -> None:
    print(f"{title}:")
    print(f"  source={item.source}")
    print(f"  path={item.path}")
    print(
        "  counts="
        f"presets:{item.presets_count} "
        f"frases:{item.frases_count} "
        f"aspectos:{item.aspectos_count}"
    )
    print(f"  has_token={item.has_token}")
    print(f"  mtime={_fmt_dt(item.mtime)}")
    if item.labels_sample:
        print(f"  labels_sample={item.labels_sample}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspeciona e recupera frases/presets do ecocardiograma em stage."
    )
    parser.add_argument("--app-dir", default="/var/www/fortcordis-stage")
    parser.add_argument("--backup-root", default=str(Path.home() / "fortcordis-runtime-backups"))
    parser.add_argument("--token", default="DMVM", help="Texto para procurar nos labels dos presets.")
    parser.add_argument("--apply", action="store_true", help="Aplica recuperacao usando melhor candidato.")
    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    backup_root = Path(args.backup_root).resolve()
    target_file = app_dir / TARGET_REL_PATH

    candidates = list(_iter_candidates(app_dir, backup_root, token=args.token))
    if not candidates:
        print("Nenhum snapshot valido encontrado.")
        return 2

    ranked = sorted(candidates, key=_sort_key, reverse=True)
    current = next((item for item in ranked if item.source == "current"), ranked[0])
    best = ranked[0]

    _print_summary("CURRENT", current)
    _print_summary("BEST", best)

    print("TOP_CANDIDATES:")
    for idx, item in enumerate(ranked[:10], start=1):
        print(
            f"  {idx:02d}. source={item.source} "
            f"presets={item.presets_count} frases={item.frases_count} "
            f"has_token={item.has_token} mtime={_fmt_dt(item.mtime)} path={item.path}"
        )

    if not args.apply:
        print("Dry-run concluido. Nenhuma alteracao aplicada.")
        return 0

    if not target_file.exists():
        print(f"Arquivo alvo ausente: {target_file}")
        return 3

    if best.path.resolve() == target_file.resolve():
        print("Arquivo atual ja e o melhor candidato. Nenhuma restauracao necessaria.")
        return 0

    backup_path = target_file.with_name(
        f"{target_file.name}.pre_recover_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    shutil.copy2(target_file, backup_path)
    shutil.copy2(best.path, target_file)

    print(f"Backup do atual salvo em: {backup_path}")
    print(f"Store restaurado a partir de: {best.path}")

    restored = _parse_snapshot(target_file, token=args.token, source="restored_current")
    if restored:
        _print_summary("RESTORED_CURRENT", restored)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
