"""Separate the service-order payer from the clinic that originated the case."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20261116_111"
DESCRIPTION = "Registra clinica ou veterinario parceiro como responsavel financeiro da OS"


def upgrade(connection: Connection, dialect: str) -> None:
    if "ordens_servico" not in inspect(connection).get_table_names():
        return

    columns = {column["name"] for column in inspect(connection).get_columns("ordens_servico")}
    definitions = (
        ("responsavel_pagamento_tipo", "VARCHAR(20) NOT NULL DEFAULT 'clinica'"),
        ("responsavel_pagamento_id", "INTEGER NULL"),
        ("responsavel_pagamento_nome", "VARCHAR(255) NULL"),
        ("responsavel_pagamento_telefone", "VARCHAR(50) NULL"),
        ("responsavel_pagamento_email", "VARCHAR(255) NULL"),
    )
    for name, sql_type in definitions:
        if name not in columns:
            connection.execute(text(f"ALTER TABLE ordens_servico ADD COLUMN {name} {sql_type}"))

    # Os vínculos de OS antigas continuam sendo lidos pelas regras legadas.
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_ordens_servico_responsavel_pagamento "
        "ON ordens_servico (responsavel_pagamento_tipo, responsavel_pagamento_id, status)"
    ))
