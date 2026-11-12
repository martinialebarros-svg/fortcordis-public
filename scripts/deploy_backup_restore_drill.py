#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

DEFAULT_RUNTIME_PATHS = [
    "backend/fortcordis.db",
    "backend/data/frases.json",
    "backend/data/patologias.json",
    "backend/data/frases_ecocardiograma_estruturado_teste.json",
    "backend/data/frases_ultrassom_abdominal.json",
    "backend/data/atendimento_clinical_phrases.json",
]
DEFAULT_SQLITE_REL_PATH = "backend/fortcordis.db"


def _is_within(base_dir: str, candidate_path: str) -> bool:
    base_abs = os.path.abspath(base_dir)
    candidate_abs = os.path.abspath(candidate_path)
    return os.path.commonpath([base_abs, candidate_abs]) == base_abs


def _resolve_relative_file(base_dir: str, relative_path: str) -> str:
    rel = str(relative_path or "").strip().replace("\\", "/")
    if not rel:
        raise RuntimeError("Path relativo vazio.")
    if os.path.isabs(rel):
        raise RuntimeError(f"Path absoluto nao permitido: {relative_path}")
    abs_path = os.path.abspath(os.path.join(base_dir, rel))
    if not _is_within(base_dir, abs_path):
        raise RuntimeError(f"Path fora do diretorio base: {relative_path}")
    return abs_path


def _slugify_fragment(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    normalized = normalized.strip("-")
    return normalized or "app"


def _build_default_stamp(app_dir: str) -> str:
    app_slug = _slugify_fragment(os.path.basename(os.path.abspath(app_dir)))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"{timestamp}_{app_slug}_{os.getpid()}"


def _sha256_file(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _collect_runtime_files(app_dir: str, runtime_paths: List[str]) -> Dict[str, str]:
    files: Dict[str, str] = {}
    missing: List[str] = []
    for rel_path in runtime_paths:
        abs_path = _resolve_relative_file(app_dir, rel_path)
        if not os.path.isfile(abs_path):
            missing.append(rel_path)
            continue
        files[rel_path] = abs_path
    if missing:
        raise RuntimeError(f"Arquivos runtime ausentes: {', '.join(missing)}")
    return files


def _build_manifest(files: Dict[str, str]) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": {},
    }
    entries: Dict[str, Dict[str, object]] = {}
    for rel_path in sorted(files.keys()):
        abs_path = files[rel_path]
        entries[rel_path] = {
            "sha256": _sha256_file(abs_path),
            "size_bytes": int(os.path.getsize(abs_path)),
        }
    payload["files"] = entries
    return payload


def _archive_snapshot(files: Dict[str, str], archive_path: str) -> None:
    with tarfile.open(archive_path, "w:gz") as archive:
        for rel_path in sorted(files.keys()):
            archive.add(files[rel_path], arcname=rel_path)


def _extract_archive(archive_path: str, destination_dir: str) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if member.name.startswith("/") or ".." in parts:
                raise RuntimeError(f"Entrada de archive insegura: {member.name}")
            target_path = os.path.abspath(os.path.join(destination_dir, member.name))
            if not _is_within(destination_dir, target_path):
                raise RuntimeError(f"Entrada de archive fora do destino: {member.name}")
        # `filter="data"` endurece a extracao em Python mais novo; para
        # interpretadores antigos, o pre-check acima mantem a extracao segura.
        try:
            archive.extractall(destination_dir, filter="data")
        except TypeError:
            archive.extractall(destination_dir)


def _verify_restored_files(restore_dir: str, manifest: Dict[str, object]) -> List[str]:
    errors: List[str] = []
    files = manifest.get("files")
    if not isinstance(files, dict):
        return ["Manifest invalido: campo files ausente."]

    for rel_path, metadata in files.items():
        if not isinstance(metadata, dict):
            errors.append(f"Manifest invalido para {rel_path}: metadata ausente.")
            continue
        expected_hash = str(metadata.get("sha256") or "").strip()
        expected_size = int(metadata.get("size_bytes") or 0)

        restored_path = _resolve_relative_file(restore_dir, str(rel_path))
        if not os.path.isfile(restored_path):
            errors.append(f"Arquivo restaurado ausente: {rel_path}")
            continue

        current_hash = _sha256_file(restored_path)
        current_size = int(os.path.getsize(restored_path))
        if current_hash != expected_hash:
            errors.append(f"Hash divergente em {rel_path}")
        if current_size != expected_size:
            errors.append(
                f"Tamanho divergente em {rel_path} (esperado={expected_size}, atual={current_size})"
            )

    return errors


def _validate_sqlite_integrity(restore_dir: str, sqlite_rel_path: str) -> None:
    sqlite_file = _resolve_relative_file(restore_dir, sqlite_rel_path)
    if not os.path.isfile(sqlite_file):
        raise RuntimeError(f"SQLite restaurado ausente: {sqlite_rel_path}")

    connection = sqlite3.connect(sqlite_file)
    try:
        row = connection.execute("PRAGMA integrity_check;").fetchone()
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"Falha no PRAGMA integrity_check: {exc}") from exc
    finally:
        connection.close()

    result = str(row[0]).strip().lower() if row else ""
    if result != "ok":
        raise RuntimeError(f"PRAGMA integrity_check retornou '{result or 'vazio'}'")


def _write_json_file(path: str, payload: Dict[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drill automatizado de backup + restore de artefatos runtime."
    )
    parser.add_argument(
        "--app-dir",
        default="/var/www/fortcordis-v2",
        help="Diretorio raiz da aplicacao.",
    )
    parser.add_argument(
        "--backup-dir",
        default=os.path.join(os.path.expanduser("~"), "fortcordis-runtime-backups"),
        help="Diretorio base para artefatos de backup.",
    )
    parser.add_argument(
        "--runtime-path",
        action="append",
        default=[],
        help="Path relativo de arquivo runtime critico (repetivel).",
    )
    parser.add_argument(
        "--sqlite-rel-path",
        default=DEFAULT_SQLITE_REL_PATH,
        help="Path relativo do SQLite a validar com integrity_check.",
    )
    parser.add_argument(
        "--skip-sqlite-check",
        action="store_true",
        help="Pula validacao do PRAGMA integrity_check.",
    )
    parser.add_argument(
        "--keep-restore-dir",
        action="store_true",
        help="Mantem diretorio temporario de restore para depuracao.",
    )
    parser.add_argument(
        "--stamp",
        default="",
        help="Carimbo opcional para nome dos artefatos.",
    )
    args = parser.parse_args()

    app_dir = os.path.abspath(args.app_dir)
    backup_dir = os.path.abspath(args.backup_dir)
    runtime_paths = list(args.runtime_path or [])
    if not runtime_paths:
        runtime_paths = list(DEFAULT_RUNTIME_PATHS)
    stamp = str(args.stamp or "").strip() or _build_default_stamp(app_dir)

    os.makedirs(backup_dir, exist_ok=True)
    archive_path = os.path.join(backup_dir, f"{stamp}__runtime-drill.tar.gz")
    manifest_path = os.path.join(backup_dir, f"{stamp}__runtime-drill.manifest.json")
    restore_dir = tempfile.mkdtemp(prefix=f"{stamp}__restore-drill_", dir=backup_dir)

    print(f"[drill] app_dir={app_dir}")
    print(f"[drill] backup_dir={backup_dir}")
    print(f"[drill] restore_dir={restore_dir}")

    try:
        runtime_files = _collect_runtime_files(app_dir, runtime_paths)
        manifest = _build_manifest(runtime_files)
        _archive_snapshot(runtime_files, archive_path)
        _write_json_file(manifest_path, manifest)
        print(f"[drill] snapshot={archive_path}")
        print(f"[drill] manifest={manifest_path}")

        _extract_archive(archive_path, restore_dir)
        restore_errors = _verify_restored_files(restore_dir, manifest)
        if restore_errors:
            raise RuntimeError("; ".join(restore_errors))

        if not args.skip_sqlite_check:
            _validate_sqlite_integrity(restore_dir, args.sqlite_rel_path)
            print("[drill] sqlite_integrity=ok")
        else:
            print("[drill] sqlite_integrity=skipped")

        print("[drill] PASSED")
        return 0
    except Exception as exc:
        print("[drill] FAILED")
        print(f"[drill] - {exc}")
        return 1
    finally:
        if args.keep_restore_dir:
            print(f"[drill] keep_restore_dir=true: {restore_dir}")
        else:
            shutil.rmtree(restore_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
