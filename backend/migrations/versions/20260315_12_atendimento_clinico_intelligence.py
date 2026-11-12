"""Adds pharmacology metadata and prescription adjustment history."""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260315_12"
DESCRIPTION = "Amplia medicamentos com dose/interacoes e cria historico de ajustes da prescricao"


STARTER_CARDIO_MEDICATIONS = [
    ("Pimobendan", "Pimobendan", "Inodilatador"),
    ("Furosemida", "Furosemida", "Diuretico de alca"),
    ("Espironolactona", "Espironolactona", "Antagonista da aldosterona"),
    ("Enalapril", "Maleato de enalapril", "Inibidor da ECA"),
    ("Benazepril", "Cloridrato de benazepril", "Inibidor da ECA"),
    ("Amlodipina", "Besilato de amlodipina", "Bloqueador de canal de calcio"),
    ("Atenolol", "Atenolol", "Betabloqueador"),
    ("Diltiazem", "Cloridrato de diltiazem", "Bloqueador de canal de calcio"),
    ("Clopidogrel", "Clopidogrel", "Antiplaquetario"),
    ("Sildenafil", "Sildenafil", "Vasodilatador pulmonar"),
    ("Digoxina", "Digoxina", "Inotropico"),
]


def _gerar_nome_key(value: str) -> str:
    texto = unicodedata.normalize("NFKD", value or "")
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _add_medicamento_columns(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "medicamentos"):
        return

    columns = _column_names(connection, "medicamentos")
    missing = {
        "principio_ativo": ("VARCHAR(255)", "TEXT"),
        "concentracao": ("VARCHAR(120)", "TEXT"),
        "forma_farmaceutica": ("VARCHAR(120)", "TEXT"),
        "classe_terapeutica": ("VARCHAR(255)", "TEXT"),
        "especie_alvo": ("VARCHAR(255)", "TEXT"),
        "dose_min_mg_kg": ("DOUBLE PRECISION", "REAL"),
        "dose_max_mg_kg": ("DOUBLE PRECISION", "REAL"),
        "dose_intervalo_horas": ("INTEGER", "INTEGER"),
        "dose_unidade": ("VARCHAR(50)", "TEXT"),
        "via_padrao": ("VARCHAR(50)", "TEXT"),
        "duracao_padrao": ("VARCHAR(120)", "TEXT"),
        "concentracao_mg_ml": ("DOUBLE PRECISION", "REAL"),
        "concentracao_mg_comprimido": ("DOUBLE PRECISION", "REAL"),
        "indicacoes": ("TEXT", "TEXT"),
        "contraindicacoes": ("TEXT", "TEXT"),
        "interacoes_json": ("TEXT", "TEXT"),
        "observacao_seguranca": ("TEXT", "TEXT"),
        "parametrizacao_origem": ("VARCHAR(50)", "TEXT"),
    }

    for column_name, (pg_type, sqlite_type) in missing.items():
        if column_name in columns:
            continue
        column_type = pg_type if dialect == "postgresql" else sqlite_type
        connection.execute(text(f"ALTER TABLE medicamentos ADD COLUMN {column_name} {column_type}"))

    connection.execute(
        text(
            """
            UPDATE medicamentos
            SET especie_alvo = COALESCE(NULLIF(especie_alvo, ''), 'Canina,Felina'),
                dose_unidade = COALESCE(NULLIF(dose_unidade, ''), 'mg/kg'),
                parametrizacao_origem = COALESCE(NULLIF(parametrizacao_origem, ''), 'manual')
            """
        )
    )


def _create_prescricao_item_ajustes(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "prescricao_item_ajustes"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE prescricao_item_ajustes (
                    id SERIAL PRIMARY KEY,
                    prescricao_item_id INTEGER NOT NULL,
                    atendimento_id INTEGER NOT NULL,
                    campo VARCHAR(80) NOT NULL,
                    valor_anterior TEXT,
                    valor_novo TEXT,
                    motivo TEXT,
                    responsavel_id INTEGER,
                    responsavel_nome VARCHAR(255),
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE prescricao_item_ajustes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prescricao_item_id INTEGER NOT NULL,
                    atendimento_id INTEGER NOT NULL,
                    campo TEXT NOT NULL,
                    valor_anterior TEXT,
                    valor_novo TEXT,
                    motivo TEXT,
                    responsavel_id INTEGER,
                    responsavel_nome TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_prescricao_item_ajustes_item_id "
            "ON prescricao_item_ajustes (prescricao_item_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_prescricao_item_ajustes_atendimento_id "
            "ON prescricao_item_ajustes (atendimento_id)"
        )
    )


def _seed_starter_medications(connection: Connection) -> None:
    if not _table_exists(connection, "medicamentos"):
        return

    columns = _column_names(connection, "medicamentos")
    if "nome" not in columns:
        return

    for nome, principio_ativo, classe in STARTER_CARDIO_MEDICATIONS:
        exists = connection.execute(
            text("SELECT id FROM medicamentos WHERE lower(nome) = lower(:nome)"),
            {"nome": nome},
        ).fetchone()
        if exists:
            continue

        values_by_column = {
            "nome": nome,
            "nome_key": _gerar_nome_key(nome),
            "principio_ativo": principio_ativo,
            "concentracao": "",
            "forma_farmaceutica": "",
            "categoria": "Cardiologia",
            "classe_terapeutica": classe,
            "especie_alvo": "Canina,Felina",
            "dose_unidade": "mg/kg",
            "observacao_seguranca": "Revisar dose, interacoes e ajustes especificos antes do uso clinico.",
            "observacoes": "Medicamento inicial do catalogo cardiologico. Parametrize a posologia antes de automatizar receituarios.",
            "parametrizacao_origem": "starter",
            "ativo": 1,
        }

        ordered_columns = [
            "nome",
            "nome_key",
            "principio_ativo",
            "concentracao",
            "forma_farmaceutica",
            "categoria",
            "classe_terapeutica",
            "especie_alvo",
            "dose_unidade",
            "observacao_seguranca",
            "observacoes",
            "parametrizacao_origem",
            "ativo",
            "created_at",
            "updated_at",
        ]

        insert_columns: list[str] = []
        value_fragments: list[str] = []
        bind_params: dict[str, object] = {}

        for column_name in ordered_columns:
            if column_name not in columns:
                continue
            insert_columns.append(column_name)
            if column_name in {"created_at", "updated_at"}:
                value_fragments.append("CURRENT_TIMESTAMP")
            else:
                value_fragments.append(f":{column_name}")
                bind_params[column_name] = values_by_column.get(column_name)

        if not insert_columns:
            continue

        insert_sql = (
            f"INSERT INTO medicamentos ({', '.join(insert_columns)}) "
            f"VALUES ({', '.join(value_fragments)})"
        )
        connection.execute(text(insert_sql), bind_params)


def upgrade(connection: Connection, dialect: str) -> None:
    _add_medicamento_columns(connection, dialect)
    _create_prescricao_item_ajustes(connection, dialect)
    _seed_starter_medications(connection)
