"""Adds the measured lookup index for the pending reports queue."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260901_79"
DESCRIPTION = "Adiciona indice da fila paginada de laudos pendentes"

INDEX_NAME = "ix_laudos_agendamento_tipo_created_id"
REQUIRED_COLUMNS = {"agendamento_id", "tipo", "created_at", "id", "status"}


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "laudos" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("laudos")}
    if not REQUIRED_COLUMNS.issubset(columns):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                f"""
                CREATE INDEX IF NOT EXISTS {INDEX_NAME}
                ON laudos (
                    agendamento_id,
                    lower(btrim(tipo)),
                    created_at DESC NULLS LAST,
                    id DESC
                ) INCLUDE (status)
                """
            )
        )
        return

    # SQLite e usado nas suites locais/CI. Ele nao suporta INCLUDE, mas a
    # chave de busca e de ordenacao permanece a mesma da consulta em producao.
    connection.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS {INDEX_NAME}
            ON laudos (
                agendamento_id,
                lower(trim(tipo)),
                created_at DESC,
                id DESC
            )
            """
        )
    )
