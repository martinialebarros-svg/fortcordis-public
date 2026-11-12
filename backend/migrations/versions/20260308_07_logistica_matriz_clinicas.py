"""Add clinic geolocation fields and clinic travel matrix table."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260308_07"
DESCRIPTION = "Adiciona geolocalizacao de clinicas e matriz de deslocamentos"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _ensure_clinicas_columns(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "clinicas"):
        return

    latitude_type = "DOUBLE PRECISION" if dialect == "postgresql" else "REAL"
    longitude_type = "DOUBLE PRECISION" if dialect == "postgresql" else "REAL"
    geocode_at_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    statements = {
        "latitude": f"ALTER TABLE clinicas ADD COLUMN latitude {latitude_type}",
        "longitude": f"ALTER TABLE clinicas ADD COLUMN longitude {longitude_type}",
        "endereco_normalizado": "ALTER TABLE clinicas ADD COLUMN endereco_normalizado TEXT",
        "geocode_at": f"ALTER TABLE clinicas ADD COLUMN geocode_at {geocode_at_type}",
    }

    columns = _column_names(connection, "clinicas")
    for column_name, sql in statements.items():
        if column_name not in columns:
            connection.execute(text(sql))


def _create_deslocamento_table(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "clinica_deslocamentos"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE clinica_deslocamentos (
                    id SERIAL PRIMARY KEY,
                    origem_clinica_id INTEGER NOT NULL,
                    destino_clinica_id INTEGER NOT NULL,
                    perfil VARCHAR(20) NOT NULL DEFAULT 'comercial',
                    distancia_km NUMERIC(10,2) NOT NULL DEFAULT 0,
                    duracao_min INTEGER NOT NULL DEFAULT 0,
                    fonte VARCHAR(50) NOT NULL DEFAULT 'heuristica',
                    manual_override BOOLEAN NOT NULL DEFAULT false,
                    observacoes TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NULL
                )
                """
            )
        )
        return

    connection.execute(
        text(
            """
            CREATE TABLE clinica_deslocamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origem_clinica_id INTEGER NOT NULL,
                destino_clinica_id INTEGER NOT NULL,
                perfil TEXT NOT NULL DEFAULT 'comercial',
                distancia_km NUMERIC(10,2) NOT NULL DEFAULT 0,
                duracao_min INTEGER NOT NULL DEFAULT 0,
                fonte TEXT NOT NULL DEFAULT 'heuristica',
                manual_override INTEGER NOT NULL DEFAULT 0,
                observacoes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL
            )
            """
        )
    )


def _ensure_deslocamento_columns(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "clinica_deslocamentos"):
        return

    manual_override_type = "BOOLEAN NOT NULL DEFAULT false" if dialect == "postgresql" else "INTEGER NOT NULL DEFAULT 0"
    created_at_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
    updated_at_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    statements = {
        "origem_clinica_id": "ALTER TABLE clinica_deslocamentos ADD COLUMN origem_clinica_id INTEGER",
        "destino_clinica_id": "ALTER TABLE clinica_deslocamentos ADD COLUMN destino_clinica_id INTEGER",
        "perfil": "ALTER TABLE clinica_deslocamentos ADD COLUMN perfil VARCHAR(20) DEFAULT 'comercial'",
        "distancia_km": "ALTER TABLE clinica_deslocamentos ADD COLUMN distancia_km NUMERIC(10,2) DEFAULT 0",
        "duracao_min": "ALTER TABLE clinica_deslocamentos ADD COLUMN duracao_min INTEGER DEFAULT 0",
        "fonte": "ALTER TABLE clinica_deslocamentos ADD COLUMN fonte VARCHAR(50) DEFAULT 'heuristica'",
        "manual_override": f"ALTER TABLE clinica_deslocamentos ADD COLUMN manual_override {manual_override_type}",
        "observacoes": "ALTER TABLE clinica_deslocamentos ADD COLUMN observacoes TEXT",
        "created_at": f"ALTER TABLE clinica_deslocamentos ADD COLUMN created_at {created_at_type}",
        "updated_at": f"ALTER TABLE clinica_deslocamentos ADD COLUMN updated_at {updated_at_type}",
    }

    columns = _column_names(connection, "clinica_deslocamentos")
    for column_name, sql in statements.items():
        if column_name not in columns:
            connection.execute(text(sql))


def _ensure_deslocamento_indexes(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_clinica_deslocamentos_par "
            "ON clinica_deslocamentos (origem_clinica_id, destino_clinica_id, perfil)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_clinica_deslocamentos_origem "
            "ON clinica_deslocamentos (origem_clinica_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_clinica_deslocamentos_destino "
            "ON clinica_deslocamentos (destino_clinica_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_clinica_deslocamentos_perfil "
            "ON clinica_deslocamentos (perfil)"
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _ensure_clinicas_columns(connection, dialect)
    _create_deslocamento_table(connection, dialect)
    _ensure_deslocamento_columns(connection, dialect)
    _ensure_deslocamento_indexes(connection)
