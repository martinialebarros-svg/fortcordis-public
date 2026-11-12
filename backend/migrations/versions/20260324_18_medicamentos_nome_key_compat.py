"""Align legacy schema drift for medicamentos.nome_key."""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260324_18"
DESCRIPTION = "Compatibiliza medicamentos.nome_key em bancos legados"


def _column_map(connection: Connection, table_name: str) -> dict:
    inspector = inspect(connection)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _gerar_nome_key(nome: str) -> str:
    texto = unicodedata.normalize("NFKD", nome or "")
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "medicamentos" not in inspector.get_table_names():
        return

    columns = _column_map(connection, "medicamentos")

    if "nome_key" not in columns:
        column_type = "VARCHAR(255)" if dialect == "postgresql" else "TEXT"
        connection.execute(text(f"ALTER TABLE medicamentos ADD COLUMN nome_key {column_type}"))
        columns = _column_map(connection, "medicamentos")

    rows = connection.execute(
        text("SELECT id, nome, nome_key FROM medicamentos")
    ).mappings().all()
    for row in rows:
        nome_key_atual = str(row.get("nome_key") or "").strip()
        if nome_key_atual:
            continue
        nome = str(row.get("nome") or "").strip()
        nome_key = _gerar_nome_key(nome) or f"med-{row['id']}"
        connection.execute(
            text("UPDATE medicamentos SET nome_key = :nome_key WHERE id = :id"),
            {"id": row["id"], "nome_key": nome_key},
        )

    # Em alguns bancos legados a coluna veio como NOT NULL.
    # O fluxo atual da aplicacao nao depende de preenchimento obrigatorio.
    if dialect == "postgresql" and "nome_key" in columns:
        is_nullable = bool(columns["nome_key"].get("nullable", True))
        if not is_nullable:
            connection.execute(text("ALTER TABLE medicamentos ALTER COLUMN nome_key DROP NOT NULL"))
