"""Add strong fiscal number sequence table with backfill."""
from __future__ import annotations

import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260512_35"
DESCRIPTION = "Adiciona sequencia forte para numero fiscal com backfill"

_NUMERO_PATTERN = re.compile(r"^NFO-(\d{4})-(\d+)$")


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _create_sequence_table(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "fiscal_numero_sequencias"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE fiscal_numero_sequencias (
                    ano INTEGER PRIMARY KEY,
                    ultimo_numero INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT
                )
                """
            )
        )
        return

    connection.execute(
        text(
            """
            CREATE TABLE fiscal_numero_sequencias (
                ano INTEGER PRIMARY KEY,
                ultimo_numero INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
            """
        )
    )


def _parse_existing_max_by_year(connection: Connection) -> dict[int, int]:
    rows = connection.execute(
        text(
            """
            SELECT numero
            FROM notas_fiscais
            WHERE numero IS NOT NULL AND TRIM(numero) <> ''
            """
        )
    ).fetchall()

    max_by_year: dict[int, int] = {}
    for row in rows:
        numero = str(row[0] or "").strip()
        match = _NUMERO_PATTERN.match(numero)
        if not match:
            continue
        ano = int(match.group(1))
        sequencial = int(match.group(2))
        current = max_by_year.get(ano, 0)
        if sequencial > current:
            max_by_year[ano] = sequencial

    return max_by_year


def _upsert_sequence_row(connection: Connection, ano: int, ultimo_numero: int) -> None:
    connection.execute(
        text(
            """
            INSERT INTO fiscal_numero_sequencias (ano, ultimo_numero, updated_at)
            VALUES (:ano, :ultimo_numero, CURRENT_TIMESTAMP)
            ON CONFLICT (ano) DO UPDATE
            SET
                ultimo_numero = CASE
                    WHEN fiscal_numero_sequencias.ultimo_numero >= :ultimo_numero
                    THEN fiscal_numero_sequencias.ultimo_numero
                    ELSE :ultimo_numero
                END,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"ano": ano, "ultimo_numero": ultimo_numero},
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _create_sequence_table(connection, dialect)

    if not _table_exists(connection, "notas_fiscais"):
        return

    max_by_year = _parse_existing_max_by_year(connection)
    for ano, ultimo_numero in sorted(max_by_year.items()):
        _upsert_sequence_row(connection, ano, ultimo_numero)
