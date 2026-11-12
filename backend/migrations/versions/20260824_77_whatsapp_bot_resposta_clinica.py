"""Atribui cada resposta do bot a clinica de origem (Fase 4 do piloto).

Sem isto o retorno do piloto nao e atribuivel: o numero agregado esconde qual
clinica aceita e qual descarta, e tres clinicas boas mascaram uma ruim.

Grava na ORIGEM em vez de resolver na leitura. Resolver depois exigiria
reexecutar a identificacao de telefone para cada linha - caro - e, pior,
poderia devolver resultado diferente do que era verdade quando a resposta foi
gerada, se o cadastro mudou no meio. Metrica que muda o passado nao serve para
decidir.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260824_77"
DESCRIPTION = "Adiciona whatsapp_bot_respostas.clinica_id para atribuir a metrica por clinica"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _index_names(connection: Connection, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(connection).get_indexes(table_name)}


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "whatsapp_bot_respostas"):
        return

    if "clinica_id" not in _column_names(connection, "whatsapp_bot_respostas"):
        # Sem FK de proposito: a resposta e registro historico e nao pode
        # sumir nem impedir a exclusao de uma clinica. O id fica como
        # referencia solta, que e o comportamento correto para auditoria.
        connection.execute(
            text("ALTER TABLE whatsapp_bot_respostas ADD COLUMN clinica_id INTEGER")
        )

    if "ix_whatsapp_bot_respostas_clinica_id" not in _index_names(
        connection, "whatsapp_bot_respostas"
    ):
        connection.execute(
            text(
                "CREATE INDEX ix_whatsapp_bot_respostas_clinica_id "
                "ON whatsapp_bot_respostas (clinica_id)"
            )
        )
