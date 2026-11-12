"""Corrige um limite de DIVEd de 25 kg transcrito abaixo do intervalo de Cornell.

Esser et al. (2020, doi:10.1111/jvim.15914) explicitam que o intervalo de
predicao de Cornell et al. (2004) para 25 kg vai de 3,3 a 4,8 cm. A atualizacao
e condicional para preservar linhas personalizadas ou provenientes de outra base.
"""

from sqlalchemy import inspect, text


VERSION = "20260928_93"
DESCRIPTION = "Corrige limite superior DIVEd canino 25 kg da tabela Cornell"


def upgrade(connection, dialect):
    if "referencias_eco" not in inspect(connection).get_table_names():
        return
    connection.execute(text("""
        UPDATE referencias_eco
        SET lvid_d_max = 48.0
        WHERE lower(especie) LIKE 'canin%'
          AND peso_kg = 25.0
          AND lvid_d_min = 33.0
          AND lvid_d_max = 42.0
    """))
