"""Import existing staff identities; dry-run by default. No emails are sent.

Run from backend/: python scripts/import_supabase_auth_users.py [--apply]
Requires DATABASE_URL, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and
SUPABASE_SECRET_KEY in the server environment, including for read-only identity
inspection in dry-run mode. Never print passwords or hashes.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import SessionLocal
from app.models.user import User
from app.services import supabase_auth


def plan_import(users: list, identities: list[dict]) -> tuple[list, int]:
    pending = []
    linked = 0
    emails = [(user.email or "").strip().casefold() for user in users]
    if not all(emails) or len(set(emails)) != len(emails):
        raise ValueError("Emails locais ausentes ou duplicados; reconciliar antes da importacao.")
    for user in users:
        by_email = [item for item in identities if item.get("email", "").casefold() == user.email.casefold()]
        by_id = [item for item in identities if item.get("app_metadata", {}).get("fortcordis_user_id") == user.id]
        if by_email or by_id:
            if len(by_email) != 1 or len(by_id) != 1 or by_email[0]["id"] != by_id[0]["id"]:
                raise ValueError("Identidade existente sem vinculo consistente; reconciliar antes da importacao.")
            identity = by_id[0]
            UUID(identity["id"])
            if (type(identity.get("app_metadata", {}).get("fortcordis_user_id")) is not int
                or not identity.get("email_confirmed_at") or identity.get("is_anonymous")):
                raise ValueError("Identidade existente ainda nao pode autenticar a equipe.")
            linked += 1
            continue
        if not supabase_auth.has_importable_password_hash(user.senha_hash):
            raise ValueError("Usuario sem hash bcrypt compativel; importacao interrompida.")
        pending.append(user)
    return pending, linked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Criar identidades no Supabase; requer autorizacao do ambiente.")
    args = parser.parse_args()
    with SessionLocal() as db:
        users = db.query(User).order_by(User.id).all()
        identities = supabase_auth.admin_users()
        pending, linked = plan_import(users, identities)
        print(f"Contas: {len(users)}; vinculadas: {linked}; a importar: {len(pending)}; apply={args.apply}")
        if args.apply:
            for user in pending:
                supabase_auth.create_identity(user)
            # Verify every mapping through the actual Auth API after mutation.
            remaining, verified = plan_import(users, supabase_auth.admin_users())
            if remaining or verified != len(users):
                raise RuntimeError("Verificacao incompleta; nao ativar AUTH_PROVIDER=supabase.")
            print(f"Importacao verificada: {verified} contas. Nenhum email enviado.")


if __name__ == "__main__":
    main()
