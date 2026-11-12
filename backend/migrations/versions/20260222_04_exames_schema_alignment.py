"""Aligns legacy stage schema for `exames` with current model usage."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260222_04"
DESCRIPTION = "Alinha schema legado de exames (colunas e defaults)"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _add_missing_columns(connection: Connection, columns: dict) -> None:
    add_statements = {
        "laudo_id": "ALTER TABLE exames ADD COLUMN laudo_id INTEGER",
        "tipo_exame": "ALTER TABLE exames ADD COLUMN tipo_exame VARCHAR(255)",
        "resultado": "ALTER TABLE exames ADD COLUMN resultado TEXT",
        "valor_referencia": "ALTER TABLE exames ADD COLUMN valor_referencia TEXT",
        "unidade": "ALTER TABLE exames ADD COLUMN unidade VARCHAR(255)",
        "status": "ALTER TABLE exames ADD COLUMN status VARCHAR(255) DEFAULT 'Solicitado'",
        "data_solicitacao": "ALTER TABLE exames ADD COLUMN data_solicitacao TIMESTAMP",
        "data_resultado": "ALTER TABLE exames ADD COLUMN data_resultado TIMESTAMP",
        "valor": "ALTER TABLE exames ADD COLUMN valor DOUBLE PRECISION DEFAULT 0",
        "observacoes": "ALTER TABLE exames ADD COLUMN observacoes TEXT",
        "created_at": "ALTER TABLE exames ADD COLUMN created_at TIMESTAMP",
        "criado_por_id": "ALTER TABLE exames ADD COLUMN criado_por_id INTEGER",
        "criado_por_nome": "ALTER TABLE exames ADD COLUMN criado_por_nome VARCHAR(255)",
    }

    for column_name, sql in add_statements.items():
        if column_name not in columns:
            connection.execute(text(sql))


def _align_postgres_defaults(connection: Connection) -> None:
    # Defaults seguros para inserts novos.
    connection.execute(text("ALTER TABLE exames ALTER COLUMN status SET DEFAULT 'Solicitado'"))
    connection.execute(text("ALTER TABLE exames ALTER COLUMN valor SET DEFAULT 0"))
    connection.execute(text("ALTER TABLE exames ALTER COLUMN data_solicitacao SET DEFAULT NOW()"))
    connection.execute(text("ALTER TABLE exames ALTER COLUMN created_at SET DEFAULT NOW()"))

    # Backfill de registros antigos.
    connection.execute(
        text("UPDATE exames SET status = 'Solicitado' WHERE status IS NULL OR status = ''")
    )
    connection.execute(text("UPDATE exames SET valor = 0 WHERE valor IS NULL"))
    connection.execute(text("UPDATE exames SET data_solicitacao = NOW() WHERE data_solicitacao IS NULL"))
    connection.execute(text("UPDATE exames SET created_at = NOW() WHERE created_at IS NULL"))


def _align_sqlite_defaults(connection: Connection) -> None:
    # SQLite não permite alterar default com a mesma flexibilidade do Postgres.
    connection.execute(
        text("UPDATE exames SET status = 'Solicitado' WHERE status IS NULL OR status = ''")
    )
    connection.execute(text("UPDATE exames SET valor = 0 WHERE valor IS NULL"))
    connection.execute(
        text(
            """
            UPDATE exames
            SET data_solicitacao = strftime('%Y-%m-%d %H:%M:%S', 'now')
            WHERE data_solicitacao IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE exames
            SET created_at = strftime('%Y-%m-%d %H:%M:%S', 'now')
            WHERE created_at IS NULL
            """
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "exames" not in inspector.get_table_names():
        return

    columns = _column_map(connection, "exames")
    _add_missing_columns(connection, columns)

    if dialect == "postgresql":
        _align_postgres_defaults(connection)
    elif dialect == "sqlite":
        _align_sqlite_defaults(connection)
