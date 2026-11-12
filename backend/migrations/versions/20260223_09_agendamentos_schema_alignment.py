"""Aligns legacy `agendamentos` schema with current API/model usage."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260223_09"
DESCRIPTION = "Alinha schema legado de agendamentos (colunas usadas pela API)"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _add_missing_columns(connection: Connection, dialect: str, columns: dict) -> None:
    if dialect == "postgresql":
        add_statements = {
            "paciente_id": "ALTER TABLE agendamentos ADD COLUMN paciente_id INTEGER",
            "clinica_id": "ALTER TABLE agendamentos ADD COLUMN clinica_id INTEGER",
            "servico_id": "ALTER TABLE agendamentos ADD COLUMN servico_id INTEGER",
            "inicio": "ALTER TABLE agendamentos ADD COLUMN inicio TIMESTAMP",
            "fim": "ALTER TABLE agendamentos ADD COLUMN fim TIMESTAMP",
            "data": "ALTER TABLE agendamentos ADD COLUMN data TEXT",
            "hora": "ALTER TABLE agendamentos ADD COLUMN hora TEXT",
            "status": "ALTER TABLE agendamentos ADD COLUMN status VARCHAR(50) DEFAULT 'Agendado'",
            "observacoes": "ALTER TABLE agendamentos ADD COLUMN observacoes TEXT",
            "paciente": "ALTER TABLE agendamentos ADD COLUMN paciente TEXT",
            "tutor": "ALTER TABLE agendamentos ADD COLUMN tutor TEXT",
            "telefone": "ALTER TABLE agendamentos ADD COLUMN telefone TEXT",
            "servico": "ALTER TABLE agendamentos ADD COLUMN servico TEXT",
            "clinica": "ALTER TABLE agendamentos ADD COLUMN clinica TEXT",
            "pacote_id": "ALTER TABLE agendamentos ADD COLUMN pacote_id INTEGER",
            "created_at": "ALTER TABLE agendamentos ADD COLUMN created_at TIMESTAMP DEFAULT NOW()",
            "updated_at": "ALTER TABLE agendamentos ADD COLUMN updated_at TIMESTAMP",
            "criado_em": "ALTER TABLE agendamentos ADD COLUMN criado_em TIMESTAMP",
            "atualizado_em": "ALTER TABLE agendamentos ADD COLUMN atualizado_em TIMESTAMP",
            "criado_por_id": "ALTER TABLE agendamentos ADD COLUMN criado_por_id INTEGER",
            "criado_por_nome": "ALTER TABLE agendamentos ADD COLUMN criado_por_nome VARCHAR(255)",
            "confirmado_por_id": "ALTER TABLE agendamentos ADD COLUMN confirmado_por_id INTEGER",
            "confirmado_por_nome": "ALTER TABLE agendamentos ADD COLUMN confirmado_por_nome VARCHAR(255)",
            "confirmado_em": "ALTER TABLE agendamentos ADD COLUMN confirmado_em TIMESTAMP",
        }
    else:
        add_statements = {
            "paciente_id": "ALTER TABLE agendamentos ADD COLUMN paciente_id INTEGER",
            "clinica_id": "ALTER TABLE agendamentos ADD COLUMN clinica_id INTEGER",
            "servico_id": "ALTER TABLE agendamentos ADD COLUMN servico_id INTEGER",
            "inicio": "ALTER TABLE agendamentos ADD COLUMN inicio DATETIME",
            "fim": "ALTER TABLE agendamentos ADD COLUMN fim DATETIME",
            "data": "ALTER TABLE agendamentos ADD COLUMN data TEXT",
            "hora": "ALTER TABLE agendamentos ADD COLUMN hora TEXT",
            "status": "ALTER TABLE agendamentos ADD COLUMN status TEXT DEFAULT 'Agendado'",
            "observacoes": "ALTER TABLE agendamentos ADD COLUMN observacoes TEXT",
            "paciente": "ALTER TABLE agendamentos ADD COLUMN paciente TEXT",
            "tutor": "ALTER TABLE agendamentos ADD COLUMN tutor TEXT",
            "telefone": "ALTER TABLE agendamentos ADD COLUMN telefone TEXT",
            "servico": "ALTER TABLE agendamentos ADD COLUMN servico TEXT",
            "clinica": "ALTER TABLE agendamentos ADD COLUMN clinica TEXT",
            "pacote_id": "ALTER TABLE agendamentos ADD COLUMN pacote_id INTEGER",
            "created_at": "ALTER TABLE agendamentos ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE agendamentos ADD COLUMN updated_at DATETIME",
            "criado_em": "ALTER TABLE agendamentos ADD COLUMN criado_em DATETIME",
            "atualizado_em": "ALTER TABLE agendamentos ADD COLUMN atualizado_em DATETIME",
            "criado_por_id": "ALTER TABLE agendamentos ADD COLUMN criado_por_id INTEGER",
            "criado_por_nome": "ALTER TABLE agendamentos ADD COLUMN criado_por_nome TEXT",
            "confirmado_por_id": "ALTER TABLE agendamentos ADD COLUMN confirmado_por_id INTEGER",
            "confirmado_por_nome": "ALTER TABLE agendamentos ADD COLUMN confirmado_por_nome TEXT",
            "confirmado_em": "ALTER TABLE agendamentos ADD COLUMN confirmado_em DATETIME",
        }

    for column_name, sql in add_statements.items():
        if column_name not in columns:
            connection.execute(text(sql))


def _backfill_postgres(connection: Connection, columns: dict) -> None:
    if "status" in columns:
        connection.execute(
            text(
                """
                UPDATE agendamentos
                SET status = 'Agendado'
                WHERE status IS NULL OR BTRIM(status) = ''
                """
            )
        )

    if "inicio" in columns and "data" in columns and "hora" in columns:
        connection.execute(
            text(
                """
                UPDATE agendamentos
                SET
                    data = COALESCE(data, SUBSTRING(inicio::text FROM 1 FOR 10)),
                    hora = COALESCE(hora, SUBSTRING(inicio::text FROM 12 FOR 5))
                WHERE inicio IS NOT NULL
                  AND (data IS NULL OR hora IS NULL)
                """
            )
        )

    if "created_at" in columns:
        connection.execute(text("UPDATE agendamentos SET created_at = NOW() WHERE created_at IS NULL"))
        connection.execute(text("ALTER TABLE agendamentos ALTER COLUMN created_at SET DEFAULT NOW()"))

    if "updated_at" in columns:
        connection.execute(text("UPDATE agendamentos SET updated_at = NOW() WHERE updated_at IS NULL"))
        connection.execute(text("ALTER TABLE agendamentos ALTER COLUMN updated_at SET DEFAULT NOW()"))


def _backfill_sqlite(connection: Connection, columns: dict) -> None:
    if "status" in columns:
        connection.execute(
            text(
                """
                UPDATE agendamentos
                SET status = 'Agendado'
                WHERE status IS NULL OR TRIM(status) = ''
                """
            )
        )

    if "inicio" in columns and "data" in columns and "hora" in columns:
        connection.execute(
            text(
                """
                UPDATE agendamentos
                SET
                    data = COALESCE(data, substr(CAST(inicio AS TEXT), 1, 10)),
                    hora = COALESCE(hora, substr(CAST(inicio AS TEXT), 12, 5))
                WHERE inicio IS NOT NULL
                  AND (data IS NULL OR hora IS NULL)
                """
            )
        )

    if "created_at" in columns and "updated_at" in columns:
        connection.execute(
            text(
                """
                UPDATE agendamentos
                SET
                    created_at = COALESCE(created_at, strftime('%Y-%m-%d %H:%M:%S', 'now')),
                    updated_at = COALESCE(updated_at, strftime('%Y-%m-%d %H:%M:%S', 'now'))
                """
            )
        )


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "agendamentos" not in inspector.get_table_names():
        return

    columns = _column_map(connection, "agendamentos")
    _add_missing_columns(connection, dialect, columns)

    columns = _column_map(connection, "agendamentos")
    if dialect == "postgresql":
        _backfill_postgres(connection, columns)
    else:
        _backfill_sqlite(connection, columns)
