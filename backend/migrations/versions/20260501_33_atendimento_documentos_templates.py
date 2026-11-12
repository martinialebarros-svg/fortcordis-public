"""Adds editable clinical documents to attendance module."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260501_33"
DESCRIPTION = "Adiciona documentos clinicos editaveis ao atendimento"


DEFAULT_TEMPLATES = [
    {
        "nome": "Parecer medico veterinario",
        "tipo": "parecer",
        "titulo_padrao": "Parecer Medico Veterinario",
        "ordem": 10,
        "corpo_template": (
            "Eu, Dr(a). {{veterinario_nome}}, CRMV {{crmv}}, declaro que realizei avaliacao "
            "dos exames cardiologicos e exame fisico no animal denominado {{paciente_nome}}, "
            "especie {{especie}}, {{sexo}}, raca {{raca}}, com {{idade}}, de propriedade do(a) "
            "tutor(a) {{tutor_nome}}.\n\n"
            "Apos a analise, constatei que os resultados estao dentro da normalidade para idade "
            "e condicao fisica do paciente. Nao ha, portanto, qualquer impedimento para a "
            "realizacao de procedimento cirurgico no referido animal.\n\n"
            "Atenciosamente,"
        ),
    },
    {
        "nome": "Atestado de saude",
        "tipo": "atestado",
        "titulo_padrao": "Atestado de Saude Animal",
        "ordem": 20,
        "corpo_template": (
            "Atesto, para os devidos fins, que o paciente {{paciente_nome}}, especie {{especie}}, "
            "raca {{raca}}, {{sexo}}, com {{idade}}, pertencente ao(a) tutor(a) {{tutor_nome}}, "
            "foi avaliado em {{data_atendimento}}.\n\n"
            "No momento da avaliacao, encontra-se clinicamente estavel, conforme exame fisico "
            "e informacoes registradas no atendimento.\n\n"
            "Este atestado e emitido a pedido do(a) tutor(a), para fins de comprovacao."
        ),
    },
    {
        "nome": "Declaracao de comparecimento",
        "tipo": "declaracao",
        "titulo_padrao": "Declaracao de Comparecimento",
        "ordem": 30,
        "corpo_template": (
            "Declaramos que o paciente {{paciente_nome}}, acompanhado por {{tutor_nome}}, "
            "compareceu para atendimento veterinario em {{data_atendimento_hora}}, na clinica "
            "{{clinica_nome}}.\n\n"
            "Documento emitido para fins de comprovacao de comparecimento."
        ),
    },
    {
        "nome": "Encaminhamento veterinario",
        "tipo": "encaminhamento",
        "titulo_padrao": "Encaminhamento Veterinario",
        "ordem": 40,
        "corpo_template": (
            "Encaminho o paciente {{paciente_nome}}, especie {{especie}}, raca {{raca}}, "
            "{{sexo}}, com {{idade}}, pertencente ao(a) tutor(a) {{tutor_nome}}, para avaliacao "
            "especializada.\n\n"
            "Resumo clinico: {{queixa_principal}}\n\n"
            "Diagnostico/hipotese: {{diagnostico_principal}}\n\n"
            "Conduta atual: {{plano_terapeutico}}"
        ),
    },
    {
        "nome": "Autorizacao de procedimento",
        "tipo": "autorizacao",
        "titulo_padrao": "Autorizacao de Procedimento Veterinario",
        "ordem": 50,
        "corpo_template": (
            "Eu, {{tutor_nome}}, tutor(a)/responsavel pelo animal {{paciente_nome}}, especie "
            "{{especie}}, declaro estar ciente das orientacoes recebidas e autorizo a equipe "
            "veterinaria a realizar o procedimento indicado.\n\n"
            "Procedimento autorizado: [descrever procedimento]\n\n"
            "Fui orientado(a) sobre beneficios, riscos, alternativas, necessidade de exames "
            "complementares e cuidados pos-procedimento."
        ),
    },
    {
        "nome": "Orientacoes pos-atendimento",
        "tipo": "orientacoes",
        "titulo_padrao": "Orientacoes Pos-atendimento",
        "ordem": 60,
        "corpo_template": (
            "Paciente: {{paciente_nome}}\n"
            "Tutor(a): {{tutor_nome}}\n"
            "Data: {{data_atendimento}}\n\n"
            "Orientacoes gerais:\n"
            "- Manter repouso relativo conforme tolerancia.\n"
            "- Observar apetite, disposicao, respiracao e ocorrencia de sinais de dor.\n"
            "- Seguir a prescricao e as recomendacoes registradas no atendimento.\n\n"
            "Retorno recomendado: {{retorno_recomendado}}\n"
            "Motivo do retorno: {{motivo_retorno}}"
        ),
    },
]


def _table_exists(connection: Connection, table_name: str) -> bool:
    return table_name in inspect(connection).get_table_names()


def _create_templates_table(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "documentos_atendimento_templates"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE documentos_atendimento_templates (
                    id SERIAL PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL,
                    tipo VARCHAR(80) NOT NULL DEFAULT 'documento',
                    titulo_padrao VARCHAR(255) NOT NULL,
                    corpo_template TEXT NOT NULL,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    ordem INTEGER NOT NULL DEFAULT 0,
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(255) NULL,
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
                CREATE TABLE documentos_atendimento_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome VARCHAR(255) NOT NULL,
                    tipo VARCHAR(80) NOT NULL DEFAULT 'documento',
                    titulo_padrao VARCHAR(255) NOT NULL,
                    corpo_template TEXT NOT NULL,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    ordem INTEGER NOT NULL DEFAULT 0,
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(255) NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NULL
                )
                """
            )
        )


def _create_documents_table(connection: Connection, dialect: str) -> None:
    if _table_exists(connection, "documentos_atendimento"):
        return

    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE documentos_atendimento (
                    id SERIAL PRIMARY KEY,
                    atendimento_id INTEGER NOT NULL,
                    template_id INTEGER NULL,
                    titulo VARCHAR(255) NOT NULL,
                    corpo TEXT NOT NULL,
                    status VARCHAR(40) NOT NULL DEFAULT 'rascunho',
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(255) NULL,
                    emitido_at TIMESTAMP NULL,
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
                CREATE TABLE documentos_atendimento (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    atendimento_id INTEGER NOT NULL,
                    template_id INTEGER NULL,
                    titulo VARCHAR(255) NOT NULL,
                    corpo TEXT NOT NULL,
                    status VARCHAR(40) NOT NULL DEFAULT 'rascunho',
                    criado_por_id INTEGER NULL,
                    criado_por_nome VARCHAR(255) NULL,
                    emitido_at DATETIME NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NULL
                )
                """
            )
        )


def _seed_templates(connection: Connection) -> None:
    for template in DEFAULT_TEMPLATES:
        exists = connection.execute(
            text("SELECT id FROM documentos_atendimento_templates WHERE nome = :nome LIMIT 1"),
            {"nome": template["nome"]},
        ).fetchone()
        if exists:
            continue
        connection.execute(
            text(
                """
                INSERT INTO documentos_atendimento_templates
                    (nome, tipo, titulo_padrao, corpo_template, ativo, ordem, criado_por_nome)
                VALUES
                    (:nome, :tipo, :titulo_padrao, :corpo_template, 1, :ordem, 'sistema')
                """
            ),
            template,
        )


def upgrade(connection: Connection, dialect: str) -> None:
    _create_templates_table(connection, dialect)
    _create_documents_table(connection, dialect)

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documentos_atendimento_templates_nome "
            "ON documentos_atendimento_templates (nome)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documentos_atendimento_templates_tipo "
            "ON documentos_atendimento_templates (tipo)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documentos_atendimento_templates_ativo "
            "ON documentos_atendimento_templates (ativo)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documentos_atendimento_atendimento_id "
            "ON documentos_atendimento (atendimento_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documentos_atendimento_template_id "
            "ON documentos_atendimento (template_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documentos_atendimento_status "
            "ON documentos_atendimento (status)"
        )
    )

    _seed_templates(connection)
