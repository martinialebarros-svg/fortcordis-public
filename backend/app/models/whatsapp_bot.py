from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class WhatsAppBotJob(Base):
    """Job de resposta automatica gerado a partir de uma mensagem inbound.

    Enfileirado pelo endpoint de mensagem recebida (Fase 2); consumido pelo
    worker do bot. `wa_message_id` e unico para dedupe de reentrega do
    webhook.
    """

    __tablename__ = "whatsapp_bot_jobs"

    id = Column(Integer, primary_key=True, index=True)
    wa_identity = Column(String(30), nullable=False, index=True)
    conversation_id = Column(String(64), nullable=False, index=True)
    wa_message_id = Column(String(160), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=False, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WhatsAppBotResposta(Base):
    """Registro de auditoria de cada job processado pelo bot.

    Grava a decisao tomada (`sent`/`draft`/`suppressed`/`handoff`/`blocked`) e
    o contexto usado para chegar nela, independente do que foi de fato
    enviado ao cliente.
    """

    __tablename__ = "whatsapp_bot_respostas"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, nullable=False, index=True)
    wa_identity = Column(String(30), nullable=False, index=True)
    conversation_id = Column(String(64), nullable=False)
    decisao = Column(String(20), nullable=False)
    motivo = Column(Text, nullable=True)
    texto_gerado = Column(Text, nullable=True)
    texto_enviado = Column(Text, nullable=True)
    modelo = Column(String(100), nullable=True)
    prompt_version = Column(String(50), nullable=True)
    tools_usadas = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latencia_ms = Column(Integer, nullable=True)
    resolution = Column(String(20), nullable=True)
    match_type = Column(String(20), nullable=True)
    contexto_chave = Column(String(64), nullable=True)
    # Sem FK: registro historico nao pode sumir nem travar exclusao de clinica.
    clinica_id = Column(Integer, nullable=True, index=True)
    feedback = Column(String(20), nullable=True)
    enviado_por_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WhatsAppBotConversaEstado(Base):
    """Estado do bot por conversa, chaveado pela identidade canonica do telefone.

    Sem linha para uma `wa_identity` **ou com `modo` nulo**, a conversa herda
    `configuracoes.whatsapp_bot_modo` (ver `Configuracao`) e continua sujeita
    ao portao de participacao. A linha existe tambem so para anotar pausa e
    handoff, e nesses casos `modo` fica nulo de proposito.
    """

    __tablename__ = "whatsapp_bot_conversa_estado"

    wa_identity = Column(String(30), primary_key=True)
    # Anulavel de proposito: NULL e "sem override por conversa". A linha
    # tambem existe so para anotar pausa/handoff, e nesse caso gravar um modo
    # criaria um opt-in que ninguem pediu - furando o portao do piloto.
    modo = Column(String(20), nullable=True)
    pausado_ate = Column(DateTime(timezone=True), nullable=True)
    handoff_motivo = Column(String(50), nullable=True)
    atualizado_por_id = Column(Integer, nullable=True)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WhatsAppBotContextoSelecao(Base):
    """Escolha auditavel por conversa, sem alterar telefones ou estado do bot.

    Sem FK polimorfica: exclusao/inativacao precisa invalidar a escolha, nunca
    apagar a linha e liberar silenciosamente outro cadastro para o telefone.
    Limpar a escolha preserva a linha e sua versao para detectar telas antigas.
    """

    __tablename__ = "whatsapp_bot_contexto_selecao"
    __table_args__ = (
        CheckConstraint(
            "(match_type IS NULL AND cadastro_id IS NULL) OR "
            "(match_type IS NOT NULL AND match_type IN ('clinica', 'tutor') AND cadastro_id IS NOT NULL AND cadastro_id > 0)",
            name="ck_whatsapp_contexto_selecao_cadastro",
        ),
        CheckConstraint("versao >= 1", name="ck_whatsapp_contexto_selecao_versao"),
    )

    wa_identity = Column(String(30), primary_key=True)
    match_type = Column(String(20), nullable=True)
    cadastro_id = Column(Integer, nullable=True)
    versao = Column(Integer, nullable=False, default=1)
    atualizado_por_id = Column(Integer, nullable=True)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WhatsAppBotClinicaEstado(Base):
    """RF-P01: participacao do bot por clinica parceira.

    Terceiro nivel de controle, entre o global e o por conversa. Estado
    operacional - com responsavel e historico -, por isso tabela propria em vez
    de coluna em `Clinica`.

    Sem linha para uma clinica, a resolucao depende de
    `configuracoes.whatsapp_bot_participacao`: em `todos` herda o padrao
    institucional; em `piloto` fica `off`.
    """

    __tablename__ = "whatsapp_bot_clinica_estado"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(
        Integer, ForeignKey("clinicas.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    modo = Column(String(20), nullable=False, default="off")
    observacao = Column(Text, nullable=True)
    habilitado_por_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WhatsAppBotSolicitacao(Base):
    """Fila administrativa duravel, independente da validade do contexto do bot."""

    __tablename__ = 'whatsapp_bot_solicitacoes'
    id = Column(Integer, primary_key=True)
    resposta_id = Column(Integer, nullable=False, unique=True)
    agendamento_id = Column(Integer, nullable=True, unique=True)
    wa_identity = Column(String(30), nullable=False, index=True)
    conversation_id = Column(String(64), nullable=False)
    clinica_id = Column(Integer, nullable=False, index=True)
    resumo = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default='aguardando_equipe', index=True)
    responsavel_id = Column(Integer, nullable=True)
    responsavel_nome = Column(String(160), nullable=True)
    prazo_em = Column(DateTime(timezone=True), nullable=False, index=True)
    assumida_em = Column(DateTime(timezone=True), nullable=True)
    concluida_em = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    versao = Column(Integer, nullable=False, default=1)
    historico = Column(Text, nullable=False, default='[]')
