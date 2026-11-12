"""Persiste a excecao de deslocamento concedida por admin no agendamento.

Ate aqui a excecao de conflito de rota vivia apenas na requisicao que a
confirmou (`confirmar_conflito_deslocamento`) - mais um texto solto em
`observacoes` e um evento de auditoria, nenhum dos dois reconsultado depois.
Resultado: reabilitar a reserva ou reativar o agendamento batia na mesma
validacao de deslocamento e era bloqueado de novo. As colunas abaixo guardam a
concessao (quem, quando, motivo) e a assinatura da rota aprovada, usada para
invalidar a excecao se horario, destino ou servico mudarem.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260823_75"
DESCRIPTION = (
    "Adiciona agendamentos.excecao_deslocamento_* para persistir a excecao de "
    "conflito de rota concedida por admin"
)


def _add_column_if_missing(
    connection: Connection,
    dialect: str,
    table_name: str,
    column_name: str,
    postgres_type: str,
    sqlite_type: str,
) -> None:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return

    column_type = postgres_type if dialect == "postgresql" else sqlite_type
    connection.execute(
        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
    )


def upgrade(connection: Connection, dialect: str) -> None:
    colunas = (
        ("excecao_deslocamento_concedida_em", "TIMESTAMP", "TIMESTAMP"),
        ("excecao_deslocamento_concedida_por_id", "INTEGER", "INTEGER"),
        ("excecao_deslocamento_concedida_por_nome", "VARCHAR(255)", "TEXT"),
        ("excecao_deslocamento_motivo", "TEXT", "TEXT"),
        ("excecao_deslocamento_escopo", "VARCHAR(64)", "TEXT"),
    )
    for column_name, postgres_type, sqlite_type in colunas:
        _add_column_if_missing(
            connection,
            dialect,
            "agendamentos",
            column_name,
            postgres_type=postgres_type,
            sqlite_type=sqlite_type,
        )
