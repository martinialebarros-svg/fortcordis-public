"""Fuso operacional de prescricoes_clinicas.emitida_em.

A migracao 20260910_83 criou `emitida_em` como TIMESTAMP puro, enquanto o
modelo declara `DateTime(timezone=True)`. Em Postgres, gravar um datetime aware
numa coluna naive converte para UTC e descarta o fuso: a API passava a entregar
numeros de UTC sem offset, e o frontend, que le string sem fuso como horario
operacional, mostrava 3h a frente.

Converte a coluna para TIMESTAMPTZ reinterpretando o valor gravado como UTC,
que e o que ele de fato e. O `USING` corrige os registros existentes na mesma
operacao.

SQLite nao entra aqui de proposito. O dialeto guarda os numeros do relogio
local e descarta o offset, entao la o valor ja esta em horario operacional e
`_to_operational_iso` o le corretamente. Converter seria introduzir o desvio
que o SQLite nao tem.
"""
from sqlalchemy import inspect, text

VERSION = '20260911_84'
DESCRIPTION = 'emitida_em em timestamptz (Postgres), interpretando o valor atual como UTC'

TABELA = 'prescricoes_clinicas'
COLUNA = 'emitida_em'


def _tipo_atual(connection):
    return connection.execute(
        text(
            'SELECT data_type FROM information_schema.columns '
            'WHERE table_name = :tabela AND column_name = :coluna'
        ),
        {'tabela': TABELA, 'coluna': COLUNA},
    ).scalar()


def upgrade(connection, dialect):
    if dialect != 'postgresql':
        return

    if TABELA not in set(inspect(connection).get_table_names()):
        return
    if COLUNA not in {c['name'] for c in inspect(connection).get_columns(TABELA)}:
        return

    # Idempotencia: na segunda execucao o tipo ja e o novo e nao ha o que fazer.
    # Reexecutar o ALTER seria inofensivo para o tipo, mas o `AT TIME ZONE` de
    # um timestamptz produz timestamp naive - aplicado duas vezes, deslocaria
    # os valores.
    if _tipo_atual(connection) == 'timestamp with time zone':
        return

    connection.execute(
        text(
            f'ALTER TABLE {TABELA} ALTER COLUMN {COLUNA} TYPE TIMESTAMPTZ '
            f'USING {COLUNA} AT TIME ZONE \'UTC\''
        )
    )
