import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.services import frases_ecocardiograma_estruturado_teste_service as service


def build_report(source_path: Path, apply: bool) -> dict:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    before_store = service.get_payload()
    normalized = service.normalize_external_store(payload)

    report = {
        "source": str(source_path),
        "apply": apply,
        "before": service.summarize_store(before_store),
        "after": service.summarize_store(normalized),
    }

    if apply:
        persisted = service.import_store(payload)
        report["persisted"] = service.summarize_store(persisted)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importa o banco estruturado de frases/presets de ecocardiograma."
    )
    parser.add_argument("source", help="Caminho para o JSON completo de aspectos e presets.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica a importacao no store local. Sem esta flag, roda apenas dry-run.",
    )
    args = parser.parse_args()

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(
            json.dumps(
                {
                    "error": "source_not_found",
                    "source": str(source_path),
                },
                ensure_ascii=False,
            )
        )
        return 1

    report = build_report(source_path, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
