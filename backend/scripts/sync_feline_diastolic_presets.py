"""Synchronize feline diastolic phrases without replacing customized runtime content.

Dry-run by default. Use --apply after reviewing the printed changes. The runtime
bank is backed up before any write because VPS deploys preserve that file.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parents[1] / "data" / "frases_ecocardiograma_estruturado_teste.json"

# These are interpretive options, not diagnoses or rules computed from E/A alone.
PATTERNS = (
    (
        "preservada", "Função diastólica felina: padrão preservado",
        "Função diastólica ventricular esquerda sem alteração relevante nos parâmetros avaliáveis do exame.",
        "Selecionar após integrar fluxo transmitral, Doppler tecidual e dimensões atriais; não aplicar apenas por E/A normal.",
    ),
    (
        "relaxamento", "Função diastólica felina: relaxamento retardado",
        "Padrão de relaxamento ventricular esquerdo retardado, conforme avaliação integrada dos parâmetros diastólicos disponíveis.",
        "Corresponde ao padrão de relaxamento alterado (classe 2 no estudo felino); considerar E/A, IVRT, e' e tamanho atrial, sem atribuição automática à idade.",
    ),
    (
        "pseudonormal", "Função diastólica felina: padrão pseudonormal",
        "Padrão de enchimento ventricular esquerdo pseudonormal, identificado pela avaliação conjunta do fluxo transmitral e dos demais marcadores diastólicos disponíveis.",
        "E/A aparentemente usual não basta: integrar e', átrio esquerdo, IVRT e, quando disponível, fluxo venoso pulmonar.",
    ),
    (
        "restritivo", "Função diastólica felina: padrão restritivo",
        "Padrão de enchimento ventricular esquerdo restritivo, segundo a avaliação integrada dos parâmetros diastólicos disponíveis.",
        "Descreve o padrão de enchimento, sem diagnosticar cardiomiopatia restritiva ou insuficiência cardíaca por si só.",
    ),
    (
        "indeterminada", "Função diastólica felina: classificação indeterminada",
        "Classificação do padrão diastólico indeterminada neste exame, devido à limitação ou discordância dos parâmetros disponíveis.",
        "Usar quando fusão E/A, taquicardia, medidas ausentes ou resultados discordantes impedirem classificação segura.",
    ),
)

# Only known seed titles in known feline presets are adjusted. A runtime-assigned
# phrase ID does not turn the original catalog choice into a customization.
SEED_SELECTIONS = {
    "hcm_leve": "Disfunção diástólica leve",
    "hcm_moderada": "Disfunção diástólica por HCM",
    "hcm_importante": "Disfunção diástólica por HCM com padrao restritivo",
    "hcm_obstrutiva_sam": "Disfunção diástólica por HCM",
    "restritiva_felina": "Disfunção diástólica restritiva felina",
    "dcm_felina": "Padrao restritivo",
    "disfuncao_diastolica_relevante": "Padrao restritivo",
}


def synchronize(bank: dict) -> list[str]:
    changes: list[str] = []
    aspect = next(item for item in bank["aspectos"] if item["key"] == "funcao_diastolica")
    phrases = aspect["frases"]
    presets = bank["presets"]
    next_phrase_id = max((phrase["id"] for item in bank["aspectos"] for phrase in item["frases"]), default=0) + 1
    next_preset_id = max((preset["id"] for preset in presets), default=0) + 1

    for index, (slug, title, body, guidance) in enumerate(PATTERNS, start=1):
        if not any(phrase.get("titulo") == title for phrase in phrases):
            phrases.append({
                "id": next_phrase_id, "titulo": title, "texto": body,
                "tags": ["gato", "diastolica", slug], "patologias": [],
                "ordem": 110 + index * 10, "ativo": 1,
            })
            next_phrase_id += 1
            changes.append(f"frase: {title}")
        key = f"felino_diastolica_{slug}"
        if not any(preset.get("key") == key for preset in presets):
            presets.append({
                "id": next_preset_id, "key": key, "label": title,
                "patologia": "Função diastólica felina", "grau": "",
                "descricao": guidance, "tags": ["gato", "diastolica", "complementar"],
                "ordem": 510 + index * 10, "ativo": 1,
                "selecoes": [{"aspecto": "funcao_diastolica", "frase_titulo": title, "frase_id": None}],
            })
            next_preset_id += 1
            changes.append(f"preset: {key}")

    for preset in presets:
        expected = SEED_SELECTIONS.get(preset.get("key"))
        if not expected or "gato" not in preset.get("tags", []):
            continue
        selections = preset.get("selecoes", [])
        retained = [selection for selection in selections if not (
            selection.get("aspecto") == "funcao_diastolica"
            and selection.get("frase_titulo") == expected
        )]
        if len(retained) != len(selections):
            preset["selecoes"] = retained
            changes.append(f"remove classificação automática: {preset['key']}")
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    original = args.file.read_text(encoding="utf-8")
    bank = json.loads(original)
    changes = synchronize(bank)
    print("\n".join(changes) if changes else "Nenhuma alteração necessária.")
    if not args.apply or not changes:
        return
    backup_dir = args.file.parent / "runtime_backups" / "frases_ecocardiograma_estruturado_teste"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{datetime.now():%Y%m%d_%H%M%S_%f}__before_feline_diastolic_sync.json"
    shutil.copy2(args.file, backup)
    bank["last_updated"] = datetime.now().isoformat()
    tmp = args.file.with_suffix(args.file.suffix + ".tmp")
    tmp.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(args.file)
    print(f"Aplicado. Backup: {backup}")


if __name__ == "__main__":
    main()
