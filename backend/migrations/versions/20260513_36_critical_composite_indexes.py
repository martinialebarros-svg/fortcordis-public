"""Adds composite indexes for critical agenda/atendimento/relatorios queries."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260513_36"
DESCRIPTION = "Adiciona indices compostos para consultas criticas de agenda, atendimento e relatorios"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _create_index(
    connection: Connection,
    *,
    table_name: str,
    index_name: str,
    columns: tuple[str, ...],
) -> None:
    if not _table_exists(connection, table_name):
        return

    existing_columns = _column_names(connection, table_name)
    if any(column not in existing_columns for column in columns):
        return

    columns_sql = ", ".join(columns)
    connection.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} ({columns_sql})"
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _ = dialect

    # Agenda
    _create_index(
        connection,
        table_name="agendamentos",
        index_name="ix_agendamentos_data_inicio_id",
        columns=("data", "inicio", "id"),
    )
    _create_index(
        connection,
        table_name="agendamentos",
        index_name="ix_agendamentos_data_status_inicio_id",
        columns=("data", "status", "inicio", "id"),
    )
    _create_index(
        connection,
        table_name="agendamentos",
        index_name="ix_agendamentos_data_clinica_inicio_id",
        columns=("data", "clinica_id", "inicio", "id"),
    )
    _create_index(
        connection,
        table_name="agendamentos",
        index_name="ix_agendamentos_data_servico_inicio_id",
        columns=("data", "servico_id", "inicio", "id"),
    )
    _create_index(
        connection,
        table_name="agendamentos",
        index_name="ix_agendamentos_data_criado_por_inicio_id",
        columns=("data", "criado_por_id", "inicio", "id"),
    )

    # Atendimento
    _create_index(
        connection,
        table_name="atendimentos_clinicos",
        index_name="ix_atendimentos_clinicos_data_atendimento_id",
        columns=("data_atendimento", "id"),
    )
    _create_index(
        connection,
        table_name="atendimentos_clinicos",
        index_name="ix_atendimentos_clinicos_clinica_data_id",
        columns=("clinica_id", "data_atendimento", "id"),
    )
    _create_index(
        connection,
        table_name="atendimentos_clinicos",
        index_name="ix_atendimentos_clinicos_status_data_id",
        columns=("status", "data_atendimento", "id"),
    )
    _create_index(
        connection,
        table_name="atendimentos_clinicos",
        index_name="ix_atendimentos_clinicos_agendamento_data_id",
        columns=("agendamento_id", "data_atendimento", "id"),
    )

    # Ordem de servico / relatorios
    _create_index(
        connection,
        table_name="ordens_servico",
        index_name="ix_ordens_servico_status_data_atendimento_id",
        columns=("status", "data_atendimento", "id"),
    )
    _create_index(
        connection,
        table_name="ordens_servico",
        index_name="ix_ordens_servico_clinica_status_data_id",
        columns=("clinica_id", "status", "data_atendimento", "id"),
    )
    _create_index(
        connection,
        table_name="ordens_servico",
        index_name="ix_ordens_servico_servico_status_data_id",
        columns=("servico_id", "status", "data_atendimento", "id"),
    )
    _create_index(
        connection,
        table_name="ordens_servico",
        index_name="ix_ordens_servico_criado_por_status_data_id",
        columns=("criado_por_id", "status", "data_atendimento", "id"),
    )
    _create_index(
        connection,
        table_name="ordens_servico",
        index_name="ix_ordens_servico_agendamento_status_id",
        columns=("agendamento_id", "status", "id"),
    )
