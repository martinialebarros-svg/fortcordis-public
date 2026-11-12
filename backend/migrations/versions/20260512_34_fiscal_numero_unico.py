"""Enforce unique fiscal number in notas_fiscais."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "20260512_34"
DESCRIPTION = "Adiciona indice unico para numero de nota fiscal"


def _ensure_no_duplicate_numero(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT numero, COUNT(*) AS total
            FROM notas_fiscais
            WHERE numero IS NOT NULL AND TRIM(numero) <> ''
            GROUP BY numero
            HAVING COUNT(*) > 1
            ORDER BY total DESC, numero ASC
            LIMIT 10
            """
        )
    ).fetchall()
    if not rows:
        return

    exemplos = ", ".join(f"{row[0]} (x{row[1]})" for row in rows)
    raise RuntimeError(
        "Nao foi possivel aplicar unicidade de numero fiscal: "
        f"duplicidades encontradas em notas_fiscais.numero: {exemplos}"
    )


def upgrade(connection: Connection, dialect: str) -> None:
    # Guardrail: nao cria indice unico se houver duplicidade existente.
    _ensure_no_duplicate_numero(connection)

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_notas_fiscais_numero
                ON notas_fiscais (numero)
                WHERE numero IS NOT NULL AND BTRIM(numero) <> ''
                """
            )
        )
        return

    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_notas_fiscais_numero
            ON notas_fiscais (numero)
            WHERE numero IS NOT NULL AND TRIM(numero) <> ''
            """
        )
    )
