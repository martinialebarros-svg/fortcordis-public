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


TARGET_FILE = Path("data/frases_ecocardiograma_estruturado_teste.json")
RUNTIME_BACKUP_DIR = Path("data/runtime_backups/frases_ecocardiograma_estruturado_teste")


@dataclass
class Snapshot:
    path: Path
    source: str
    presets_count: int
    frases_count: int
    aspectos_count: int
    has_token: bool
    mtime: float


def _read_json(path: Path) -> Optional[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _snapshot_from(path: Path, source: str, token: str) -> Optional[Snapshot]:
    payload = _read_json(path)
    if payload is None:
        return None

    presets = payload.get("presets") or []
    aspectos = payload.get("aspectos") or []
    if not isinstance(presets, list) or not isinstance(aspectos, list):
        return None

    token_cf = token.casefold()
    has_token = False
    for item in presets:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if label and token_cf in label.casefold():
            has_token = True
            break

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

    return Snapshot(
        path=path,
        source=source,
        presets_count=len(presets),
        frases_count=frases_count,
        aspectos_count=len(aspectos),
        has_token=has_token,
        mtime=mtime,
    )


def _iter_candidates(app_dir: Path, token: str) -> Iterable[Snapshot]:
    current = app_dir / TARGET_FILE
    if current.exists():
        item = _snapshot_from(current, "current", token)
        if item:
            yield item

    runtime_dir = app_dir / RUNTIME_BACKUP_DIR
    if runtime_dir.exists():
        for path in sorted(runtime_dir.glob("*.json"), reverse=True):
            item = _snapshot_from(path, "runtime_backup", token)
            if item:
                yield item

    deploy_root = Path.home() / "fortcordis-runtime-backups"
    if deploy_root.exists():
        for path in sorted(deploy_root.glob("*__runtime/backend/data/frases_ecocardiograma_estruturado_teste.json"), reverse=True):
            item = _snapshot_from(path, "deploy_snapshot", token)
            if item:
                yield item


def _rank_key(item: Snapshot) -> tuple[int, int, int, float]:
    return (1 if item.has_token else 0, item.presets_count, item.frases_count, item.mtime)


def _fmt_time(ts: float) -> str:
    if ts <= 0:
        return "-"
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _print_item(prefix: str, item: Snapshot) -> None:
    print(
        f"{prefix} source={item.source} presets={item.presets_count} frases={item.frases_count} "
        f"aspectos={item.aspectos_count} has_token={item.has_token} mtime={_fmt_time(item.mtime)} "
        f"path={item.path}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspeciona/recupera store de frases no stage.")
    parser.add_argument("--apply", action="store_true", help="Aplica recuperacao.")
    parser.add_argument(
        "--token",
        default=os.getenv("FRASES_EXPECTED_TOKEN", "DMVM"),
        help="Token esperado nos labels dos presets.",
    )
    args = parser.parse_args()

    app_dir = Path(__file__).resolve().parent
    target = app_dir / TARGET_FILE

    print(f"TOKEN={args.token}")
    print(f"TARGET={target}")

    candidates = list(_iter_candidates(app_dir, args.token))
    if not candidates:
        print("Nenhum candidato valido encontrado.")
        return 2

    ranked = sorted(candidates, key=_rank_key, reverse=True)
    current = next((item for item in ranked if item.source == "current"), ranked[0])
    best = ranked[0]

    _print_item("CURRENT", current)
    _print_item("BEST   ", best)
    print("TOP_CANDIDATES")
    for idx, item in enumerate(ranked[:12], start=1):
        _print_item(f"{idx:02d}.", item)

    if not args.apply:
        print("Dry-run finalizado sem alteracoes.")
        return 0

    if not target.exists():
        print(f"Arquivo alvo ausente: {target}")
        return 3

    if best.path.resolve() == target.resolve():
        print("Arquivo atual ja e o melhor candidato. Nada a restaurar.")
        return 0

    backup_current = target.with_name(
        f"{target.name}.pre_recover_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    shutil.copy2(target, backup_current)
    shutil.copy2(best.path, target)
    print(f"Backup atual salvo em: {backup_current}")
    print(f"Store restaurado de: {best.path}")

    restored = _snapshot_from(target, "restored_current", args.token)
    if restored:
        _print_item("RESTORED", restored)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
