#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.eco_study_extraction_service import (
    GE_LOGIQ_E_PROFILE,
    parse_eco_study_import_content,
)


GOLD_STUDIES: dict[str, dict[str, dict[str, float]]] = {
    "A": {
        "Image04.jpg": {
            "SIVd": 5.0,
            "DIVEd": 25.7,
            "PLVEd": 3.9,
            "SIVs": 8.4,
            "DIVES": 14.7,
            "PLVES": 6.7,
            "VDF": 23.94,
            "VSF": 5.77,
            "FE_Teicholz": 75.91,
            "DeltaD_FS": 42.75,
            "DIVEd_normalizado": 1.65,
        },
        "Image05.jpg": {"Aorta": 12.3, "Atrio_esquerdo": 12.0, "AE_Ao": 0.98},
        "Image06.jpg": {"Vmax_pulmonar": 0.90, "Grad_pulmonar": 3.27},
        "Image07.jpg": {
            "Onda_E": 0.80,
            "TD": 74.21,
            "Onda_A": 0.59,
            "E_A": 1.35,
            "TRIV": 26.67,
        },
        "Image08.jpg": {"MAPSE": 8.0},
        "Image09.jpg": {"e_doppler": 0.09, "a_doppler": 0.08, "E_E_linha": 8.47},
        "Image10.jpg": {"Vmax_aorta": 0.87, "Grad_aorta": 3.01},
        "Image11.jpg": {"TAPSE": 14.7},
    },
    "B": {
        "Image03.jpg": {"Aorta": 8.8, "Atrio_esquerdo": 10.6, "AE_Ao": 1.20},
        "Image04.jpg": {
            "SIVd": 4.0,
            "DIVEd": 19.4,
            "PLVEd": 3.7,
            "SIVs": 7.1,
            "DIVES": 9.3,
            "PLVES": 6.4,
            "VDF": 11.79,
            "VSF": 1.70,
            "FE_Teicholz": 85.59,
            "DeltaD_FS": 52.0,
            "DIVEd_normalizado": 1.54,
        },
        "Image05.jpg": {"Vmax_pulmonar": 0.55, "Grad_pulmonar": 1.21},
        "Image07.jpg": {
            "Onda_E": 0.60,
            "TD": 84.43,
            "Onda_A": 0.78,
            "E_A": 0.76,
            "TRIV": 40.0,
        },
        "Image08.jpg": {"e_doppler": 0.07, "a_doppler": 0.08, "E_E_linha": 8.23},
        "Image09.jpg": {"MAPSE": 6.7},
        "Image10.jpg": {"MAPSE": 6.1},
        "Image11.jpg": {"Vmax_aorta": 0.97, "Grad_aorta": 3.80},
        "Image12.jpg": {"TAPSE": 8.5},
    },
}


def _matches(expected: float, actual: float) -> bool:
    return abs(float(expected) - float(actual)) <= 0.02


def evaluate_study(label: str, directory: Path) -> dict[str, Any]:
    expected_by_file = GOLD_STUDIES[label]
    correct = 0
    expected_total = sum(len(values) for values in expected_by_file.values())
    missing: list[str] = []
    wrong: list[dict[str, Any]] = []
    unexpected: list[str] = []
    profiles: set[str] = set()

    for filename, expected_fields in expected_by_file.items():
        path = directory / filename
        if not path.is_file():
            missing.extend(f"{label}/{filename}:{field}" for field in expected_fields)
            continue
        try:
            payload = parse_eco_study_import_content(filename, path.read_bytes())
        except Exception as exc:
            wrong.append({"source": f"{label}/{filename}", "error": str(exc)})
            continue

        actual_fields = payload.get("medidas") or {}
        profile = (payload.get("meta_importacao_estudo") or {}).get("perfil")
        if profile:
            profiles.add(str(profile))
        for field, expected in expected_fields.items():
            if field not in actual_fields:
                missing.append(f"{label}/{filename}:{field}")
                continue
            actual = float(actual_fields[field])
            if _matches(expected, actual):
                correct += 1
            else:
                wrong.append(
                    {
                        "source": f"{label}/{filename}",
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    }
                )
        unexpected.extend(
            f"{label}/{filename}:{field}"
            for field in actual_fields
            if field not in expected_fields
        )

    return {
        "study": label,
        "expected": expected_total,
        "correct": correct,
        "recall": round(correct / expected_total, 4) if expected_total else 1.0,
        "missing": missing,
        "wrong": wrong,
        "unexpected": unexpected,
        "profiles": sorted(profiles),
        "profile_ok": profiles == {GE_LOGIQ_E_PROFILE},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Avalia o perfil OCR GE LOGIQ e sem copiar os estudos para o repositorio."
    )
    parser.add_argument("--study-a-dir", required=True, type=Path)
    parser.add_argument("--study-b-dir", required=True, type=Path)
    args = parser.parse_args()

    results = [
        evaluate_study("A", args.study_a_dir),
        evaluate_study("B", args.study_b_dir),
    ]
    expected = sum(result["expected"] for result in results)
    correct = sum(result["correct"] for result in results)
    report = {
        "expected": expected,
        "correct": correct,
        "recall": round(correct / expected, 4) if expected else 1.0,
        "studies": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    profiles_ok = all(result["profile_ok"] for result in results)
    return 0 if correct == expected and profiles_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
