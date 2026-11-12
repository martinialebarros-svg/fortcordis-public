"""Participacao do bot por clinica parceira (Fase 1 - so schema).

Terceiro nivel de controle do bot, entre o global e o por conversa. Nada aqui e
lido em runtime ainda: a resolucao de modo e o portao vem na Fase 2. Ver
docs/specs/whatsapp-bot-piloto-por-clinica/spec.md.

Default deliberadamente inerte: `whatsapp_bot_participacao` nasce `todos` e a
tabela nasce vazia, entao aplicar esta migracao nao muda o comportamento de
nenhuma instalacao existente (NFR-P01).
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260824_76"
DESCRIPTION = (
    "Cria whatsapp_bot_clinica_estado e a coluna "
    "whatsapp_bot_participacao em configuracoes"
)


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _index_names(connection: Connection, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(connection).get_indexes(table_name)}


def _create_whatsapp_bot_clinica_estado(connection: Connection, dialect: str) -> None:
    """RF-P01: estado operacional por clinica, com responsavel e historico.

    Tabela propria em vez de coluna em `clinicas` porque isto e estado do bot,
    nao cadastro: tem quem habilitou, quando, e por que. `clinicas` ja carrega
    25 colunas de cadastro.

    FK com ON DELETE CASCADE (CB-P04): participacao de clinica que nao existe
    mais nao tem sentido.
    """
    if _table_exists(connection, "whatsapp_bot_clinica_estado"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE whatsapp_bot_clinica_estado (
                    id SERIAL PRIMARY KEY,
                    clinica_id INTEGER NOT NULL UNIQUE
                        REFERENCES clinicas(id) ON DELETE CASCADE,
                    modo VARCHAR(20) NOT NULL DEFAULT 'off',
                    observacao TEXT,
                    habilitado_por_id INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE whatsapp_bot_clinica_estado (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clinica_id INTEGER NOT NULL UNIQUE
                        REFERENCES clinicas(id) ON DELETE CASCADE,
                    modo VARCHAR(20) NOT NULL DEFAULT 'off',
                    observacao TEXT,
                    habilitado_por_id INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    if "ix_whatsapp_bot_clinica_estado_clinica_id" not in _index_names(
        connection, "whatsapp_bot_clinica_estado"
    ):
        connection.execute(
            text(
                "CREATE INDEX ix_whatsapp_bot_clinica_estado_clinica_id "
                "ON whatsapp_bot_clinica_estado (clinica_id)"
            )
        )


def _add_configuracoes_columns(connection: Connection, dialect: str) -> None:
    """RF-P02: postura de participacao, default `todos`.

    `todos` preserva o comportamento atual. E em `piloto` que a ausencia de
    habilitacao explicita passa a significar `off` em vez de herdar o padrao
    institucional - a inversao que faz o piloto ser piloto.
    """
    if not _table_exists(connection, "configuracoes"):
        return

    columns = _column_names(connection, "configuracoes")

    if "whatsapp_bot_participacao" not in columns:
        if dialect == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE configuracoes "
                    "ADD COLUMN whatsapp_bot_participacao VARCHAR(20) DEFAULT 'todos'"
                )
            )
        else:
            connection.execute(
                text("ALTER TABLE configuracoes ADD COLUMN whatsapp_bot_participacao TEXT")
            )

    # Linhas que ja existiam nascem explicitamente em `todos`: default de
    # coluna nao preenche linha antiga em todo dialeto.
    connection.execute(
        text(
            "UPDATE configuracoes SET whatsapp_bot_participacao = 'todos' "
            "WHERE whatsapp_bot_participacao IS NULL"
        )
    )


def upgrade(connection: Connection, dialect: str) -> None:
    _create_whatsapp_bot_clinica_estado(connection, dialect)
    _add_configuracoes_columns(connection, dialect)
