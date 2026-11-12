"""Torna whatsapp_bot_conversa_estado.modo anulavel: NULL = sem override.

A tabela guarda duas coisas diferentes na mesma linha: o override de modo por
conversa (decisao de gente) e a escrituracao de pausa/handoff (efeito colateral
do worker). Com `modo` NOT NULL DEFAULT 'suggest', criar a linha para anotar uma
pausa criava tambem um override que ninguem pediu.

Isso furava o portao do piloto. `resolve_modo_efetivo` sai antes de avaliar
clinica e participacao quando a conversa ja tem modo valido - de proposito, e o
opt-in por conversa. Como pause_conversation e set_handoff_motivo gravavam
'suggest' sozinhos, bastava uma emergencia, um pedido de humano ou uma pausa
para a conversa ficar isenta do piloto para sempre.

NULL passa a significar "sem override": a linha existe para a pausa e o
handoff, e a participacao volta a ser avaliada.

BACKFILL - decisao registrada. As linhas ja gravadas com 'suggest' viram NULL,
porque nao existe discriminador confiavel entre o 'suggest' escolhido e o
incidental: `atualizado_por_id` nao separa os dois (o worker pausa sem usuario,
mas a central pausa COM usuario e tambem criava a linha). O custo de apagar um
override deliberado e baixo justamente porque o valor apagado coincide com o
default institucional - a conversa segue em 'suggest' por heranca. O que muda e
que ela volta a respeitar o piloto, que e o comportamento correto. Erra para o
lado de atender menos, igual ao resto dos portoes.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260825_78"
DESCRIPTION = "Torna whatsapp_bot_conversa_estado.modo anulavel e zera os 'suggest' incidentais"

TARGET_TABLE = "whatsapp_bot_conversa_estado"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _modo_is_nullable(connection: Connection) -> bool:
    for column in inspect(connection).get_columns(TARGET_TABLE):
        if column["name"] == "modo":
            return bool(column.get("nullable", True))
    return True


def _upgrade_postgresql(connection: Connection) -> None:
    connection.execute(
        text(f"ALTER TABLE {TARGET_TABLE} ALTER COLUMN modo DROP NOT NULL")
    )
    # Sem o DROP DEFAULT o furo fica meio vivo: qualquer INSERT que apenas
    # OMITA a coluna volta a receber 'suggest' do servidor.
    connection.execute(text(f"ALTER TABLE {TARGET_TABLE} ALTER COLUMN modo DROP DEFAULT"))
    connection.execute(
        text(f"UPDATE {TARGET_TABLE} SET modo = NULL WHERE modo = 'suggest'")
    )


def _upgrade_sqlite(connection: Connection) -> None:
    # SQLite nao muda nulidade por ALTER: e rebuild. A coluna nasceu com
    # NOT NULL explicito em 20260820_75, entao nao da para pular este ramo.
    # O INSERT..SELECT ja faz a conversao 'suggest' -> NULL junto com a copia.
    connection.execute(
        text(
            f"""
            CREATE TABLE {TARGET_TABLE}__new (
                wa_identity TEXT PRIMARY KEY,
                modo TEXT,
                pausado_ate DATETIME,
                handoff_motivo TEXT,
                atualizado_por_id INTEGER,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
            INSERT INTO {TARGET_TABLE}__new (
                wa_identity, modo, pausado_ate, handoff_motivo, atualizado_por_id, updated_at
            )
            SELECT
                wa_identity,
                CASE WHEN modo = 'suggest' THEN NULL ELSE modo END,
                pausado_ate,
                handoff_motivo,
                atualizado_por_id,
                updated_at
            FROM {TARGET_TABLE}
            """
        )
    )
    connection.execute(text(f"DROP TABLE {TARGET_TABLE}"))
    connection.execute(text(f"ALTER TABLE {TARGET_TABLE}__new RENAME TO {TARGET_TABLE}"))


def upgrade(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, TARGET_TABLE):
        return
    # Banco novo nasce do model (create_all roda antes das migracoes), ja
    # anulavel e sem linha nenhuma - nao ha o que converter nem que zerar.
    # A guarda tambem evita que um segundo run apague override deliberado
    # gravado DEPOIS da conversao.
    if _modo_is_nullable(connection):
        return
    if dialect == "postgresql":
        _upgrade_postgresql(connection)
    else:
        _upgrade_sqlite(connection)
