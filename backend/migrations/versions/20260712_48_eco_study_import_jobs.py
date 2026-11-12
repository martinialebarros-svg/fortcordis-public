"""Create asynchronous echocardiography study import jobs."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260712_48"
DESCRIPTION = "Cria jobs idempotentes para importacao de estudo ecocardiografico por imagem/PDF"


def upgrade(connection: Connection, dialect: str) -> None:
    if "eco_study_import_jobs" not in inspect(connection).get_table_names():
        id_column = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        connection.execute(
            text(
                f"""
                CREATE TABLE eco_study_import_jobs (
                    id {id_column},
                    requested_by_id INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    arquivo_nome VARCHAR(255),
                    arquivo_tipo VARCHAR(100),
                    arquivo_caminho VARCHAR(500),
                    conteudo_hash VARCHAR(64),
                    resultado_json TEXT,
                    erro TEXT,
                    tentativas INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    expires_at TIMESTAMP
                )
                """
            )
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_eco_study_import_jobs_requested_by_id "
            "ON eco_study_import_jobs (requested_by_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_eco_study_import_jobs_status "
            "ON eco_study_import_jobs (status)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_eco_study_import_jobs_conteudo_hash "
            "ON eco_study_import_jobs (conteudo_hash)"
        )
    )
    trim = "BTRIM(conteudo_hash)" if dialect == "postgresql" else "TRIM(conteudo_hash)"
    connection.execute(
        text(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_eco_study_import_jobs_active_dedupe
            ON eco_study_import_jobs (requested_by_id, conteudo_hash)
            WHERE status IN ('pending', 'processing')
              AND conteudo_hash IS NOT NULL
              AND {trim} <> ''
            """
        )
    )
