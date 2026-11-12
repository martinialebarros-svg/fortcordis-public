from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.sql import func

from app.db.database import Base


class AtendimentoClinico(Base):
    __tablename__ = "atendimentos_clinicos"
    __table_args__ = (
        Index("ix_atendimentos_clinicos_data_atendimento_id", "data_atendimento", "id"),
        Index("ix_atendimentos_clinicos_clinica_data_id", "clinica_id", "data_atendimento", "id"),
        Index("ix_atendimentos_clinicos_status_data_id", "status", "data_atendimento", "id"),
        Index("ix_atendimentos_clinicos_agendamento_data_id", "agendamento_id", "data_atendimento", "id"),
        Index(
            "ux_atendimentos_clinicos_agendamento_unico",
            "agendamento_id",
            unique=True,
            postgresql_where=text("agendamento_id IS NOT NULL"),
            sqlite_where=text("agendamento_id IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, nullable=False, index=True)
    tutor_id = Column(Integer, nullable=True, index=True)
    clinica_id = Column(Integer, nullable=True, index=True)
    agendamento_id = Column(Integer, nullable=True, index=True)
    veterinario_id = Column(Integer, nullable=False, index=True)
    especie = Column(String)  # Canina, Felina, etc. - preenchido automaticamente a partir do paciente

    data_atendimento = Column(DateTime(timezone=True), nullable=False, default=func.now(), index=True)
    status = Column(String, nullable=False, default="Triagem", index=True)

    # === TRIAGEM ===
    peso = Column(Float)  # kg
    temperatura = Column(Float)  # Celsius
    frequencia_cardiaca = Column(Integer)  # bpm
    frequencia_respiratoria = Column(Integer)  # mpm
    pressao_arterial = Column(String)  # mmHg
    saturacao_oxigenio = Column(Integer)  # %
    escore_condicion_corpo = Column(Integer)  # 1-9
    mucosas = Column(String)  # rosadas, palidas, ictericas, cianoticas
    hidratacao = Column(String)  # normal, desidratado, desidratado++
    triagem_observacoes = Column(Text)

    # === CONSULTA ===
    queixa_principal = Column(Text)
    anamnese = Column(Text)
    exame_fisico = Column(Text)
    dados_clinicos = Column(Text)

    # === DIAGNOSTICO E TRATAMENTO ===
    diagnostico_principal = Column(Text)
    diagnostico_secundario = Column(Text)
    diagnostico_diferencial = Column(Text)
    plano_terapeutico = Column(Text)
    prognostico = Column(String)  # Favoravel, Reservado, Ruim

    # === RETORNO E OBSERVACOES ===
    retorno_recomendado = Column(String)
    motivo_retorno = Column(Text)
    observacoes = Column(Text)

    # === FLUXO DE TRABALHO ===
    triagem_concluida = Column(Integer, default=0)
    consulta_concluida = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_por_id = Column(Integer)
    criado_por_nome = Column(String)


class AnexoAtendimento(Base):
    __tablename__ = "anexos_atendimentos"

    id = Column(Integer, primary_key=True, index=True)
    atendimento_id = Column(Integer, nullable=False, index=True)
    exame_id = Column(Integer, nullable=True, index=True)
    # Adendo que trouxe o anexo (nulo quando anexado durante o atendimento).
    evolucao_id = Column(Integer, nullable=True, index=True)
    tipo = Column(String, nullable=False)  # imagem, documento, radiografia, ultrassom, outro
    descricao = Column(String)
    url = Column(String, nullable=False)
    nome_original = Column(String)
    tamanho = Column(Integer)  # bytes
    mime_type = Column(String)
    arquivo_hash = Column(String(64))
    dedupe_key = Column(String(96))
    caminho_arquivo = Column(String)
    origem = Column(String, nullable=False, default="externo")

    created_at = Column(DateTime(timezone=True), default=func.now())


class DocumentoAtendimentoTemplate(Base):
    __tablename__ = "documentos_atendimento_templates"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False, index=True)
    tipo = Column(String(80), nullable=False, default="documento", index=True)
    titulo_padrao = Column(String(255), nullable=False)
    corpo_template = Column(Text, nullable=False)
    ativo = Column(Integer, nullable=False, default=1, index=True)
    ordem = Column(Integer, nullable=False, default=0)
    criado_por_id = Column(Integer)
    criado_por_nome = Column(String)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class DocumentoAtendimento(Base):
    __tablename__ = "documentos_atendimento"

    id = Column(Integer, primary_key=True, index=True)
    atendimento_id = Column(Integer, nullable=False, index=True)
    template_id = Column(Integer, nullable=True, index=True)
    titulo = Column(String(255), nullable=False)
    corpo = Column(Text, nullable=False)
    status = Column(String(40), nullable=False, default="rascunho", index=True)
    criado_por_id = Column(Integer)
    criado_por_nome = Column(String)
    emitido_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class UploadDedupeMetrica(Base):
    __tablename__ = "upload_dedupe_metricas"

    id = Column(Integer, primary_key=True, index=True)
    atendimento_id = Column(Integer, nullable=False, index=True)
    clinica_id = Column(Integer, nullable=True, index=True)
    evento = Column(String(40), nullable=False, index=True)
    dedupe_key = Column(String(120))
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), index=True)


class UploadDedupeCleanupRun(Base):
    __tablename__ = "upload_dedupe_cleanup_runs"

    id = Column(Integer, primary_key=True, index=True)
    executor = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, index=True)
    retention_days = Column(Integer, nullable=False)
    cutoff_date = Column(String(10), nullable=False)
    deleted_rows = Column(Integer, nullable=False, default=0)
    error_message = Column(Text)
    duration_ms = Column(Integer)
    started_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), index=True)


class EvolucaoClinica(Base):
    """Evolucao intra-atendimento ou adendo posterior a conclusao.

    A mesma tabela cobre os dois casos: `pos_conclusao` marca o registro
    criado depois que o atendimento foi concluido, e `tipo` diz o que o
    adendo carrega (resultado de exame recebido depois, receita
    complementar, orientacao). O episodio continua sendo o mesmo
    atendimento - nao se cria encontro novo para registrar o que chega
    depois da alta.
    """

    __tablename__ = "evolucoes_clinicas"

    id = Column(Integer, primary_key=True, index=True)
    atendimento_id = Column(Integer, nullable=False, index=True)
    data_evolucao = Column(DateTime(timezone=True), nullable=False, default=func.now())
    tipo = Column(String(40), nullable=False, default="evolucao", server_default=text("'evolucao'"))
    titulo = Column(String(255))
    # Derivado no backend a partir do status do atendimento na criacao,
    # nunca aceito do cliente.
    pos_conclusao = Column(Integer, nullable=False, default=0, server_default=text("0"))
    descricao = Column(Text, nullable=False)
    sinais_vitais = Column(Text)  # JSON com FC, FR, Temp, etc
    responsavel_id = Column(Integer)
    responsavel_nome = Column(String)

    created_at = Column(DateTime(timezone=True), default=func.now())


class AlertaClinico(Base):
    __tablename__ = "alertas_clinicos"

    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, nullable=False, index=True)
    tipo = Column(String, nullable=False)  # alergia, contraindicacao, doenca_cronica, risco, outro
    titulo = Column(String, nullable=False)
    descricao = Column(Text)
    gravidade = Column(String)  # baixa, media, alta, critica
    ativo = Column(Integer, default=1, index=True)
    data_inicio = Column(DateTime(timezone=True), default=func.now())
    data_fim = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Medicamento(Base):
    __tablename__ = "medicamentos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False, index=True)
    principio_ativo = Column(String)
    concentracao = Column(String)
    forma_farmaceutica = Column(String)
    categoria = Column(String, index=True)
    classe_terapeutica = Column(String, index=True)
    especie_alvo = Column(String)
    dose_min_mg_kg = Column(Float)
    dose_max_mg_kg = Column(Float)
    dose_intervalo_horas = Column(Integer)
    dose_unidade = Column(String)
    via_padrao = Column(String)
    duracao_padrao = Column(String)
    concentracao_mg_ml = Column(Float)
    concentracao_mg_comprimido = Column(Float)
    indicacoes = Column(Text)
    contraindicacoes = Column(Text)
    interacoes_json = Column(Text)
    observacao_seguranca = Column(Text)
    parametrizacao_origem = Column(String)
    observacoes = Column(Text)
    ativo = Column(Integer, nullable=False, default=1, index=True)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PrescricaoClinica(Base):
    """Receita de um atendimento.

    Um atendimento pode ter mais de uma receita: `sequencia` 1 e a receita
    emitida no dia da consulta, e as seguintes sao complementares, emitidas
    em adendos posteriores a conclusao. Isso evita que uma receita
    complementar sobrescreva a que ja foi entregue ao tutor.
    """

    __tablename__ = "prescricoes_clinicas"
    __table_args__ = (
        Index(
            "ux_prescricoes_clinicas_atendimento_sequencia",
            "atendimento_id",
            "sequencia",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    atendimento_id = Column(Integer, nullable=False, index=True)
    sequencia = Column(Integer, nullable=False, default=1, server_default=text("1"))
    # Momento da primeira geracao do PDF. Preenchido uma unica vez: e o que
    # marca a receita como documento oficial ja entregue.
    emitida_em = Column(DateTime(timezone=True), nullable=True)
    # Adendo que originou a receita complementar (nulo na receita do dia).
    adendo_id = Column(Integer, nullable=True, index=True)
    orientacoes_gerais = Column(Text)
    retorno_dias = Column(Integer)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PrescricaoItem(Base):
    __tablename__ = "prescricoes_itens"

    id = Column(Integer, primary_key=True, index=True)
    prescricao_id = Column(Integer, nullable=False, index=True)
    medicamento_id = Column(Integer, nullable=True, index=True)
    medicamento_nome = Column(String, nullable=False, index=True)
    apresentacao_selecionada = Column(String)
    dose = Column(String)
    frequencia = Column(String)
    duracao = Column(String)
    via = Column(String)
    instrucoes = Column(Text)
    ordem = Column(Integer, nullable=False, default=0)
    dose_mg_kg = Column(String)
    peso_referencia_kg = Column(String)
    unidade_dose_calculo = Column(String)
    concentracao_personalizada = Column(String)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PrescricaoItemAjuste(Base):
    __tablename__ = "prescricao_item_ajustes"

    id = Column(Integer, primary_key=True, index=True)
    prescricao_item_id = Column(Integer, nullable=False, index=True)
    atendimento_id = Column(Integer, nullable=False, index=True)
    campo = Column(String, nullable=False, index=True)
    valor_anterior = Column(Text)
    valor_novo = Column(Text)
    motivo = Column(Text)
    responsavel_id = Column(Integer)
    responsavel_nome = Column(String)

    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)


class ExameAjuste(Base):
    __tablename__ = "exame_ajustes"

    id = Column(Integer, primary_key=True, index=True)
    exame_id = Column(Integer, nullable=False, index=True)
    atendimento_id = Column(Integer, nullable=False, index=True)
    campo = Column(String, nullable=False, index=True)
    valor_anterior = Column(Text)
    valor_novo = Column(Text)
    motivo = Column(Text)
    responsavel_id = Column(Integer)
    responsavel_nome = Column(String)

    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)
