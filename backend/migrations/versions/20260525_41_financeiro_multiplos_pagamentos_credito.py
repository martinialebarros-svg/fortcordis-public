"""Add finance structures for multi-payment OS flow, fees and client/clinic credit."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260525_41"
DESCRIPTION = "Cadastro de meios de pagamento, taxas, rateio por OS e creditos financeiros"


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _ensure_column(connection: Connection, table_name: str, column_name: str, definition_sql: str) -> None:
    if not _table_exists(connection, table_name):
        return
    if column_name in _column_names(connection, table_name):
        return
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}"))


def _create_bandeiras_cartao(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "bandeiras_cartao"):
        return
    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE bandeiras_cartao (
                    id BIGSERIAL PRIMARY KEY,
                    nome VARCHAR(120) NOT NULL,
                    codigo VARCHAR(80) UNIQUE,
                    ativo BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NULL,
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(120) NULL
                )
                """
            )
        )
        return
    connection.execute(
        text(
            """
            CREATE TABLE bandeiras_cartao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome VARCHAR(120) NOT NULL,
                codigo VARCHAR(80) UNIQUE,
                ativo BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NULL,
                criado_por_id INTEGER NULL,
                criado_por_nome VARCHAR(120) NULL
            )
            """
        )
    )


def _create_formas_pagamento_config(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "formas_pagamento_config"):
        return
    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE formas_pagamento_config (
                    id BIGSERIAL PRIMARY KEY,
                    nome VARCHAR(140) NOT NULL,
                    codigo VARCHAR(80) NOT NULL,
                    tipo VARCHAR(40) NOT NULL,
                    adquirente VARCHAR(120) NULL,
                    bandeira_id INTEGER NULL,
                    taxa_percentual DOUBLE PRECISION NOT NULL DEFAULT 0,
                    taxa_fixa DOUBLE PRECISION NOT NULL DEFAULT 0,
                    ativo BOOLEAN NOT NULL DEFAULT TRUE,
                    ordem_exibicao INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NULL,
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(120) NULL,
                    CONSTRAINT uq_formas_pagamento_codigo UNIQUE (codigo)
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_formas_pagamento_config_ativo_ordem "
                "ON formas_pagamento_config (ativo, ordem_exibicao, id)"
            )
        )
        return
    connection.execute(
        text(
            """
            CREATE TABLE formas_pagamento_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome VARCHAR(140) NOT NULL,
                codigo VARCHAR(80) NOT NULL UNIQUE,
                tipo VARCHAR(40) NOT NULL,
                adquirente VARCHAR(120) NULL,
                bandeira_id INTEGER NULL,
                taxa_percentual DOUBLE NOT NULL DEFAULT 0,
                taxa_fixa DOUBLE NOT NULL DEFAULT 0,
                ativo BOOLEAN NOT NULL DEFAULT 1,
                ordem_exibicao INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NULL,
                criado_por_id INTEGER NULL,
                criado_por_nome VARCHAR(120) NULL
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_formas_pagamento_config_ativo_ordem "
            "ON formas_pagamento_config (ativo, ordem_exibicao, id)"
        )
    )


def _create_ordens_servico_pagamentos(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "ordens_servico_pagamentos"):
        return
    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE ordens_servico_pagamentos (
                    id BIGSERIAL PRIMARY KEY,
                    ordem_servico_id INTEGER NOT NULL,
                    transacao_id INTEGER NULL,
                    forma_pagamento_config_id INTEGER NULL,
                    forma_pagamento_codigo VARCHAR(80) NOT NULL,
                    forma_pagamento_nome VARCHAR(140) NOT NULL,
                    adquirente VARCHAR(120) NULL,
                    bandeira_nome VARCHAR(120) NULL,
                    valor_bruto DOUBLE PRECISION NOT NULL,
                    taxa_percentual_aplicada DOUBLE PRECISION NOT NULL DEFAULT 0,
                    taxa_fixa_aplicada DOUBLE PRECISION NOT NULL DEFAULT 0,
                    valor_taxa DOUBLE PRECISION NOT NULL DEFAULT 0,
                    valor_liquido DOUBLE PRECISION NOT NULL,
                    data_recebimento TIMESTAMP NOT NULL,
                    observacoes TEXT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NULL,
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(120) NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_os_pagamentos_os_data "
                "ON ordens_servico_pagamentos (ordem_servico_id, data_recebimento)"
            )
        )
        return
    connection.execute(
        text(
            """
            CREATE TABLE ordens_servico_pagamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ordem_servico_id INTEGER NOT NULL,
                transacao_id INTEGER NULL,
                forma_pagamento_config_id INTEGER NULL,
                forma_pagamento_codigo VARCHAR(80) NOT NULL,
                forma_pagamento_nome VARCHAR(140) NOT NULL,
                adquirente VARCHAR(120) NULL,
                bandeira_nome VARCHAR(120) NULL,
                valor_bruto DOUBLE NOT NULL,
                taxa_percentual_aplicada DOUBLE NOT NULL DEFAULT 0,
                taxa_fixa_aplicada DOUBLE NOT NULL DEFAULT 0,
                valor_taxa DOUBLE NOT NULL DEFAULT 0,
                valor_liquido DOUBLE NOT NULL,
                data_recebimento TIMESTAMP NOT NULL,
                observacoes TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NULL,
                criado_por_id INTEGER NULL,
                criado_por_nome VARCHAR(120) NULL
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_os_pagamentos_os_data "
            "ON ordens_servico_pagamentos (ordem_servico_id, data_recebimento)"
        )
    )


def _create_creditos_financeiros(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "creditos_financeiros"):
        return
    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE creditos_financeiros (
                    id BIGSERIAL PRIMARY KEY,
                    tipo_destino VARCHAR(20) NOT NULL,
                    clinica_id INTEGER NULL,
                    paciente_id INTEGER NULL,
                    tutor_id INTEGER NULL,
                    valor DOUBLE PRECISION NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'Ativo',
                    origem VARCHAR(40) NOT NULL DEFAULT 'manual',
                    descricao TEXT NULL,
                    ordem_servico_id INTEGER NULL,
                    transacao_id INTEGER NULL,
                    data_movimento TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NULL,
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(120) NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_creditos_financeiros_destino_data "
                "ON creditos_financeiros (tipo_destino, data_movimento)"
            )
        )
        return
    connection.execute(
        text(
            """
            CREATE TABLE creditos_financeiros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_destino VARCHAR(20) NOT NULL,
                clinica_id INTEGER NULL,
                paciente_id INTEGER NULL,
                tutor_id INTEGER NULL,
                valor DOUBLE NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'Ativo',
                origem VARCHAR(40) NOT NULL DEFAULT 'manual',
                descricao TEXT NULL,
                ordem_servico_id INTEGER NULL,
                transacao_id INTEGER NULL,
                data_movimento TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NULL,
                criado_por_id INTEGER NULL,
                criado_por_nome VARCHAR(120) NULL
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_creditos_financeiros_destino_data "
            "ON creditos_financeiros (tipo_destino, data_movimento)"
        )
    )


def _seed_bandeiras_e_formas(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "bandeiras_cartao") or not _table_exists(connection, "formas_pagamento_config"):
        return

    bandeiras = [
        ("visa", "Visa"),
        ("mastercard", "Mastercard"),
        ("elo", "Elo"),
        ("hipercard", "Hipercard"),
    ]
    for codigo, nome in bandeiras:
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    INSERT INTO bandeiras_cartao (codigo, nome, ativo)
                    VALUES (:codigo, :nome, TRUE)
                    ON CONFLICT (codigo) DO NOTHING
                    """
                ),
                {"codigo": codigo, "nome": nome},
            )
        else:
            connection.execute(
                text(
                    """
                    INSERT OR IGNORE INTO bandeiras_cartao (codigo, nome, ativo)
                    VALUES (:codigo, :nome, 1)
                    """
                ),
                {"codigo": codigo, "nome": nome},
            )

    formas = [
        ("dinheiro", "Dinheiro", "dinheiro", None, 0.0, 0.0, 10),
        ("pix", "PIX", "pix", None, 0.0, 0.0, 20),
        ("transferencia", "Transferencia", "transferencia", None, 0.0, 0.0, 30),
        ("cartao_credito_mercado_pago", "Cartao credito - Mercado Pago", "cartao_credito", "Mercado Pago", 4.99, 0.0, 40),
        ("cartao_debito_mercado_pago", "Cartao debito - Mercado Pago", "cartao_debito", "Mercado Pago", 1.99, 0.0, 50),
        ("cartao_credito_ton", "Cartao credito - TON", "cartao_credito", "TON", 4.49, 0.0, 60),
        ("cartao_debito_ton", "Cartao debito - TON", "cartao_debito", "TON", 1.49, 0.0, 70),
        ("boleto", "Boleto", "boleto", None, 0.0, 0.0, 80),
    ]
    for codigo, nome, tipo, adquirente, taxa_percentual, taxa_fixa, ordem in formas:
        params = {
            "codigo": codigo,
            "nome": nome,
            "tipo": tipo,
            "adquirente": adquirente,
            "taxa_percentual": taxa_percentual,
            "taxa_fixa": taxa_fixa,
            "ordem": ordem,
        }
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    INSERT INTO formas_pagamento_config (
                        codigo, nome, tipo, adquirente, taxa_percentual, taxa_fixa, ativo, ordem_exibicao
                    )
                    VALUES (
                        :codigo, :nome, :tipo, :adquirente, :taxa_percentual, :taxa_fixa, TRUE, :ordem
                    )
                    ON CONFLICT (codigo) DO NOTHING
                    """
                ),
                params,
            )
        else:
            connection.execute(
                text(
                    """
                    INSERT OR IGNORE INTO formas_pagamento_config (
                        codigo, nome, tipo, adquirente, taxa_percentual, taxa_fixa, ativo, ordem_exibicao
                    )
                    VALUES (
                        :codigo, :nome, :tipo, :adquirente, :taxa_percentual, :taxa_fixa, 1, :ordem
                    )
                    """
                ),
                params,
            )


def upgrade(connection: Connection, dialect: str) -> None:
    _ensure_column(connection, "transacoes", "forma_pagamento_config_id", "INTEGER")
    _ensure_column(connection, "transacoes", "adquirente_pagamento", "VARCHAR(120)")
    _ensure_column(connection, "transacoes", "bandeira_pagamento", "VARCHAR(120)")
    _ensure_column(connection, "transacoes", "taxa_percentual", "DOUBLE PRECISION NOT NULL DEFAULT 0")
    _ensure_column(connection, "transacoes", "taxa_fixa", "DOUBLE PRECISION NOT NULL DEFAULT 0")
    _ensure_column(connection, "transacoes", "valor_taxa", "DOUBLE PRECISION NOT NULL DEFAULT 0")

    _create_bandeiras_cartao(connection, dialect)
    _create_formas_pagamento_config(connection, dialect)
    _create_ordens_servico_pagamentos(connection, dialect)
    _create_creditos_financeiros(connection, dialect)
    _seed_bandeiras_e_formas(connection, dialect)

