"""Resumable, private draft-only Atendimento analysis."""
from sqlalchemy import text

VERSION = "20261108_109"
DESCRIPTION = "Lotes privados de audio e exames com retomada e revisao clinica"


def upgrade(connection, dialect):
    from app.models.atendimento_assistente_lote import AtendimentoAssistenteLote, AtendimentoAssistenteLoteArquivo

    for model in (AtendimentoAssistenteLote, AtendimentoAssistenteLoteArquivo):
        model.__table__.create(connection, checkfirst=True)
        if dialect == "postgresql":
            table = model.__tablename__
            connection.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            connection.execute(text(f'REVOKE ALL ON "{table}" FROM PUBLIC'))
            for role in ("anon", "authenticated"):
                if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                    connection.execute(text(f'REVOKE ALL ON "{table}" FROM "{role}"'))
