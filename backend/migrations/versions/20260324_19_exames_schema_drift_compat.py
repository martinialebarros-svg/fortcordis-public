"""Hardens exames table against legacy schema drift."""
from __future__ import annotations

import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260324_19"
DESCRIPTION = "Compatibiliza drift legado de schema em exames para fluxo de atendimento"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _safe_identifier(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""))


def _add_missing_known_columns(connection: Connection, dialect: str, columns: dict) -> None:
    known_columns = {
        "laudo_id": ("INTEGER", "INTEGER"),
        "atendimento_id": ("INTEGER", "INTEGER"),
        "tipo_exame": ("VARCHAR(255)", "TEXT"),
        "catalogo_exame_id": ("INTEGER", "INTEGER"),
        "painel_exame_id": ("INTEGER", "INTEGER"),
        "painel_exame_nome": ("VARCHAR(255)", "TEXT"),
        "categoria_exame": ("VARCHAR(120)", "TEXT"),
        "preparo": ("TEXT", "TEXT"),
        "prioridade": ("VARCHAR(50)", "TEXT"),
        "resultado": ("TEXT", "TEXT"),
        "valor_referencia": ("TEXT", "TEXT"),
        "unidade": ("VARCHAR(255)", "TEXT"),
        "status": ("VARCHAR(255)", "TEXT"),
        "data_solicitacao": ("TIMESTAMP", "DATETIME"),
        "data_resultado": ("TIMESTAMP", "DATETIME"),
        "valor": ("DOUBLE PRECISION", "REAL"),
        "observacoes": ("TEXT", "TEXT"),
        "created_at": ("TIMESTAMP", "DATETIME"),
        "criado_por_id": ("INTEGER", "INTEGER"),
        "criado_por_nome": ("VARCHAR(255)", "TEXT"),
    }

    for column_name, (pg_type, sqlite_type) in known_columns.items():
        if column_name in columns:
            continue
        column_type = pg_type if dialect == "postgresql" else sqlite_type
        connection.execute(text(f"ALTER TABLE exames ADD COLUMN {column_name} {column_type}"))


def _backfill_defaults(connection: Connection, dialect: str) -> None:
    if dialect == "postgresql":
        connection.execute(text("UPDATE exames SET tipo_exame = 'Exame' WHERE tipo_exame IS NULL OR tipo_exame = ''"))
        connection.execute(text("UPDATE exames SET status = 'Solicitado' WHERE status IS NULL OR status = ''"))
        connection.execute(text("UPDATE exames SET prioridade = 'Rotina' WHERE prioridade IS NULL OR prioridade = ''"))
        connection.execute(text("UPDATE exames SET valor = 0 WHERE valor IS NULL"))
        connection.execute(text("UPDATE exames SET data_solicitacao = NOW() WHERE data_solicitacao IS NULL"))
        connection.execute(text("UPDATE exames SET created_at = NOW() WHERE created_at IS NULL"))
        return

    connection.execute(text("UPDATE exames SET tipo_exame = 'Exame' WHERE tipo_exame IS NULL OR tipo_exame = ''"))
    connection.execute(text("UPDATE exames SET status = 'Solicitado' WHERE status IS NULL OR status = ''"))
    connection.execute(text("UPDATE exames SET prioridade = 'Rotina' WHERE prioridade IS NULL OR prioridade = ''"))
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


def _drop_not_null_legacy_columns_postgres(connection: Connection, columns: dict) -> None:
    optional_known = {
        "laudo_id",
        "atendimento_id",
        "catalogo_exame_id",
        "painel_exame_id",
        "painel_exame_nome",
        "categoria_exame",
        "preparo",
        "prioridade",
        "resultado",
        "valor_referencia",
        "unidade",
        "status",
        "data_solicitacao",
        "data_resultado",
        "valor",
        "observacoes",
        "created_at",
        "criado_por_id",
        "criado_por_nome",
    }
    required_known = {"id", "paciente_id", "tipo_exame"}

    for column_name, meta in columns.items():
        if not _safe_identifier(column_name):
            continue
        if column_name in required_known:
            continue

        is_nullable = bool(meta.get("nullable", True))
        if is_nullable:
            continue

        if column_name in optional_known or column_name not in required_known:
            connection.execute(text(f'ALTER TABLE exames ALTER COLUMN "{column_name}" DROP NOT NULL'))


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "exames" not in inspector.get_table_names():
        return

    columns = _column_map(connection, "exames")
    _add_missing_known_columns(connection, dialect, columns)
    _backfill_defaults(connection, dialect)

    if dialect == "postgresql":
        columns = _column_map(connection, "exames")
        _drop_not_null_legacy_columns_postgres(connection, columns)
