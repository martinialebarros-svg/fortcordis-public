import argparse
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sincroniza modulos faltantes na matriz de permissoes.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica as alteracoes no banco. Sem esta flag, executa apenas dry-run.",
    )
    parser.add_argument(
        "--module",
        action="append",
        dest="modules",
        default=[],
        help="Filtra a sincronizacao para um modulo especifico. Pode repetir.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    backend_dir = Path(__file__).resolve().parent
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

    os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
    os.environ.setdefault(
        "SECRET_KEY",
        "permission-matrix-sync-local-secret-key-1234567890",
    )

    from app.api.v1.endpoints.admin import _sync_permission_matrix
    from app.db.database import SessionLocal

    modules = {
        str(module or "").strip()
        for module in (args.modules or [])
        if str(module or "").strip()
    } or None

    db = SessionLocal()
    try:
        result = _sync_permission_matrix(
            db,
            modules=modules,
            commit=bool(args.apply),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.close()

    output = {
        "dry_run": not bool(args.apply),
        **result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
