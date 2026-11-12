"""Support domiciliary OS without clinic and preserve attendance origin."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260707_47"
DESCRIPTION = "Permite OS domiciliar sem clinica e adiciona origem_atendimento em ordens_servico"

TARGET_TABLE = "ordens_servico"


def _ensure_column(connection: Connection, table_name: str, column_name: str, sql: str) -> None:
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name not in columns:
        connection.execute(text(sql))


def _backfill_origem_atendimento(connection: Connection) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "agendamentos" in tables:
        connection.execute(
            text(
                """
                UPDATE ordens_servico
                SET origem_atendimento = COALESCE(
                    (
                        SELECT ag.origem_atendimento
                        FROM agendamentos ag
                        WHERE ag.id = ordens_servico.agendamento_id
                    ),
                    'clinica_parceira'
                )
                WHERE origem_atendimento IS NULL OR TRIM(origem_atendimento) = ''
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                UPDATE ordens_servico
                SET origem_atendimento = 'clinica_parceira'
                WHERE origem_atendimento IS NULL OR TRIM(origem_atendimento) = ''
                """
            )
        )


def _upgrade_postgres(connection: Connection) -> None:
    _ensure_column(
        connection,
        TARGET_TABLE,
        "origem_atendimento",
        "ALTER TABLE ordens_servico ADD COLUMN origem_atendimento VARCHAR(32) DEFAULT 'clinica_parceira'",
    )
    _backfill_origem_atendimento(connection)
    connection.execute(text("ALTER TABLE ordens_servico ALTER COLUMN clinica_id DROP NOT NULL"))


def _upgrade_sqlite(connection: Connection) -> None:
    inspector = inspect(connection)
    columns_meta = {column["name"]: column for column in inspector.get_columns(TARGET_TABLE)}
    clinica_nullable = bool(columns_meta.get("clinica_id", {}).get("nullable", True))
    if "origem_atendimento" in columns_meta and clinica_nullable:
        connection.execute(
            text(
                """
                UPDATE ordens_servico
                SET origem_atendimento = 'clinica_parceira'
                WHERE origem_atendimento IS NULL OR TRIM(origem_atendimento) = ''
                """
            )
        )
        return

    connection.execute(
        text(
            """
            CREATE TABLE ordens_servico__new (
                id INTEGER PRIMARY KEY,
                numero_os VARCHAR(50) NOT NULL UNIQUE,
                agendamento_id INTEGER NOT NULL,
                paciente_id INTEGER NOT NULL,
                clinica_id INTEGER,
                servico_id INTEGER NOT NULL,
                origem_atendimento VARCHAR(32) DEFAULT 'clinica_parceira',
                data_atendimento DATETIME,
                tipo_horario VARCHAR(20),
                valor_servico NUMERIC(10,2) DEFAULT 0,
                desconto NUMERIC(10,2) DEFAULT 0,
                valor_final NUMERIC(10,2) DEFAULT 0,
                status VARCHAR(50) DEFAULT 'Pendente',
                observacoes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME,
                criado_por_id INTEGER,
                criado_por_nome VARCHAR(100)
            )
            """
        )
    )

    tables = set(inspect(connection).get_table_names())
    if "agendamentos" in tables:
        connection.execute(
            text(
                """
                INSERT INTO ordens_servico__new (
                    id,
                    numero_os,
                    agendamento_id,
                    paciente_id,
                    clinica_id,
                    servico_id,
                    origem_atendimento,
                    data_atendimento,
                    tipo_horario,
                    valor_servico,
                    desconto,
                    valor_final,
                    status,
                    observacoes,
                    created_at,
                    updated_at,
                    criado_por_id,
                    criado_por_nome
                )
                SELECT
                    os.id,
                    os.numero_os,
                    os.agendamento_id,
                    os.paciente_id,
                    os.clinica_id,
                    os.servico_id,
                    COALESCE(ag.origem_atendimento, 'clinica_parceira'),
                    os.data_atendimento,
                    os.tipo_horario,
                    os.valor_servico,
                    os.desconto,
                    os.valor_final,
                    os.status,
                    os.observacoes,
                    os.created_at,
                    os.updated_at,
                    os.criado_por_id,
                    os.criado_por_nome
                FROM ordens_servico os
                LEFT JOIN agendamentos ag ON ag.id = os.agendamento_id
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                INSERT INTO ordens_servico__new (
                    id,
                    numero_os,
                    agendamento_id,
                    paciente_id,
                    clinica_id,
                    servico_id,
                    origem_atendimento,
                    data_atendimento,
                    tipo_horario,
                    valor_servico,
                    desconto,
                    valor_final,
                    status,
                    observacoes,
                    created_at,
                    updated_at,
                    criado_por_id,
                    criado_por_nome
                )
                SELECT
                    id,
                    numero_os,
                    agendamento_id,
                    paciente_id,
                    clinica_id,
                    servico_id,
                    'clinica_parceira',
                    data_atendimento,
                    tipo_horario,
                    valor_servico,
                    desconto,
                    valor_final,
                    status,
                    observacoes,
                    created_at,
                    updated_at,
                    criado_por_id,
                    criado_por_nome
                FROM ordens_servico
                """
            )
        )

    connection.execute(text("DROP TABLE ordens_servico"))
    connection.execute(text("ALTER TABLE ordens_servico__new RENAME TO ordens_servico"))
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ordens_servico_status_data_atendimento_id "
            "ON ordens_servico (status, data_atendimento, id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ordens_servico_clinica_status_data_id "
            "ON ordens_servico (clinica_id, status, data_atendimento, id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ordens_servico_servico_status_data_id "
            "ON ordens_servico (servico_id, status, data_atendimento, id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ordens_servico_criado_por_status_data_id "
            "ON ordens_servico (criado_por_id, status, data_atendimento, id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ordens_servico_agendamento_status_id "
            "ON ordens_servico (agendamento_id, status, id)"
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    if TARGET_TABLE not in inspector.get_table_names():
        return

    if dialect == "sqlite":
        _upgrade_sqlite(connection)
        return

    _upgrade_postgres(connection)
