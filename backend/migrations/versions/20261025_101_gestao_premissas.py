"""Premissas manuais exclusivas do backend administrativo, sem dados semeados."""
from sqlalchemy import text

VERSION = "20261025_101"
DESCRIPTION = "Premissas versionadas do painel administrativo de gestão"


def upgrade(connection, dialect):
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError("Gestão requer SQLite ou PostgreSQL")
    from app.models.gestao import GestaoPremissas

    GestaoPremissas.__table__.create(bind=connection, checkfirst=True)
    if dialect == "postgresql":
        connection.execute(text('ALTER TABLE gestao_premissas ENABLE ROW LEVEL SECURITY'))
        connection.execute(text('REVOKE ALL ON TABLE gestao_premissas FROM PUBLIC'))
        for role in ("anon", "authenticated"):
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                connection.execute(text(f'REVOKE ALL ON TABLE gestao_premissas FROM "{role}"'))
