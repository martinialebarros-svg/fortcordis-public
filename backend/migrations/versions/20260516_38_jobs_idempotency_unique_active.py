"""Enforce active-job idempotency for async laudo/pdf and xml imports."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260516_38"
DESCRIPTION = "Garante idempotencia em jobs ativos de PDF/XML com indices unicos parciais"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _ensure_xml_hash_column(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "xml_import_jobs"):
        return
    columns = _column_names(connection, "xml_import_jobs")
    if "conteudo_hash" in columns:
        return
    if dialect == "postgresql":
        connection.execute(text("ALTER TABLE xml_import_jobs ADD COLUMN conteudo_hash VARCHAR(64)"))
    else:
        connection.execute(text("ALTER TABLE xml_import_jobs ADD COLUMN conteudo_hash TEXT"))


def _mark_duplicate_active_laudo_jobs(connection: Connection) -> None:
    connection.execute(
        text(
            """
            UPDATE laudo_pdf_jobs
            SET status = 'failed',
                erro = COALESCE(NULLIF(TRIM(COALESCE(erro, '')), ''), 'Job duplicado cancelado por normalizacao de idempotencia.'),
                finished_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY laudo_id, requested_by_id, cache_key
                               ORDER BY id DESC
                           ) AS rn
                    FROM laudo_pdf_jobs
                    WHERE status IN ('pending', 'processing')
                      AND laudo_id IS NOT NULL
                      AND requested_by_id IS NOT NULL
                      AND cache_key IS NOT NULL
                      AND TRIM(CAST(cache_key AS TEXT)) <> ''
                ) ranked
                WHERE rn > 1
            )
            """
        )
    )


def _mark_duplicate_active_xml_jobs(connection: Connection) -> None:
    connection.execute(
        text(
            """
            UPDATE xml_import_jobs
            SET status = 'failed',
                erro = COALESCE(NULLIF(TRIM(COALESCE(erro, '')), ''), 'Job duplicado cancelado por normalizacao de idempotencia.'),
                finished_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY requested_by_id, conteudo_hash
                               ORDER BY id DESC
                           ) AS rn
                    FROM xml_import_jobs
                    WHERE status IN ('pending', 'processing')
                      AND requested_by_id IS NOT NULL
                      AND conteudo_hash IS NOT NULL
                      AND TRIM(CAST(conteudo_hash AS TEXT)) <> ''
                ) ranked
                WHERE rn > 1
            )
            """
        )
    )


def _create_partial_unique_indexes(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "laudo_pdf_jobs"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_laudo_pdf_jobs_active_dedupe
                    ON laudo_pdf_jobs (laudo_id, requested_by_id, cache_key)
                    WHERE status IN ('pending', 'processing')
                      AND cache_key IS NOT NULL
                      AND BTRIM(cache_key) <> ''
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_laudo_pdf_jobs_active_dedupe
                    ON laudo_pdf_jobs (laudo_id, requested_by_id, cache_key)
                    WHERE status IN ('pending', 'processing')
                      AND cache_key IS NOT NULL
                      AND TRIM(cache_key) <> ''
                    """
                )
            )

    if _table_exists(connection, "xml_import_jobs"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_xml_import_jobs_active_dedupe
                    ON xml_import_jobs (requested_by_id, conteudo_hash)
                    WHERE status IN ('pending', 'processing')
                      AND conteudo_hash IS NOT NULL
                      AND BTRIM(conteudo_hash) <> ''
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_xml_import_jobs_active_dedupe
                    ON xml_import_jobs (requested_by_id, conteudo_hash)
                    WHERE status IN ('pending', 'processing')
                      AND conteudo_hash IS NOT NULL
                      AND TRIM(conteudo_hash) <> ''
                    """
                )
            )


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "laudo_pdf_jobs") and not _table_exists(connection, "xml_import_jobs"):
        return

    _ensure_xml_hash_column(connection, dialect)
    if _table_exists(connection, "laudo_pdf_jobs"):
        _mark_duplicate_active_laudo_jobs(connection)
    if _table_exists(connection, "xml_import_jobs"):
        _mark_duplicate_active_xml_jobs(connection)
    _create_partial_unique_indexes(connection, dialect)
