"""Link standalone ECG uploads to service orders without manufacturing appointments."""
from __future__ import annotations

import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20261005_95"
DESCRIPTION = "Permite OS de laudo de eletro sem agenda, com idempotencia persistida"


def _nullable_agendamento_sqlite(connection: Connection) -> None:
    columns = inspect(connection).get_columns("ordens_servico")
    if next(column for column in columns if column["name"] == "agendamento_id")["nullable"]:
        return
    original_sql = connection.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ordens_servico'"
    )).scalar_one()
    new_sql, changed = re.subn(
        r'((?:"agendamento_id"|`agendamento_id`|\[agendamento_id\]|\bagendamento_id\b)\s+INTEGER)\s+NOT\s+NULL',
        r'\1', original_sql, flags=re.IGNORECASE,
    )
    if changed != 1:
        raise RuntimeError("Nao foi possivel preservar o schema de ordens_servico ao liberar agendamento_id.")
    new_sql = re.sub(
        r'^(CREATE\s+TABLE\s+)(?:"ordens_servico"|`ordens_servico`|\[ordens_servico\]|ordens_servico)',
        r'\1"ordens_servico__laudo_new"', new_sql, count=1, flags=re.IGNORECASE,
    )
    # Preserve all indexes/triggers, including ones introduced by later releases.
    auxiliary_sql = connection.execute(text(
        "SELECT sql FROM sqlite_master WHERE tbl_name='ordens_servico' "
        "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
    )).scalars().all()
    names = ", ".join('"' + column["name"].replace('"', '""') + '"' for column in columns)
    connection.execute(text(new_sql))
    connection.execute(text(f'INSERT INTO ordens_servico__laudo_new ({names}) SELECT {names} FROM ordens_servico'))
    connection.execute(text("DROP TABLE ordens_servico"))
    connection.execute(text("ALTER TABLE ordens_servico__laudo_new RENAME TO ordens_servico"))
    for sql in auxiliary_sql:
        connection.execute(text(sql))


def upgrade(connection: Connection, dialect: str) -> None:
    if "ordens_servico" not in inspect(connection).get_table_names():
        return
    columns = {column["name"] for column in inspect(connection).get_columns("ordens_servico")}
    for name, column_type in (("laudo_id", "INTEGER"), ("idempotency_key", "VARCHAR(200)"), ("request_hash", "VARCHAR(64)")):
        if name not in columns:
            connection.execute(text(f"ALTER TABLE ordens_servico ADD COLUMN {name} {column_type} NULL"))
    if dialect == "postgresql":
        connection.execute(text("ALTER TABLE ordens_servico ALTER COLUMN agendamento_id DROP NOT NULL"))
    elif dialect == "sqlite":
        _nullable_agendamento_sqlite(connection)
    else:
        raise RuntimeError(f"Dialeto nao suportado para OS sem agenda: {dialect}")
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ordens_servico_laudo_ativa ON ordens_servico (laudo_id) "
        "WHERE laudo_id IS NOT NULL AND COALESCE(status, '') <> 'Cancelado'"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ordens_servico_idempotency_key ON ordens_servico (idempotency_key)"
    ))
