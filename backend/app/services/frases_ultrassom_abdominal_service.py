"""
Service para gerenciamento das frases de ultrassonografia abdominal.

As frases ficam versionadas em JSON para facilitar ajustes pela equipe sem
dependencia de migracao de banco.
"""
import json
from datetime import datetime
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


DATA_DIR = Path(__file__).parent.parent.parent / "data"
FRASES_FILE = DATA_DIR / "frases_ultrassom_abdominal.json"
RUNTIME_BACKUP_DIR = DATA_DIR / "runtime_backups" / "frases_ultrassom_abdominal"
RUNTIME_BACKUP_RETENTION = 240


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _default_payload() -> Dict[str, Any]:
    return {
        "version": "1.0",
        "last_updated": datetime.now().isoformat(),
        "frases": [],
    }


def _backup_tag(value: str) -> str:
    tag = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    return tag.strip("_") or "update"


def _dump_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _atomic_write_payload(payload: Dict[str, Any]) -> None:
    _ensure_data_dir()
    tmp_path = FRASES_FILE.with_suffix(f"{FRASES_FILE.suffix}.tmp")
    tmp_path.write_text(_dump_payload(payload), encoding="utf-8")
    tmp_path.replace(FRASES_FILE)


def _prune_runtime_backups() -> None:
    if not RUNTIME_BACKUP_DIR.exists():
        return
    snapshots = sorted(RUNTIME_BACKUP_DIR.glob("*.json"), reverse=True)
    for stale in snapshots[RUNTIME_BACKUP_RETENTION:]:
        try:
            stale.unlink()
        except OSError:
            continue


def _snapshot_current_file(reason: str) -> Optional[Path]:
    if not FRASES_FILE.exists():
        return None
    RUNTIME_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = RUNTIME_BACKUP_DIR / f"{stamp}__{_backup_tag(reason)}.json"
    shutil.copy2(FRASES_FILE, backup_path)
    _prune_runtime_backups()
    return backup_path


def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _latest_valid_runtime_backup() -> Optional[Dict[str, Any]]:
    if not RUNTIME_BACKUP_DIR.exists():
        return None
    for candidate in sorted(RUNTIME_BACKUP_DIR.glob("*.json"), reverse=True):
        payload = _load_json_file(candidate)
        if payload is not None:
            return payload
    return None


def _load_payload() -> Dict[str, Any]:
    if not FRASES_FILE.exists():
        payload = _default_payload()
        _atomic_write_payload(payload)
        return payload

    data = _load_json_file(FRASES_FILE)
    if data is None:
        _snapshot_current_file("corrupted_store")
        recovered = _latest_valid_runtime_backup()
        if recovered is not None:
            _atomic_write_payload(recovered)
            data = recovered
        else:
            data = _default_payload()
            _atomic_write_payload(data)

    if not isinstance(data, dict):
        data = _default_payload()

    frases = data.get("frases")
    if not isinstance(frases, list):
        data["frases"] = []

    return data


def _save_payload(payload: Dict[str, Any], reason: str = "update") -> None:
    _snapshot_current_file(reason)
    _atomic_write_payload(payload)


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _normalize_sexo(sexo: Optional[str]) -> str:
    texto = (sexo or "Todos").strip().lower()
    if texto.startswith("m"):
        return "Macho"
    if texto.startswith("f"):
        return "Femea"
    return "Todos"


def _normalize_orgao(orgao: Optional[str]) -> str:
    return (orgao or "").strip().lower()


def _next_id(frases: List[Dict[str, Any]]) -> int:
    ids = [_to_int(item.get("id")) for item in frases]
    ids_validos = [item for item in ids if item is not None]
    return (max(ids_validos) + 1) if ids_validos else 1


def _normalizar_ids(frases: List[Dict[str, Any]]) -> bool:
    changed = False
    usados = set()
    next_id = _next_id(frases)

    for frase in frases:
        frase_id = _to_int(frase.get("id"))
        if frase_id is None or frase_id in usados:
            while next_id in usados:
                next_id += 1
            frase_id = next_id
            next_id += 1
            frase["id"] = frase_id
            changed = True
        usados.add(frase_id)

        sexo = _normalize_sexo(frase.get("sexo"))
        if frase.get("sexo") != sexo:
            frase["sexo"] = sexo
            changed = True

        orgao = _normalize_orgao(frase.get("orgao"))
        if frase.get("orgao") != orgao:
            frase["orgao"] = orgao
            changed = True

        frase.setdefault("titulo", "")
        frase.setdefault("texto", "")
        frase.setdefault("ativo", 1)

    return changed


def listar_frases(
    orgao: Optional[str] = None,
    sexo: Optional[str] = None,
    busca: Optional[str] = None,
    ativo: Optional[int] = 1,
    skip: int = 0,
    limit: int = 200,
) -> Dict[str, Any]:
    payload = _load_payload()
    frases = payload.get("frases", [])

    if _normalizar_ids(frases):
        payload["last_updated"] = datetime.now().isoformat()
        _save_payload(payload, reason="normalize_ids")

    if ativo is not None:
        frases = [item for item in frases if int(item.get("ativo", 1)) == int(ativo)]

    orgao_norm = _normalize_orgao(orgao)
    if orgao_norm:
        frases = [item for item in frases if _normalize_orgao(item.get("orgao")) == orgao_norm]

    sexo_norm = _normalize_sexo(sexo) if sexo else ""
    if sexo_norm:
        frases = [item for item in frases if _normalize_sexo(item.get("sexo")) == sexo_norm]

    if busca:
        termo = busca.strip().lower()
        frases = [
            item
            for item in frases
            if termo in str(item.get("titulo", "")).lower()
            or termo in str(item.get("texto", "")).lower()
            or termo in str(item.get("orgao", "")).lower()
        ]

    frases.sort(
        key=lambda item: (
            str(item.get("orgao", "")),
            str(item.get("sexo", "")),
            str(item.get("titulo", "")).lower(),
            _to_int(item.get("id")) or 0,
        )
    )

    total = len(frases)
    items = frases[skip : skip + limit]
    return {"items": items, "total": total}


def obter_frase(frase_id: int) -> Optional[Dict[str, Any]]:
    payload = _load_payload()
    frase_id = _to_int(frase_id) or frase_id
    for item in payload.get("frases", []):
        if _to_int(item.get("id")) == frase_id:
            return item
    return None


def criar_frase(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = _load_payload()
    frases = payload.get("frases", [])

    orgao = _normalize_orgao(data.get("orgao"))
    if not orgao:
        raise ValueError("Orgao e obrigatorio.")

    texto = str(data.get("texto") or "").strip()
    if not texto:
        raise ValueError("Texto da frase e obrigatorio.")

    titulo = str(data.get("titulo") or "").strip()
    sexo = _normalize_sexo(data.get("sexo"))
    agora = datetime.now().isoformat()

    nova_frase = {
        "id": _next_id(frases),
        "orgao": orgao,
        "sexo": sexo,
        "titulo": titulo,
        "texto": texto,
        "ativo": 1,
        "created_at": agora,
        "updated_at": agora,
    }

    frases.append(nova_frase)
    payload["frases"] = frases
    payload["last_updated"] = agora
    _save_payload(payload, reason="create_phrase")
    return nova_frase


def atualizar_frase(frase_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = _load_payload()
    frases = payload.get("frases", [])
    frase_id = _to_int(frase_id) or frase_id

    for index, frase in enumerate(frases):
        if _to_int(frase.get("id")) != frase_id:
            continue

        if "orgao" in data:
            orgao = _normalize_orgao(data.get("orgao"))
            if not orgao:
                raise ValueError("Orgao e obrigatorio.")
            frase["orgao"] = orgao

        if "sexo" in data:
            frase["sexo"] = _normalize_sexo(data.get("sexo"))

        if "titulo" in data:
            frase["titulo"] = str(data.get("titulo") or "").strip()

        if "texto" in data:
            texto = str(data.get("texto") or "").strip()
            if not texto:
                raise ValueError("Texto da frase e obrigatorio.")
            frase["texto"] = texto

        if "ativo" in data:
            frase["ativo"] = 1 if int(data.get("ativo") or 0) == 1 else 0

        frase["updated_at"] = datetime.now().isoformat()
        frases[index] = frase
        payload["frases"] = frases
        payload["last_updated"] = frase["updated_at"]
        _save_payload(payload, reason="update_phrase")
        return frase

    return None


def deletar_frase(frase_id: int) -> bool:
    return atualizar_frase(frase_id, {"ativo": 0}) is not None


def restaurar_frase(frase_id: int) -> bool:
    return atualizar_frase(frase_id, {"ativo": 1}) is not None

