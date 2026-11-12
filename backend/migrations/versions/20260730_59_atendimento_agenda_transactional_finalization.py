"""Guard transactional finalization against duplicate attendance and active OS."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from migrations.exceptions import MigrationDeferred

VERSION = "20260730_59"
DESCRIPTION = "Garante um atendimento e uma OS ativa por agendamento"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _duplicate_rows(
    connection: Connection,
    *,
    table_name: str,
    active_where: str,
) -> list[tuple[object, object, object]]:
    dialect = connection.dialect.name
    ids_expression = (
        "STRING_AGG(CAST(id AS TEXT), ',' ORDER BY id)"
        if dialect == "postgresql"
        else "GROUP_CONCAT(id, ',')"
    )
    return list(
        connection.execute(
            text(
                f"""
                SELECT agendamento_id, COUNT(*) AS total, {ids_expression} AS ids
                FROM {table_name}
                WHERE agendamento_id IS NOT NULL
                  AND ({active_where})
                GROUP BY agendamento_id
                HAVING COUNT(*) > 1
                ORDER BY agendamento_id
                LIMIT 20
                """
            )
        ).fetchall()
    )


def _pendencia_conciliacao(
    connection: Connection,
    *,
    table_name: str,
    label: str,
    active_where: str = "1 = 1",
) -> str | None:
    """Devolve o diagnostico da duplicidade, ou None se a base esta integra."""
    duplicates = _duplicate_rows(
        connection,
        table_name=table_name,
        active_where=active_where,
    )
    if not duplicates:
        return None

    sample = "; ".join(
        f"agendamento {agendamento_id}: ids {ids}"
        for agendamento_id, _total, ids in duplicates
    )
    return (
        f"Nao foi possivel criar a restricao de {label}: existem duplicidades. "
        f"Concilie os registros antes de repetir a migracao. {sample}"
    )


def upgrade(connection: Connection, dialect: str | None = None) -> None:
    _ = dialect

    tem_atendimentos = _table_exists(connection, "atendimentos_clinicos")
    tem_ordens = _table_exists(connection, "ordens_servico")
    active_where_os = "COALESCE(status, '') <> 'Cancelado'"

    # Colhe TODAS as pendencias antes de decidir. Evita o ciclo de conciliar uma
    # duplicidade, rodar o deploy de novo e so entao descobrir a outra.
    pendencias: list[str] = []
    if tem_atendimentos:
        pendencia = _pendencia_conciliacao(
            connection,
            table_name="atendimentos_clinicos",
            label="um atendimento por agendamento",
        )
        if pendencia:
            pendencias.append(pendencia)
    if tem_ordens:
        pendencia = _pendencia_conciliacao(
            connection,
            table_name="ordens_servico",
            label="uma OS ativa por agendamento",
            active_where=active_where_os,
        )
        if pendencia:
            pendencias.append(pendencia)

    if pendencias:
        # Pendencia de dados, nao erro: o runner adia esta versao, segue com as
        # demais migracoes e tenta de novo no proximo deploy. Nenhum registro e
        # apagado ou alterado aqui.
        raise MigrationDeferred(" | ".join(pendencias))

    if tem_atendimentos:
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_atendimentos_clinicos_agendamento_unico
                ON atendimentos_clinicos (agendamento_id)
                WHERE agendamento_id IS NOT NULL
                """
            )
        )

    if tem_ordens:
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_ordens_servico_agendamento_ativa
                ON ordens_servico (agendamento_id)
                WHERE COALESCE(status, '') <> 'Cancelado'
                """
            )
        )
