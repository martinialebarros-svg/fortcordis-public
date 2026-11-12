#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.eco_study_extraction_service import (  # noqa: E402
    GE_VIVID_IQ_PROFILE,
    parse_eco_study_import_content,
)


# Selectors use only numeric suffixes (or the sole file without one), keeping
# patient-identifying filenames and the clinical images outside the repository.
GOLD_STUDIES: dict[str, dict[str, dict[str, float]]] = {
    "A": {
        "base": {"TAPSE": 23.33},
        "2": {"Vmax_pulmonar": 0.75, "Grad_pulmonar": 2.24},
        "3": {
            "PLVES": 11.26,
            "DIVES": 27.29,
            "VSF": 28,
            "FE_Teicholz": 62,
            "DeltaD_FS": 33,
            "SIVs": 13.46,
        },
        "4": {"Aorta": 20.55, "Atrio_esquerdo": 29.22, "AE_Ao": 1.42},
        "5": {"Onda_E": 0.56, "TD": 129, "Onda_A": 0.45, "E_A": 1.25},
        "6": {"E_E_linha": 4.64, "e_doppler": 0.12},
        "7": {"Vmax_aorta": 1.02, "Grad_aorta": 4.12},
    },
    "B": {
        "base": {
            "SIVd": 6.04,
            "DIVEd": 24.65,
            "PLVEd": 4.99,
            "SIVs": 10.18,
            "DIVES": 10.04,
            "PLVES": 8.99,
            "VDF": 22,
            "VSF": 2,
            "FE_Teicholz": 90,
            "DeltaD_FS": 59,
            "DIVEd_normalizado": 1.817,
        },
        "3": {"Vmax_pulmonar": 0.82, "Grad_pulmonar": 2.71},
        "4": {"Aorta": 8.47, "Atrio_esquerdo": 19.56, "AE_Ao": 2.31},
        "5": {"TRIV": 34, "Onda_E": 1.22, "TD": 80, "Onda_A": 1.05, "E_A": 1.16},
        "6": {"Vmax_aorta": 0.71, "Grad_aorta": 2.04},
        "7": {"IM_Vmax": 3.98},
    },
}

REPORT_GOLD: dict[str, float] = {
    "SIVd": 8.27,
    "DIVEd": 40.93,
    "VDF": 74,
    "PLVEd": 8.74,
    "SIVs": 13.46,
    "DIVES": 27.29,
    "VSF": 28,
    "FE_Teicholz": 62,
    "DeltaD_FS": 33,
    "PLVES": 11.26,
    "Aorta": 20.55,
    "Atrio_esquerdo": 29.22,
    "AE_Ao": 1.42,
    "TAPSE": 23.33,
    "Onda_E": 0.56,
    "TD": 129,
    "Onda_A": 0.45,
    "E_A": 1.25,
    "e_doppler": 0.12,
    "E_E_linha": 4.64,
    "Vmax_aorta": 1.02,
    "Grad_aorta": 4.12,
    "Vmax_pulmonar": 0.75,
    "Grad_pulmonar": 2.24,
}


def _matches(expected: float, actual: float) -> bool:
    return abs(float(expected) - float(actual)) <= 0.02


def _resolve_selector(directory: Path, selector: str) -> Path:
    images = [
        path
        for path in directory.glob("*.jpg")
        if path.is_file() and not path.name.startswith("._")
    ]
    if selector == "base":
        matches = [path for path in images if not re.search(r"\d+\.jpg$", path.name, re.IGNORECASE)]
    else:
        matches = [
            path
            for path in images
            if re.search(rf"{re.escape(selector)}\.jpg$", path.name, re.IGNORECASE)
        ]
    if len(matches) != 1:
        raise ValueError(f"Seletor {selector!r} encontrou {len(matches)} arquivos em {directory}")
    return matches[0]


def _evaluate_payload(source: str, expected: dict[str, float], payload: dict[str, Any]) -> dict[str, Any]:
    actual = payload.get("medidas") or {}
    missing: list[str] = []
    wrong: list[dict[str, Any]] = []
    correct = 0
    for field, expected_value in expected.items():
        if field not in actual:
            missing.append(f"{source}:{field}")
        elif _matches(expected_value, float(actual[field])):
            correct += 1
        else:
            wrong.append(
                {
                    "source": source,
                    "field": field,
                    "expected": expected_value,
                    "actual": actual[field],
                }
            )
    return {
        "expected": len(expected),
        "correct": correct,
        "missing": missing,
        "wrong": wrong,
        "unexpected": sorted(field for field in actual if field not in expected),
        "profile": (payload.get("meta_importacao_estudo") or {}).get("perfil"),
        "conflicts": (payload.get("meta_importacao_estudo") or {}).get("conflitos"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Avalia o perfil OCR GE Vivid IQ sem copiar estudos clinicos para o repositorio."
    )
    parser.add_argument("--study-a-dir", required=True, type=Path)
    parser.add_argument("--study-b-dir", required=True, type=Path)
    parser.add_argument("--report-pdf", required=True, type=Path)
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    for label, directory in (("A", args.study_a_dir), ("B", args.study_b_dir)):
        for selector, expected in GOLD_STUDIES[label].items():
            path = _resolve_selector(directory, selector)
            payload = parse_eco_study_import_content(path.name, path.read_bytes())
            results.append(_evaluate_payload(f"{label}/{selector}", expected, payload))

    report_payload = parse_eco_study_import_content(args.report_pdf.name, args.report_pdf.read_bytes())
    results.append(_evaluate_payload("report", REPORT_GOLD, report_payload))

    expected_total = sum(item["expected"] for item in results)
    correct_total = sum(item["correct"] for item in results)
    report = {
        "expected": expected_total,
        "correct": correct_total,
        "recall": round(correct_total / expected_total, 4) if expected_total else 1.0,
        "missing": [value for item in results for value in item["missing"]],
        "wrong": [value for item in results for value in item["wrong"]],
        "unexpected": [
            f"{index}:{field}"
            for index, item in enumerate(results, start=1)
            for field in item["unexpected"]
        ],
        "profiles": sorted({str(item["profile"]) for item in results}),
        "conflicts": sum(int(item["conflicts"] or 0) for item in results),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    passed = (
        correct_total == expected_total
        and not report["unexpected"]
        and report["profiles"] == [GE_VIVID_IQ_PROFILE]
        and report["conflicts"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
