from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
import shutil
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FRASES_FILE = DATA_DIR / "frases_ecocardiograma_estruturado_teste.json"
RUNTIME_BACKUP_DIR = DATA_DIR / "runtime_backups" / "frases_ecocardiograma_estruturado_teste"
RUNTIME_BACKUP_RETENTION = 240

DEFAULT_ASPECTS = [
    {"key": "valva_mitral", "label": "Valva mitral", "categoria": "Valvas", "descricao": "Morfologia e funcionamento da valva mitral.", "placeholder": "Descreva espessamento, prolapso, refluxo, estenose e mobilidade da valva mitral.", "legacy_field": "valvas", "ordem": 10},
    {"key": "valva_aortica", "label": "Valva aortica", "categoria": "Valvas", "descricao": "Morfologia e funcionamento da valva aortica.", "placeholder": "Descreva cuspides, fluxo, refluxo ou estenose da valva aortica.", "legacy_field": "valvas", "ordem": 20},
    {"key": "valva_tricuspide", "label": "Valva tricuspide", "categoria": "Valvas", "descricao": "Morfologia e funcionamento da valva tricuspide.", "placeholder": "Descreva refluxo, espessamento, degeneracao ou estenose da valva tricuspide.", "legacy_field": "valvas", "ordem": 30},
    {"key": "valva_pulmonar", "label": "Valva pulmonar", "categoria": "Valvas", "descricao": "Morfologia e funcionamento da valva pulmonar.", "placeholder": "Descreva valva pulmonar, refluxo, estenose e comportamento do fluxo.", "legacy_field": "valvas", "ordem": 40},
    {"key": "atrio_esquerdo", "label": "Atrio esquerdo", "categoria": "Camaras esquerdas", "descricao": "Tamanho, remodelamento e comportamento do atrio esquerdo.", "placeholder": "Descreva dimensoes, aumento atrial e sinais de remodelamento do atrio esquerdo.", "legacy_field": "camaras", "ordem": 50},
    {"key": "ventriculo_esquerdo", "label": "Ventriculo esquerdo", "categoria": "Camaras esquerdas", "descricao": "Dimensoes e geometria do ventriculo esquerdo.", "placeholder": "Descreva espessuras, diametros, remodelamento e padrao estrutural do VE.", "legacy_field": "camaras", "ordem": 60},
    {"key": "funcao_sistolica_ve", "label": "Funcao sistolica do VE", "categoria": "Funcao", "descricao": "Comportamento da contratilidade e da funcao sistolica global.", "placeholder": "Descreva funcao sistolica, hipercinesia, hipocinesia ou preservacao da contratilidade.", "legacy_field": "funcao", "ordem": 70},
    {"key": "funcao_diastolica", "label": "Funcao diastolica", "categoria": "Funcao", "descricao": "Padrao de enchimento e relaxamento ventricular.", "placeholder": "Descreva funcao diastolica, padrao de enchimento e relaxamento.", "legacy_field": "funcao", "ordem": 80},
    {"key": "atrio_direito", "label": "Atrio direito", "categoria": "Camaras direitas", "descricao": "Dimensoes e comportamento do atrio direito.", "placeholder": "Descreva volume e remodelamento do atrio direito.", "legacy_field": "ad_vd", "ordem": 90},
    {"key": "ventriculo_direito", "label": "Ventriculo direito", "categoria": "Camaras direitas", "descricao": "Dimensoes, espessura e desempenho do ventriculo direito.", "placeholder": "Descreva diametro, hipertrofia, dilatacao e funcao do ventriculo direito.", "legacy_field": "ad_vd", "ordem": 100},
    {"key": "septos", "label": "Septos", "categoria": "Estruturas complementares", "descricao": "Avaliacao dos septos interatrial e interventricular.", "placeholder": "Descreva integridade septal, movimento e eventuais defeitos.", "legacy_field": "camaras", "ordem": 110},
    {"key": "aorta", "label": "Aorta", "categoria": "Vasos", "descricao": "Avaliacao da raiz da aorta e comportamento do vaso.", "placeholder": "Descreva raiz aortica, dimensoes e observacoes relevantes da aorta.", "legacy_field": "vasos", "ordem": 120},
    {"key": "arteria_pulmonar", "label": "Arteria pulmonar", "categoria": "Vasos", "descricao": "Avaliacao da arteria pulmonar e sua relacao com a aorta.", "placeholder": "Descreva arteria pulmonar, relacao AP/Ao e observacoes do fluxo.", "legacy_field": "vasos", "ordem": 130},
    {"key": "pericardio", "label": "Pericardio", "categoria": "Estruturas complementares", "descricao": "Avaliacao do saco pericardico e espaco pericardico.", "placeholder": "Descreva espessamento, derrame ou ausencia de alteracoes pericardicas.", "legacy_field": "pericardio", "ordem": 140},
    {"key": "conclusao", "label": "Conclusao", "categoria": "Conclusao", "descricao": "Sintese final do ecocardiograma.", "placeholder": "Escreva a sintese final do exame com os principais achados.", "legacy_field": "conclusao", "ordem": 150},
]

DEFAULT_SAMPLE_PHRASES = {
    "valva_mitral": [
        {"titulo": "Aspecto habitual", "texto": "Valva mitral com morfologia preservada, sem sinais ecocardiograficos relevantes de degeneracao, estenose ou refluxo significativo.", "tags": ["normal", "base"]},
        {"titulo": "Espessada com regurgitacao leve", "texto": "Valva mitral discretamente espessada, com refluxo mitral de baixa intensidade, sem sinais de repercussao hemodinamica importante no momento.", "tags": ["endocardiose", "b1", "leve"]},
    ],
    "valva_aortica": [
        {"titulo": "Aspecto habitual", "texto": "Valva aortica com morfologia e mobilidade preservadas, sem evidencias de refluxo ou estenose significativa.", "tags": ["normal", "base"]},
    ],
    "valva_tricuspide": [
        {"titulo": "Aspecto habitual", "texto": "Valva tricuspide com morfologia preservada, sem alteracoes ecocardiograficas relevantes e sem refluxo expressivo.", "tags": ["normal", "base"]},
    ],
    "valva_pulmonar": [
        {"titulo": "Aspecto habitual", "texto": "Valva pulmonar com aspecto ecocardiografico preservado, sem estenose ou refluxo significativo.", "tags": ["normal", "base"]},
    ],
    "atrio_esquerdo": [
        {"titulo": "Sem aumento atrial", "texto": "Atrio esquerdo com dimensoes preservadas, sem evidencias de aumento atrial no exame atual.", "tags": ["normal"]},
        {"titulo": "Remodelamento discreto", "texto": "Atrio esquerdo com discreto remodelamento, sem aumento importante das dimensoes cavitarias.", "tags": ["endocardiose", "b1", "leve"]},
    ],
    "ventriculo_esquerdo": [
        {"titulo": "Geometria preservada", "texto": "Ventriculo esquerdo com dimensoes e espessuras preservadas, sem sinais de remodelamento concentrico ou excentrico.", "tags": ["normal"]},
    ],
    "funcao_sistolica_ve": [
        {"titulo": "Funcao sistolica preservada", "texto": "Funcao sistolica global do ventriculo esquerdo preservada, sem evidencias de reducao da contratilidade.", "tags": ["normal"]},
    ],
    "atrio_direito": [
        {"titulo": "Sem alteracoes relevantes", "texto": "Atrio direito sem alteracoes ecocardiograficas relevantes no exame atual.", "tags": ["normal", "base"]},
    ],
    "ventriculo_direito": [
        {"titulo": "Sem alteracoes relevantes", "texto": "Ventriculo direito com dimensoes e funcao preservadas, sem sinais de sobrecarga significativa.", "tags": ["normal", "base"]},
    ],
    "aorta": [
        {"titulo": "Raiz aortica preservada", "texto": "Raiz aortica com dimensoes preservadas e sem alteracoes ecocardiograficas relevantes.", "tags": ["normal", "base"]},
    ],
    "arteria_pulmonar": [
        {"titulo": "Calibre preservado", "texto": "Arteria pulmonar com calibre preservado, sem sinais sugestivos de alteracao hemodinamica relevante.", "tags": ["normal", "base"]},
    ],
    "pericardio": [
        {"titulo": "Sem derrame", "texto": "Pericardio sem alteracoes ecocardiograficas relevantes e sem derrame pericardico detectavel.", "tags": ["normal"]},
    ],
    "conclusao": [
        {"titulo": "Conclusao normal", "texto": "Ecocardiograma sem alteracoes estruturais ou funcionais relevantes no momento.", "tags": ["normal", "conclusao"]},
        {"titulo": "Conclusao endocardiose B1", "texto": "Achados compativeis com endocardiose mitral em classificacao B1, sem sinais ecocardiograficos de repercussao cardiaca importante no exame atual.", "tags": ["endocardiose", "b1", "conclusao"]},
    ],
}

DEFAULT_SAMPLE_PRESETS = [
    {
        "key": "normal_base",
        "label": "Normal base",
        "patologia": "Normal",
        "grau": "Normal",
        "descricao": "Preset basal para exame sem alteracoes estruturais relevantes.",
        "tags": ["normal", "base"],
        "ordem": 10,
        "selecoes": [
            {"aspecto": "valva_mitral", "frase_titulo": "Aspecto habitual"},
            {"aspecto": "valva_aortica", "frase_titulo": "Aspecto habitual"},
            {"aspecto": "valva_tricuspide", "frase_titulo": "Aspecto habitual"},
            {"aspecto": "valva_pulmonar", "frase_titulo": "Aspecto habitual"},
            {"aspecto": "atrio_esquerdo", "frase_titulo": "Sem aumento atrial"},
            {"aspecto": "ventriculo_esquerdo", "frase_titulo": "Geometria preservada"},
            {"aspecto": "funcao_sistolica_ve", "frase_titulo": "Funcao sistolica preservada"},
            {"aspecto": "atrio_direito", "frase_titulo": "Sem alteracoes relevantes"},
            {"aspecto": "ventriculo_direito", "frase_titulo": "Sem alteracoes relevantes"},
            {"aspecto": "aorta", "frase_titulo": "Raiz aortica preservada"},
            {"aspecto": "arteria_pulmonar", "frase_titulo": "Calibre preservado"},
            {"aspecto": "pericardio", "frase_titulo": "Sem derrame"},
            {"aspecto": "conclusao", "frase_titulo": "Conclusao normal"},
        ],
    },
    {
        "key": "endocardiose_mitral_b1",
        "label": "Endocardiose mitral B1",
        "patologia": "Endocardiose Mitral",
        "grau": "B1",
        "descricao": "Exemplo de preset com combinacao tipica de achados leves e sem repercussao marcante.",
        "tags": ["endocardiose", "b1", "teste"],
        "ordem": 20,
        "selecoes": [
            {"aspecto": "valva_mitral", "frase_titulo": "Espessada com regurgitacao leve"},
            {"aspecto": "valva_aortica", "frase_titulo": "Aspecto habitual"},
            {"aspecto": "valva_tricuspide", "frase_titulo": "Aspecto habitual"},
            {"aspecto": "valva_pulmonar", "frase_titulo": "Aspecto habitual"},
            {"aspecto": "atrio_esquerdo", "frase_titulo": "Remodelamento discreto"},
            {"aspecto": "ventriculo_esquerdo", "frase_titulo": "Geometria preservada"},
            {"aspecto": "funcao_sistolica_ve", "frase_titulo": "Funcao sistolica preservada"},
            {"aspecto": "atrio_direito", "frase_titulo": "Sem alteracoes relevantes"},
            {"aspecto": "ventriculo_direito", "frase_titulo": "Sem alteracoes relevantes"},
            {"aspecto": "pericardio", "frase_titulo": "Sem derrame"},
            {"aspecto": "conclusao", "frase_titulo": "Conclusao endocardiose B1"},
        ],
    },
]

DEFAULT_SAMPLE_PRESETS_COUNT = len(DEFAULT_SAMPLE_PRESETS)
DEFAULT_SAMPLE_PHRASES_COUNT = sum(len(items) for items in DEFAULT_SAMPLE_PHRASES.values())
SAVE_REASONS_ALLOWING_SHRINK = {"import", "recover_from_backup", "fallback_rebuild", "auto_recover_minimal_store"}

CONCLUSION_TEXT_CORRECTIONS = {
    "efusao pericardica leve sem tamponamento": (
        "Efusão pericárdica discreta (não drenável), sem alterações cardíacas estruturais.",
        "Efusão pericárdica discreta (não drenável).",
    ),
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _normalize_match_key(value: Any) -> str:
    decomposed = unicodedata.normalize("NFD", str(value or ""))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").casefold().strip()


def _apply_conclusion_text_correction(aspecto: str, titulo: str, texto: str) -> str:
    if aspecto != "conclusao":
        return texto
    correction = CONCLUSION_TEXT_CORRECTIONS.get(_normalize_match_key(titulo))
    if correction is None:
        return texto
    original, replacement = correction
    return texto.replace(original, replacement)


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    items: List[str] = []
    seen = set()
    for item in raw_items:
        normalized = str(item or "").strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            items.append(normalized)
            seen.add(key)
    return items


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _backup_tag(value: str) -> str:
    tag = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    return tag.strip("_") or "update"


def _json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _atomic_write_store(payload: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = FRASES_FILE.with_suffix(f"{FRASES_FILE.suffix}.tmp")
    tmp_path.write_text(_json_dumps(payload), encoding="utf-8")
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


def _snapshot_current_store(reason: str) -> Optional[Path]:
    if not FRASES_FILE.exists():
        return None
    RUNTIME_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = RUNTIME_BACKUP_DIR / f"{stamp}__{_backup_tag(reason)}.json"
    shutil.copy2(FRASES_FILE, backup_path)
    _prune_runtime_backups()
    return backup_path


def _try_load_store(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _latest_valid_runtime_backup() -> Optional[Tuple[Path, Dict[str, Any]]]:
    if not RUNTIME_BACKUP_DIR.exists():
        return None
    for candidate in sorted(RUNTIME_BACKUP_DIR.glob("*.json"), reverse=True):
        payload = _try_load_store(candidate)
        if payload is not None:
            return candidate, payload
    return None


def _store_counts(payload: Dict[str, Any]) -> Dict[str, int]:
    if not isinstance(payload, dict):
        return {"presets_count": 0, "frases_count": 0}
    aspectos = payload.get("aspectos") or []
    presets = payload.get("presets") or []
    frases_count = 0
    for aspecto in aspectos:
        if not isinstance(aspecto, dict):
            continue
        frases_count += len(aspecto.get("frases") or [])
    return {"presets_count": len(presets), "frases_count": frases_count}


def _richest_valid_runtime_backup() -> Optional[Tuple[Path, Dict[str, Any], Dict[str, int]]]:
    if not RUNTIME_BACKUP_DIR.exists():
        return None
    best: Optional[Tuple[Path, Dict[str, Any], Dict[str, int]]] = None
    for candidate in sorted(RUNTIME_BACKUP_DIR.glob("*.json"), reverse=True):
        payload = _try_load_store(candidate)
        if payload is None:
            continue
        counts = _store_counts(payload)
        if best is None:
            best = (candidate, payload, counts)
            continue
        _, _, best_counts = best
        if (counts["presets_count"], counts["frases_count"]) > (
            best_counts["presets_count"],
            best_counts["frases_count"],
        ):
            best = (candidate, payload, counts)
    return best


def _recover_store_from_runtime_backup() -> Optional[Dict[str, Any]]:
    recovered = _latest_valid_runtime_backup()
    if recovered is None:
        return None
    _snapshot_current_store("corrupted_store")
    _, payload = recovered
    _atomic_write_store(payload)
    return payload


def _should_auto_recover_minimal_store(current_counts: Dict[str, int], recovered_counts: Dict[str, int]) -> bool:
    looks_like_minimal = (
        current_counts["presets_count"] <= DEFAULT_SAMPLE_PRESETS_COUNT + 1
        and current_counts["frases_count"] <= DEFAULT_SAMPLE_PHRASES_COUNT + 2
    )
    materially_richer_backup = (
        recovered_counts["presets_count"] >= current_counts["presets_count"] + 5
        or recovered_counts["frases_count"] >= current_counts["frases_count"] + 25
    )
    return looks_like_minimal and materially_richer_backup


def _maybe_recover_minimal_store(payload: Dict[str, Any]) -> Dict[str, Any]:
    current_counts = _store_counts(payload)
    richest = _richest_valid_runtime_backup()
    if richest is None:
        return payload
    _, candidate_payload, candidate_counts = richest
    if not _should_auto_recover_minimal_store(current_counts, candidate_counts):
        return payload
    _snapshot_current_store("minimal_store_before_auto_recover")
    recovered = _normalize_store(candidate_payload)
    _atomic_write_store(recovered)
    return recovered


def _build_default_store() -> Dict[str, Any]:
    next_phrase_id = 1
    aspectos: List[Dict[str, Any]] = []
    for aspecto in DEFAULT_ASPECTS:
        frases = []
        for frase in DEFAULT_SAMPLE_PHRASES.get(aspecto["key"], []):
            frases.append(
                {
                    "id": next_phrase_id,
                    "titulo": str(frase.get("titulo") or "").strip(),
                    "texto": str(frase.get("texto") or "").strip(),
                    "tags": list(frase.get("tags") or []),
                    "patologias": [],
                    "ordem": next_phrase_id * 10,
                    "ativo": 1,
                }
            )
            next_phrase_id += 1

        aspecto_item = dict(aspecto)
        aspecto_item["frases"] = frases
        aspectos.append(aspecto_item)

    presets = []
    for index, preset in enumerate(DEFAULT_SAMPLE_PRESETS, start=1):
        preset_item = deepcopy(preset)
        preset_item["id"] = index
        preset_item["ativo"] = 1
        presets.append(preset_item)

    return {
        "version": "1.0",
        "mode": "teste",
        "last_updated": _now_iso(),
        "aspectos": aspectos,
        "presets": presets,
    }


def _ensure_store_file() -> None:
    if FRASES_FILE.exists():
        return
    _atomic_write_store(_build_default_store())


def _load_store() -> Dict[str, Any]:
    _ensure_store_file()
    payload = _try_load_store(FRASES_FILE)
    if payload is not None:
        return _maybe_recover_minimal_store(payload)

    recovered = _recover_store_from_runtime_backup()
    if recovered is not None:
        return _maybe_recover_minimal_store(recovered)

    fallback = _build_default_store()
    _atomic_write_store(fallback)
    return fallback


def _save_store(store: Dict[str, Any], reason: str = "update") -> Dict[str, Any]:
    current = _try_load_store(FRASES_FILE)
    if current is not None and reason not in SAVE_REASONS_ALLOWING_SHRINK:
        current_counts = _store_counts(current)
        next_counts = _store_counts(store)
        shrunk = (
            next_counts["presets_count"] < current_counts["presets_count"]
            or next_counts["frases_count"] < current_counts["frases_count"]
        )
        if shrunk:
            raise ValueError(
                "Operacao bloqueada para evitar perda de dados no banco de frases/presets."
            )
    store["last_updated"] = _now_iso()
    _snapshot_current_store(reason)
    _atomic_write_store(store)
    return store


def _iter_phrase_locations(payload: Dict[str, Any]):
    for aspecto in payload.get("aspectos") or []:
        for frase in aspecto.get("frases") or []:
            yield aspecto, frase


def _next_phrase_id(payload: Dict[str, Any]) -> int:
    ids = [_to_int(frase.get("id")) for _, frase in _iter_phrase_locations(payload)]
    return max(ids + [0]) + 1


def _next_preset_id(payload: Dict[str, Any]) -> int:
    ids = [_to_int(preset.get("id")) for preset in payload.get("presets") or []]
    return max(ids + [0]) + 1


def _normalize_store(store: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _build_default_store()
    normalized.update(
        {
            "version": str(store.get("version") or normalized["version"]),
            "mode": str(store.get("mode") or normalized["mode"]),
            "last_updated": str(store.get("last_updated") or normalized["last_updated"]),
        }
    )

    next_phrase_id = 1
    aspectos_payload: List[Dict[str, Any]] = []
    aspect_index = {str(item.get("key") or ""): item for item in store.get("aspectos") or []}
    for default_aspect in DEFAULT_ASPECTS:
        incoming = aspect_index.get(default_aspect["key"], {})
        frases_in = incoming.get("frases") or []
        frases_out = []
        for index, frase in enumerate(frases_in, start=1):
            titulo = str(frase.get("titulo") or "").strip()
            texto = str(frase.get("texto") or "").strip()
            texto = _apply_conclusion_text_correction(default_aspect["key"], titulo, texto)
            if not titulo or not texto:
                continue
            frase_id = frase.get("id")
            if not isinstance(frase_id, int):
                frase_id = next_phrase_id
            next_phrase_id = max(next_phrase_id, frase_id + 1)
            frases_out.append(
                {
                    "id": frase_id,
                    "titulo": titulo,
                    "texto": texto,
                    "tags": _normalize_string_list(frase.get("tags")),
                    "patologias": _normalize_string_list(frase.get("patologias")),
                    "ordem": _to_int(frase.get("ordem"), index * 10),
                    "ativo": 1 if _to_int(frase.get("ativo"), 1) else 0,
                }
            )
        aspecto_out = dict(default_aspect)
        aspecto_out["frases"] = frases_out
        aspectos_payload.append(aspecto_out)

    presets_out = []
    next_preset_id = 1
    for preset in store.get("presets") or []:
        label = str(preset.get("label") or "").strip()
        if not label:
            continue
        preset_id = preset.get("id")
        if not isinstance(preset_id, int):
            preset_id = next_preset_id
        next_preset_id = max(next_preset_id, preset_id + 1)
        selecoes = []
        for selecao in preset.get("selecoes") or []:
            aspecto = str(selecao.get("aspecto") or "").strip()
            frase_titulo = str(selecao.get("frase_titulo") or "").strip()
            frase_id = selecao.get("frase_id")
            if not aspecto or (not frase_titulo and frase_id in (None, "")):
                continue
            selecoes.append(
                {
                    "aspecto": aspecto,
                    "frase_titulo": frase_titulo,
                    "frase_id": frase_id,
                }
            )
        presets_out.append(
            {
                "id": preset_id,
                "key": str(preset.get("key") or _slugify(label)).strip(),
                "label": label,
                "patologia": str(preset.get("patologia") or "").strip(),
                "grau": str(preset.get("grau") or "").strip(),
                "descricao": str(preset.get("descricao") or "").strip(),
                "tags": _normalize_string_list(preset.get("tags")),
                "ordem": _to_int(preset.get("ordem"), next_preset_id * 10),
                "ativo": 1 if _to_int(preset.get("ativo"), 1) else 0,
                "selecoes": selecoes,
            }
        )

    normalized["aspectos"] = aspectos_payload
    normalized["presets"] = presets_out
    return normalized


def get_payload() -> Dict[str, Any]:
    loaded = _load_store()
    normalized = _normalize_store(loaded)
    if normalized != loaded:
        return _save_store(normalized, reason="normalize")
    return normalized


def summarize_store(store: Dict[str, Any]) -> Dict[str, int]:
    aspectos = list(store.get("aspectos") or [])
    presets = list(store.get("presets") or [])
    frases_count = sum(len((aspecto.get("frases") or [])) for aspecto in aspectos)
    return {
        "aspectos_count": len(aspectos),
        "frases_count": frases_count,
        "presets_count": len(presets),
    }


def normalize_external_store(data: Dict[str, Any]) -> Dict[str, Any]:
    return _normalize_store(data)


def import_store(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_external_store(data)
    _save_store(normalized, reason="import")
    return normalized


def _find_aspect(payload: Dict[str, Any], aspecto_key: str) -> Optional[Dict[str, Any]]:
    return next((item for item in payload.get("aspectos") or [] if item.get("key") == aspecto_key), None)


def _find_phrase_location(
    payload: Dict[str, Any],
    aspecto_key: str,
    frase_id: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    aspecto = _find_aspect(payload, aspecto_key)
    if not aspecto:
        return None, None
    frase = next((item for item in aspecto.get("frases") or [] if item.get("id") == frase_id), None)
    return aspecto, frase


def _ensure_unique_phrase_title(
    aspecto: Dict[str, Any],
    titulo: str,
    ignore_phrase_id: Optional[int] = None,
) -> None:
    titulo_normalizado = titulo.casefold()
    for item in aspecto.get("frases") or []:
        if ignore_phrase_id is not None and item.get("id") == ignore_phrase_id:
            continue
        if str(item.get("titulo") or "").strip().casefold() == titulo_normalizado:
            raise ValueError("Ja existe uma frase com esse titulo neste aspecto.")


def _find_phrase(
    payload: Dict[str, Any],
    aspecto_key: str,
    frase_id: Any = None,
    frase_titulo: str = "",
) -> Optional[Dict[str, Any]]:
    aspecto = _find_aspect(payload, aspecto_key)
    if not aspecto:
        return None
    frases = aspecto.get("frases") or []
    if frase_id not in (None, ""):
        frase = next((item for item in frases if item.get("id") == int(frase_id)), None)
        if frase:
            return frase
    titulo = str(frase_titulo or "").strip()
    if titulo:
        return next((item for item in frases if str(item.get("titulo") or "").strip() == titulo), None)
    return None


def apply_preset(preset_id: int) -> Dict[str, Any]:
    payload = get_payload()
    preset = next((item for item in payload.get("presets") or [] if item.get("id") == preset_id), None)
    if not preset:
        raise KeyError("Preset nao encontrado.")

    textos: Dict[str, str] = {}
    selecoes_resolvidas: List[Dict[str, Any]] = []
    for selecao in preset.get("selecoes") or []:
        aspecto = str(selecao.get("aspecto") or "").strip()
        frase = _find_phrase(payload, aspecto, selecao.get("frase_id"), str(selecao.get("frase_titulo") or ""))
        if not aspecto or not frase:
            continue
        textos[aspecto] = str(frase.get("texto") or "").strip()
        selecoes_resolvidas.append(
            {
                "aspecto": aspecto,
                "frase_id": frase.get("id"),
                "frase_titulo": frase.get("titulo"),
            }
        )

    return {"preset": preset, "textos": textos, "selecoes_resolvidas": selecoes_resolvidas}


def save_preset(data: Dict[str, Any], preset_id: Optional[int] = None) -> Dict[str, Any]:
    payload = get_payload()
    presets = payload.get("presets") or []
    selecoes = []
    for selecao in data.get("selecoes") or []:
        aspecto = str(selecao.get("aspecto") or "").strip()
        frase = _find_phrase(payload, aspecto, selecao.get("frase_id"), str(selecao.get("frase_titulo") or ""))
        if not aspecto or not frase:
            continue
        selecoes.append(
            {
                "aspecto": aspecto,
                "frase_id": frase.get("id"),
                "frase_titulo": frase.get("titulo"),
            }
        )
    if not selecoes:
        raise ValueError("Selecione pelo menos uma frase para o preset.")

    target = next((item for item in presets if item.get("id") == preset_id), None) if preset_id else None
    if target is None:
        target = {"id": _next_preset_id(payload)}
        presets.append(target)

    label = str(data.get("label") or "").strip()
    if not label:
        raise ValueError("Informe o nome do preset.")

    target.update(
        {
            "key": str(data.get("key") or _slugify(str(data.get("label") or ""))).strip(),
            "label": label,
            "patologia": str(data.get("patologia") or "").strip(),
            "grau": str(data.get("grau") or "").strip(),
            "descricao": str(data.get("descricao") or "").strip(),
            "tags": _normalize_string_list(data.get("tags")),
            "ordem": _to_int(data.get("ordem"), _to_int(target.get("id")) * 10),
            "ativo": 1 if _to_int(data.get("ativo"), 1) else 0,
            "selecoes": selecoes,
        }
    )
    payload["presets"] = presets
    _save_store(payload, reason="save_preset")
    return target


def delete_preset(preset_id: int) -> None:
    payload = get_payload()
    preset = next((item for item in payload.get("presets") or [] if item.get("id") == preset_id), None)
    if not preset:
        raise KeyError("Preset nao encontrado.")
    preset["ativo"] = 0
    _save_store(payload, reason="delete_preset")


def restore_preset(preset_id: int) -> Dict[str, Any]:
    payload = get_payload()
    preset = next((item for item in payload.get("presets") or [] if item.get("id") == preset_id), None)
    if not preset:
        raise KeyError("Preset nao encontrado.")
    preset["ativo"] = 1
    _save_store(payload, reason="restore_preset")
    return preset


def duplicate_preset(preset_id: int, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = get_payload()
    source = next((item for item in payload.get("presets") or [] if item.get("id") == preset_id), None)
    if not source:
        raise KeyError("Preset nao encontrado.")

    data = data or {}
    clone = deepcopy(source)
    clone["id"] = _next_preset_id(payload)
    clone["label"] = str(data.get("label") or f"{source.get('label', 'Preset')} copia").strip()
    clone["key"] = str(data.get("key") or _slugify(clone["label"])).strip()
    clone["ordem"] = _to_int(data.get("ordem"), _to_int(source.get("ordem"), clone["id"] * 10) + 1)
    clone["ativo"] = 1
    payload["presets"] = list(payload.get("presets") or []) + [clone]
    _save_store(payload, reason="duplicate_preset")
    return clone


def create_phrase(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = get_payload()
    aspecto_key = str(data.get("aspecto") or "").strip()
    aspecto = _find_aspect(payload, aspecto_key)
    if not aspecto:
        raise KeyError("Aspecto nao encontrado.")

    titulo = str(data.get("titulo") or "").strip()
    texto = str(data.get("texto") or "").strip()
    if not titulo or not texto:
        raise ValueError("Titulo e texto da frase sao obrigatorios.")

    frases = aspecto.get("frases") or []
    _ensure_unique_phrase_title(aspecto, titulo)

    nova_frase = {
        "id": _next_phrase_id(payload),
        "titulo": titulo,
        "texto": texto,
        "tags": _normalize_string_list(data.get("tags")),
        "patologias": _normalize_string_list(data.get("patologias")),
        "ordem": _to_int(data.get("ordem"), (len(frases) + 1) * 10),
        "ativo": 1 if _to_int(data.get("ativo"), 1) else 0,
    }
    frases.append(nova_frase)
    aspecto["frases"] = frases
    _save_store(payload, reason="create_phrase")
    return nova_frase


def update_phrase(frase_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    payload = get_payload()
    aspecto_key = str(data.get("aspecto") or "").strip()
    aspecto, frase = _find_phrase_location(payload, aspecto_key, frase_id)
    if not aspecto:
        raise KeyError("Aspecto nao encontrado.")
    if not frase:
        raise KeyError("Frase nao encontrada.")

    novo_aspecto_key = str(data.get("novo_aspecto") or aspecto_key).strip()
    novo_aspecto = _find_aspect(payload, novo_aspecto_key)
    if not novo_aspecto:
        raise KeyError("Aspecto de destino nao encontrado.")

    titulo = str(data.get("titulo") or frase.get("titulo") or "").strip()
    texto = str(data.get("texto") or frase.get("texto") or "").strip()
    if not titulo or not texto:
        raise ValueError("Titulo e texto da frase sao obrigatorios.")
    _ensure_unique_phrase_title(novo_aspecto, titulo, ignore_phrase_id=frase_id)

    frase.update(
        {
            "titulo": titulo,
            "texto": texto,
            "tags": _normalize_string_list(data.get("tags", frase.get("tags"))),
            "patologias": _normalize_string_list(data.get("patologias", frase.get("patologias"))),
            "ordem": _to_int(data.get("ordem"), _to_int(frase.get("ordem"), 0)),
            "ativo": 1 if _to_int(data.get("ativo"), _to_int(frase.get("ativo"), 1)) else 0,
        }
    )

    if novo_aspecto_key != aspecto_key:
        aspecto["frases"] = [item for item in aspecto.get("frases") or [] if item.get("id") != frase_id]
        novo_frases = list(novo_aspecto.get("frases") or [])
        novo_frases.append(frase)
        novo_aspecto["frases"] = novo_frases

    _sync_phrase_references(
        payload,
        frase_id=frase_id,
        old_aspecto=aspecto_key,
        new_aspecto=novo_aspecto_key,
        new_titulo=titulo,
    )
    _save_store(payload, reason="update_phrase")
    return frase


def _sync_phrase_references(
    payload: Dict[str, Any],
    frase_id: int,
    old_aspecto: str,
    new_aspecto: str,
    new_titulo: str,
) -> None:
    for preset in payload.get("presets") or []:
        selecoes = list(preset.get("selecoes") or [])
        updated: List[Dict[str, Any]] = []
        for selecao in selecoes:
            matches = (
                str(selecao.get("aspecto") or "").strip() == old_aspecto
                and _to_int(selecao.get("frase_id"), -1) == frase_id
            )
            if not matches:
                updated.append(selecao)
                continue

            if new_aspecto != old_aspecto and any(
                str(item.get("aspecto") or "").strip() == new_aspecto
                and item is not selecao
                for item in selecoes
            ):
                continue

            next_selecao = dict(selecao)
            next_selecao["aspecto"] = new_aspecto
            next_selecao["frase_id"] = frase_id
            next_selecao["frase_titulo"] = new_titulo
            updated.append(next_selecao)
        preset["selecoes"] = updated


def duplicate_phrase(frase_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    payload = get_payload()
    aspecto_key = str(data.get("aspecto") or "").strip()
    aspecto, frase = _find_phrase_location(payload, aspecto_key, frase_id)
    if not aspecto:
        raise KeyError("Aspecto nao encontrado.")
    if not frase:
        raise KeyError("Frase nao encontrada.")

    destino_key = str(data.get("novo_aspecto") or aspecto_key).strip()
    destino = _find_aspect(payload, destino_key)
    if not destino:
        raise KeyError("Aspecto de destino nao encontrado.")

    titulo = str(data.get("titulo") or f"{frase.get('titulo', 'Frase')} copia").strip()
    texto = str(data.get("texto") or frase.get("texto") or "").strip()
    if not titulo or not texto:
        raise ValueError("Titulo e texto da frase sao obrigatorios.")
    _ensure_unique_phrase_title(destino, titulo)

    frases_destino = list(destino.get("frases") or [])
    clone = {
        "id": _next_phrase_id(payload),
        "titulo": titulo,
        "texto": texto,
        "tags": _normalize_string_list(data.get("tags", frase.get("tags"))),
        "patologias": _normalize_string_list(data.get("patologias", frase.get("patologias"))),
        "ordem": _to_int(data.get("ordem"), (len(frases_destino) + 1) * 10),
        "ativo": 1,
    }
    frases_destino.append(clone)
    destino["frases"] = frases_destino
    _save_store(payload, reason="duplicate_phrase")
    return clone


def set_phrase_active(frase_id: int, data: Dict[str, Any], ativo: int) -> Dict[str, Any]:
    payload = get_payload()
    aspecto_key = str(data.get("aspecto") or "").strip()
    aspecto, frase = _find_phrase_location(payload, aspecto_key, frase_id)
    if not aspecto:
        raise KeyError("Aspecto nao encontrado.")
    if not frase:
        raise KeyError("Frase nao encontrada.")
    frase["ativo"] = 1 if ativo else 0
    _save_store(payload, reason="restore_phrase" if ativo else "delete_phrase")
    return frase
