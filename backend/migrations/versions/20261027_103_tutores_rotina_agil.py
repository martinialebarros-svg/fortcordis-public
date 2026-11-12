"""Complemento opcional, confirmacao rastreavel e repeticao segura de cadastros."""
from sqlalchemy import inspect, text

VERSION = "20261027_103"
DESCRIPTION = "Adiciona historico de identificacao, contatos, origens e operacoes de tutores"


def upgrade(connection, dialect):
    if "tutores" not in inspect(connection).get_table_names():
        return
    from app.models.tutor_rotina import (
        TutorContato, TutorDuplicidadeDescarte, TutorIdentificacaoEvento,
        TutorOperacao, TutorOrigem,
    )
    for model in (TutorIdentificacaoEvento, TutorContato, TutorOrigem,
                  TutorDuplicidadeDescarte, TutorOperacao):
        model.__table__.create(connection, checkfirst=True)
        if dialect == "postgresql":
            name = model.__tablename__
            connection.execute(text(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY'))
            connection.execute(text(f'REVOKE ALL ON "{name}" FROM PUBLIC'))
            for role in ("anon", "authenticated"):
                if connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {"role": role}).scalar():
                    connection.execute(text(f'REVOKE ALL ON "{name}" FROM "{role}"'))
