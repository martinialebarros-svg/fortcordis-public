"""Initial normalization for legacy people timestamp fields."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260514_37"
DESCRIPTION = "Normaliza created_at/updated_at de pacientes e tutores para datetime"

TARGET_TABLES = ("pacientes", "tutores")
TARGET_COLUMNS = ("created_at", "updated_at")


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _is_datetime_like(column_meta: dict) -> bool:
    data_type = str(column_meta.get("type") or "").lower()
    return "timestamp" in data_type or "datetime" in data_type


def _ensure_column(connection: Connection, table_name: str, column_name: str, dialect: str) -> None:
    columns = _column_map(connection, table_name)
    if column_name in columns:
        return
    column_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def _normalize_sqlite_values(connection: Connection, table_name: str, column_name: str) -> None:
    connection.execute(
        text(
            f"""
            UPDATE {table_name}
            SET {column_name} = REPLACE(SUBSTR(TRIM(CAST({column_name} AS TEXT)), 1, 19), 'T', ' ')
            WHERE {column_name} IS NOT NULL
              AND TRIM(CAST({column_name} AS TEXT)) != ''
            """
        )
    )
    connection.execute(
        text(
            f"""
            UPDATE {table_name}
            SET {column_name} = NULL
            WHERE {column_name} IS NOT NULL
              AND TRIM(CAST({column_name} AS TEXT)) = ''
            """
        )
    )


def _upgrade_sqlite(connection: Connection, table_name: str) -> None:
    for column_name in TARGET_COLUMNS:
        _normalize_sqlite_values(connection, table_name, column_name)

    connection.execute(
        text(
            f"""
            UPDATE {table_name}
            SET created_at = strftime('%Y-%m-%d %H:%M:%S', 'now')
            WHERE created_at IS NULL
            """
        )
    )


def _upgrade_postgres(connection: Connection, table_name: str, columns: dict) -> None:
    for column_name in TARGET_COLUMNS:
        column_meta = columns.get(column_name)
        if not column_meta or _is_datetime_like(column_meta):
            continue
        # Bases legadas podem ter defaults textuais (ex.: NOW()::text) que impedem cast direto.
        connection.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP DEFAULT"))
        connection.execute(
            text(
                f"""
                ALTER TABLE {table_name}
                ALTER COLUMN {column_name} TYPE TIMESTAMP
                USING (
                    CASE
                        WHEN {column_name} IS NULL THEN NULL
                        WHEN BTRIM({column_name}::text) = '' THEN NULL
                        WHEN {column_name}::text ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' THEN
                            REPLACE(SUBSTRING({column_name}::text FROM 1 FOR 19), 'T', ' ')::timestamp
                        ELSE NULL
                    END
                )
                """
            )
        )

    connection.execute(text(f"UPDATE {table_name} SET created_at = NOW() WHERE created_at IS NULL"))
    connection.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN created_at SET DEFAULT NOW()"))


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    for table_name in TARGET_TABLES:
        if table_name not in existing_tables:
            continue

        for column_name in TARGET_COLUMNS:
            _ensure_column(connection, table_name, column_name, dialect)

        columns = _column_map(connection, table_name)
        if dialect == "postgresql":
            _upgrade_postgres(connection, table_name, columns)
        else:
            _upgrade_sqlite(connection, table_name)
