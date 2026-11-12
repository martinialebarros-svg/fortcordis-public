"""Persiste o escopo da autorizacao administrativa para agenda fechada."""

from sqlalchemy import inspect, text

VERSION = "20260925_92"
DESCRIPTION = "Escopo da excecao de agenda fechada no agendamento"


def upgrade(connection, dialect):
    if "agendamentos" not in inspect(connection).get_table_names():
        return
    colunas = {item["name"] for item in inspect(connection).get_columns("agendamentos")}
    if "excecao_agenda_fechada_escopo" not in colunas:
        connection.execute(text(
            "ALTER TABLE agendamentos ADD COLUMN excecao_agenda_fechada_escopo VARCHAR(100)"
        ))
