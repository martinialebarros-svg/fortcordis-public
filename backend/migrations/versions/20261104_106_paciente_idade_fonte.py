"""Separate declared age from birth date; never infer provenance of old rows."""
from sqlalchemy import inspect, text

VERSION = "20261104_106"
DESCRIPTION = "Idade informada, data de referência e fonte do paciente"


def upgrade(connection, dialect):
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError("Migração de idade requer SQLite ou PostgreSQL")
    columns = {column["name"] for column in inspect(connection).get_columns("pacientes")}
    for name, kind in (("idade_informada", "TEXT"), ("idade_referencia", "DATE"), ("idade_fonte", "TEXT")):
        if name not in columns:
            connection.execute(text(f'ALTER TABLE pacientes ADD COLUMN {name} {kind}'))
