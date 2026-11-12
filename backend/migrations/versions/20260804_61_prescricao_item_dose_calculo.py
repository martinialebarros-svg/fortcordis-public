"""Persist the mg/kg dose calculation fields per prescription item."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260804_61"
DESCRIPTION = "Adiciona campos de calculo mg/kg (dose_mg_kg, peso_referencia_kg, unidade_dose_calculo, concentracao_personalizada) aos itens da prescricao"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if "prescricoes_itens" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("prescricoes_itens")}
    text_type = "VARCHAR(255)" if dialect == "postgresql" else "TEXT"

    if "dose_mg_kg" not in columns:
        connection.execute(text(f"ALTER TABLE prescricoes_itens ADD COLUMN dose_mg_kg {text_type}"))
    if "peso_referencia_kg" not in columns:
        connection.execute(
            text(f"ALTER TABLE prescricoes_itens ADD COLUMN peso_referencia_kg {text_type}")
        )
    if "unidade_dose_calculo" not in columns:
        connection.execute(
            text(f"ALTER TABLE prescricoes_itens ADD COLUMN unidade_dose_calculo {text_type}")
        )
    if "concentracao_personalizada" not in columns:
        connection.execute(
            text(f"ALTER TABLE prescricoes_itens ADD COLUMN concentracao_personalizada {text_type}")
        )
