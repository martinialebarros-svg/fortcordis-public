"""Adds clinical attendance module tables and aligns exam schema."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260225_11"
DESCRIPTION = "Cria modulo de atendimento clinico com receituario e banco de medicamentos"


DEFAULT_MEDICAMENTOS = [
    ("Amoxicilina", "Amoxicilina", "250 mg", "Comprimido", "Antibiotico"),
    ("Clavulin", "Amoxicilina + Clavulanato", "500 mg", "Comprimido", "Antibiotico"),
    ("Prednisolona", "Prednisolona", "20 mg", "Comprimido", "Corticoide"),
    ("Meloxicam", "Meloxicam", "0.2 mg/ml", "Suspensao oral", "Anti-inflamatorio"),
    ("Dipirona", "Dipirona", "500 mg/ml", "Gotas", "Analgesico"),
    ("Omeprazol", "Omeprazol", "20 mg", "Capsula", "Gastroprotetor"),
    ("Furosemida", "Furosemida", "40 mg", "Comprimido", "Diuretico"),
    ("Pimobendan", "Pimobendan", "5 mg", "Comprimido", "Cardiologico"),
    ("Enalapril", "Enalapril", "10 mg", "Comprimido", "Cardiologico"),
    ("Amlodipina", "Amlodipina", "5 mg", "Comprimido", "Cardiologico"),
]


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _create_table_atendimentos(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "atendimentos_clinicos"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE atendimentos_clinicos (
                    id SERIAL PRIMARY KEY,
                    paciente_id INTEGER NOT NULL,
                    tutor_id INTEGER NULL,
                    clinica_id INTEGER NULL,
                    agendamento_id INTEGER NULL,
                    veterinario_id INTEGER NOT NULL,
                    data_atendimento TIMESTAMP NOT NULL DEFAULT NOW(),
                    status VARCHAR(50) NOT NULL DEFAULT 'Em atendimento',
                    queixa_principal TEXT,
                    anamnese TEXT,
                    exame_fisico TEXT,
                    dados_clinicos TEXT,
                    diagnostico TEXT,
                    plano_terapeutico TEXT,
                    retorno_recomendado VARCHAR(255),
                    observacoes TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NULL,
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(255) NULL
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE atendimentos_clinicos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paciente_id INTEGER NOT NULL,
                    tutor_id INTEGER NULL,
                    clinica_id INTEGER NULL,
                    agendamento_id INTEGER NULL,
                    veterinario_id INTEGER NOT NULL,
                    data_atendimento DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'Em atendimento',
                    queixa_principal TEXT,
                    anamnese TEXT,
                    exame_fisico TEXT,
                    dados_clinicos TEXT,
                    diagnostico TEXT,
                    plano_terapeutico TEXT,
                    retorno_recomendado TEXT,
                    observacoes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NULL,
                    criado_por_id INTEGER NULL,
                    criado_por_nome TEXT NULL
                )
                """
            )
        )

    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_atendimentos_clinicos_paciente_id ON atendimentos_clinicos (paciente_id)")
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_atendimentos_clinicos_clinica_id ON atendimentos_clinicos (clinica_id)")
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_atendimentos_clinicos_data_atendimento ON atendimentos_clinicos (data_atendimento)")
    )


def _create_table_medicamentos(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "medicamentos"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE medicamentos (
                    id SERIAL PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL,
                    principio_ativo VARCHAR(255),
                    concentracao VARCHAR(255),
                    forma_farmaceutica VARCHAR(255),
                    categoria VARCHAR(120),
                    observacoes TEXT,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NULL
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                CREATE TABLE medicamentos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    principio_ativo TEXT,
                    concentracao TEXT,
                    forma_farmaceutica TEXT,
                    categoria TEXT,
                    observacoes TEXT,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NULL
                )
                """
            )
        )

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_medicamentos_nome ON medicamentos (nome)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_medicamentos_categoria ON medicamentos (categoria)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_medicamentos_ativo ON medicamentos (ativo)"))


def _create_table_prescricoes(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "prescricoes_clinicas"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE prescricoes_clinicas (
                        id SERIAL PRIMARY KEY,
                        atendimento_id INTEGER NOT NULL,
                        orientacoes_gerais TEXT,
                        retorno_dias INTEGER NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NULL
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE prescricoes_clinicas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        atendimento_id INTEGER NOT NULL,
                        orientacoes_gerais TEXT,
                        retorno_dias INTEGER NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NULL
                    )
                    """
                )
            )

        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_prescricoes_clinicas_atendimento_id ON prescricoes_clinicas (atendimento_id)")
        )

    if not _table_exists(connection, "prescricoes_itens"):
        if dialect == "postgresql":
            connection.execute(
                text(
                    """
                    CREATE TABLE prescricoes_itens (
                        id SERIAL PRIMARY KEY,
                        prescricao_id INTEGER NOT NULL,
                        medicamento_id INTEGER NULL,
                        medicamento_nome VARCHAR(255) NOT NULL,
                        dose VARCHAR(255),
                        frequencia VARCHAR(255),
                        duracao VARCHAR(255),
                        via VARCHAR(120),
                        instrucoes TEXT,
                        ordem INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NULL
                    )
                    """
                )
            )
        else:
            connection.execute(
                text(
                    """
                    CREATE TABLE prescricoes_itens (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prescricao_id INTEGER NOT NULL,
                        medicamento_id INTEGER NULL,
                        medicamento_nome TEXT NOT NULL,
                        dose TEXT,
                        frequencia TEXT,
                        duracao TEXT,
                        via TEXT,
                        instrucoes TEXT,
                        ordem INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NULL
                    )
                    """
                )
            )

        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_prescricoes_itens_prescricao_id ON prescricoes_itens (prescricao_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_prescricoes_itens_medicamento_id ON prescricoes_itens (medicamento_id)")
        )


def _align_exames_table(connection: Connection, dialect: str) -> None:
    if not _table_exists(connection, "exames"):
        return

    columns = _column_names(connection, "exames")
    if "atendimento_id" not in columns:
        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE exames ADD COLUMN atendimento_id INTEGER NULL"))
        else:
            connection.execute(text("ALTER TABLE exames ADD COLUMN atendimento_id INTEGER"))

    if "prioridade" not in columns:
        if dialect == "postgresql":
            connection.execute(text("ALTER TABLE exames ADD COLUMN prioridade VARCHAR(50) DEFAULT 'Rotina'"))
        else:
            connection.execute(text("ALTER TABLE exames ADD COLUMN prioridade TEXT DEFAULT 'Rotina'"))

    connection.execute(text("UPDATE exames SET prioridade = 'Rotina' WHERE prioridade IS NULL OR prioridade = ''"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_exames_atendimento_id ON exames (atendimento_id)"))


def _seed_medicamentos(connection: Connection) -> None:
    if not _table_exists(connection, "medicamentos"):
        return

    existing_count = connection.execute(text("SELECT COUNT(*) FROM medicamentos")).scalar()
    if int(existing_count or 0) > 0:
        return

    for nome, principio_ativo, concentracao, forma_farmaceutica, categoria in DEFAULT_MEDICAMENTOS:
        connection.execute(
            text(
                """
                INSERT INTO medicamentos
                    (nome, principio_ativo, concentracao, forma_farmaceutica, categoria, ativo)
                VALUES
                    (:nome, :principio_ativo, :concentracao, :forma_farmaceutica, :categoria, 1)
                """
            ),
            {
                "nome": nome,
                "principio_ativo": principio_ativo,
                "concentracao": concentracao,
                "forma_farmaceutica": forma_farmaceutica,
                "categoria": categoria,
            },
        )


def upgrade(connection: Connection, dialect: str) -> None:
    _create_table_atendimentos(connection, dialect)
    _create_table_medicamentos(connection, dialect)
    _create_table_prescricoes(connection, dialect)
    _align_exames_table(connection, dialect)
    _seed_medicamentos(connection)
