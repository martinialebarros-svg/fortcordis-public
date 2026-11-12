"""Continuidade pos-alta: receita multipla por atendimento e adendo com anexo.

Aditiva e idempotente. Os defaults ja produzem o estado correto para todo
registro historico (`sequencia = 1`, `emitida_em` nulo, `pos_conclusao = 0`),
entao nao ha backfill.
"""
from sqlalchemy import inspect, text

VERSION = '20260910_83'
DESCRIPTION = 'Receita multipla por atendimento e adendo clinico pos-conclusao'


def _colunas(connection, table):
    return {c['name'] for c in inspect(connection).get_columns(table)}


def _add_column(connection, table, column, ddl_type):
    if column not in _colunas(connection, table):
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl_type}'))


def upgrade(connection, dialect):
    tabelas = set(inspect(connection).get_table_names())

    if 'prescricoes_clinicas' in tabelas:
        # NOT NULL com DEFAULT preenche as linhas existentes com 1 tanto no
        # SQLite quanto no Postgres, que e o que o indice unico abaixo exige.
        _add_column(connection, 'prescricoes_clinicas', 'sequencia', 'INTEGER NOT NULL DEFAULT 1')
        _add_column(connection, 'prescricoes_clinicas', 'emitida_em', 'TIMESTAMP')
        _add_column(connection, 'prescricoes_clinicas', 'adendo_id', 'INTEGER')
        connection.execute(
            text(
                'CREATE INDEX IF NOT EXISTS ix_prescricoes_clinicas_adendo_id '
                'ON prescricoes_clinicas (adendo_id)'
            )
        )
        # Bases antigas podem ter mais de uma linha para o mesmo atendimento
        # (ver comentario em historico_paciente). Renumera as excedentes antes
        # de criar o indice unico, para nao falhar a migracao nesses casos.
        duplicados = connection.execute(
            text(
                'SELECT atendimento_id FROM prescricoes_clinicas '
                'GROUP BY atendimento_id HAVING COUNT(*) > 1'
            )
        ).fetchall()
        for (atendimento_id,) in duplicados:
            linhas = connection.execute(
                text(
                    'SELECT id FROM prescricoes_clinicas WHERE atendimento_id = :aid '
                    'ORDER BY id ASC'
                ),
                {'aid': atendimento_id},
            ).fetchall()
            for posicao, (prescricao_id,) in enumerate(linhas, start=1):
                connection.execute(
                    text('UPDATE prescricoes_clinicas SET sequencia = :seq WHERE id = :pid'),
                    {'seq': posicao, 'pid': prescricao_id},
                )
        connection.execute(
            text(
                'CREATE UNIQUE INDEX IF NOT EXISTS ux_prescricoes_clinicas_atendimento_sequencia '
                'ON prescricoes_clinicas (atendimento_id, sequencia)'
            )
        )

    if 'evolucoes_clinicas' in tabelas:
        _add_column(
            connection,
            'evolucoes_clinicas',
            'tipo',
            "VARCHAR(40) NOT NULL DEFAULT 'evolucao'",
        )
        _add_column(connection, 'evolucoes_clinicas', 'titulo', 'VARCHAR(255)')
        _add_column(
            connection,
            'evolucoes_clinicas',
            'pos_conclusao',
            'INTEGER NOT NULL DEFAULT 0',
        )

    if 'anexos_atendimentos' in tabelas:
        _add_column(connection, 'anexos_atendimentos', 'evolucao_id', 'INTEGER')
        connection.execute(
            text(
                'CREATE INDEX IF NOT EXISTS ix_anexos_atendimentos_evolucao_id '
                'ON anexos_atendimentos (evolucao_id)'
            )
        )
