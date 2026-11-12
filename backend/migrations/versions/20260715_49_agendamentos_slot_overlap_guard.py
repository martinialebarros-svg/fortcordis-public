"""Enforce non-overlapping active agenda slots in PostgreSQL."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260715_49"
DESCRIPTION = "Bloqueia sobreposicao de slots ativos e alinha inicio/fim para timestamptz"

CONSTRAINT_NAME = "ex_agendamentos_slot_ativo"
BLOCKING_STATUSES = ("Agendado", "Reservado", "Confirmado", "Em atendimento")


def _column_map(connection: Connection) -> dict:
    return {column["name"]: column for column in inspect(connection).get_columns("agendamentos")}


def _is_text_type(column: dict) -> bool:
    return "TEXT" in str(column.get("type") or "").upper()


def _normalize_postgres_datetime_columns(connection: Connection) -> None:
    columns = _column_map(connection)
    inicio = columns.get("inicio")
    fim = columns.get("fim")
    if inicio is None or fim is None:
        raise RuntimeError("agendamentos precisa das colunas inicio e fim para proteger sobreposicao.")

    if _is_text_type(inicio):
        inicio_vazio = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM agendamentos "
                    "WHERE inicio IS NULL OR BTRIM(inicio) = ''"
                )
            ).scalar_one()
            or 0
        )
        if inicio_vazio:
            raise RuntimeError(
                f"Nao foi possivel converter agendamentos.inicio: {inicio_vazio} valor(es) vazio(s)."
            )
        connection.execute(
            text(
                "ALTER TABLE agendamentos "
                "ALTER COLUMN inicio TYPE TIMESTAMP WITH TIME ZONE "
                "USING BTRIM(inicio)::timestamptz"
            )
        )

    if _is_text_type(fim):
        connection.execute(
            text(
                "ALTER TABLE agendamentos "
                "ALTER COLUMN fim TYPE TIMESTAMP WITH TIME ZONE "
                "USING NULLIF(BTRIM(fim), '')::timestamptz"
            )
        )

    connection.execute(
        text(
            "UPDATE agendamentos "
            "SET fim = inicio + INTERVAL '30 minutes' "
            "WHERE fim IS NULL OR fim <= inicio"
        )
    )
    connection.execute(text("ALTER TABLE agendamentos ALTER COLUMN fim SET NOT NULL"))


def _active_overlap_count(connection: Connection) -> int:
    statuses = ", ".join(f"'{status}'" for status in BLOCKING_STATUSES)
    return int(
        connection.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM agendamentos a
                JOIN agendamentos b ON a.id < b.id
                 AND a.status IN ({statuses})
                 AND b.status IN ({statuses})
                 AND a.inicio < b.fim
                 AND a.fim > b.inicio
                """
            )
        ).scalar_one()
        or 0
    )


def _constraint_exists(connection: Connection) -> bool:
    return bool(
        connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint constraint_data
                    JOIN pg_class relation ON relation.oid = constraint_data.conrelid
                    JOIN pg_namespace namespace_data ON namespace_data.oid = relation.relnamespace
                    WHERE constraint_data.conname = :constraint_name
                      AND relation.relname = 'agendamentos'
                      AND namespace_data.nspname = current_schema()
                )
                """
            ),
            {"constraint_name": CONSTRAINT_NAME},
        ).scalar_one()
    )


def _create_exclusion_constraint(connection: Connection) -> None:
    statuses = ", ".join(f"'{status}'" for status in BLOCKING_STATUSES)
    connection.execute(
        text(
            f"""
            ALTER TABLE agendamentos
            ADD CONSTRAINT {CONSTRAINT_NAME}
            EXCLUDE USING gist (
                tstzrange(
                    inicio,
                    fim,
                    '[)'
                ) WITH &&
            )
            WHERE (status IN ({statuses}))
            """
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    if dialect != "postgresql":
        return
    if "agendamentos" not in inspect(connection).get_table_names():
        return

    _normalize_postgres_datetime_columns(connection)

    overlap_count = _active_overlap_count(connection)
    if overlap_count:
        raise RuntimeError(
            "Nao foi possivel proteger slots ativos: "
            f"existem {overlap_count} sobreposicao(oes) operacional(is) em agendamentos."
        )

    if not _constraint_exists(connection):
        _create_exclusion_constraint(connection)
