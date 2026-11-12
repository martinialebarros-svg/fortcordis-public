from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func
from app.db.database import Base

class Agendamento(Base):
    __tablename__ = "agendamentos"
    __table_args__ = (
        Index("ix_agendamentos_data_inicio_id", "data", "inicio", "id"),
        Index("ix_agendamentos_data_status_inicio_id", "data", "status", "inicio", "id"),
        Index("ix_agendamentos_data_clinica_inicio_id", "data", "clinica_id", "inicio", "id"),
        Index("ix_agendamentos_data_servico_inicio_id", "data", "servico_id", "inicio", "id"),
        Index("ix_agendamentos_data_criado_por_inicio_id", "data", "criado_por_id", "inicio", "id"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, nullable=True)
    tutor_id = Column(Integer, nullable=True)
    clinica_id = Column(Integer, nullable=True)
    servico_id = Column(Integer, nullable=True)
    origem_atendimento = Column(String, default="clinica_parceira")
    
    # Data/hora
    inicio = Column(DateTime(timezone=True), nullable=False)
    fim = Column(DateTime(timezone=True), nullable=True)
    data = Column(String)
    hora = Column(String)
    
    # Status: Agendado, Reservado, Confirmado, Em atendimento, Realizado, Cancelado, Faltou, Expirado
    status = Column(String, default='Agendado')
    reserva_expira_em = Column(DateTime(timezone=True), nullable=True)
    observacoes = Column(Text)
    
    # Campos denormalizados (legado)
    paciente = Column(String)
    tutor = Column(String)
    telefone = Column(String)
    servico = Column(String)
    clinica = Column(String)
    
    # Relacionamentos (sem FK para evitar dependências)
    pacote_id = Column(Integer, nullable=True)
    
    # Auditoria - CORRIGIDO: default no Python também
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    criado_em = Column(DateTime(timezone=True))
    atualizado_em = Column(DateTime(timezone=True))
    
    criado_por_id = Column(Integer)
    criado_por_nome = Column(String)
    confirmado_por_id = Column(Integer)
    confirmado_por_nome = Column(String)
    confirmado_em = Column(DateTime(timezone=True))

    # Marcador manual de urgencia da fila de laudos pendentes - vive aqui
    # (nao em Exame) porque a maioria dos agendamentos nunca gera Exame/
    # AtendimentoClinico (fluxo do dropdown "Laudar" na Agenda, que cria
    # o Laudo direto via agendamento_id). Para agendamentos com mais de
    # um tipo de laudo esperado (ex.: "Eco + Eletro"), o marcador vale
    # para o agendamento inteiro, nao por tipo individual.
    urgente_laudo = Column(Boolean, nullable=False, default=False)

    # Controle do worker de lembrete automatico de consulta via WhatsApp
    # (ver app/services/whatsapp_reminder_scheduler_service.py).
    whatsapp_reminder_sent_at = Column(DateTime(timezone=True), nullable=True)
    whatsapp_reminder_attempts = Column(Integer, nullable=False, default=0)
    whatsapp_reminder_last_error = Column(Text, nullable=True)

    # Excecao de deslocamento concedida por admin (ver
    # _validar_deslocamento_agendamento em app/api/v1/endpoints/agenda.py).
    # Antes disso a concessao era transiente (`confirmar_conflito_deslocamento`
    # valia so para a requisicao em curso), entao reabilitar ou reativar o
    # agendamento depois tornava a bater na mesma validacao. A coluna de escopo
    # guarda a assinatura da rota aprovada (horario, destino e servico): se
    # algum desses campos mudar, a excecao deixa de valer e a validacao volta
    # a rodar normalmente.
    excecao_deslocamento_concedida_em = Column(DateTime(timezone=True), nullable=True)
    excecao_deslocamento_concedida_por_id = Column(Integer, nullable=True)
    excecao_deslocamento_concedida_por_nome = Column(String, nullable=True)
    excecao_deslocamento_motivo = Column(Text, nullable=True)
    excecao_deslocamento_escopo = Column(String(64), nullable=True)
    # Escopo do horario fechado autorizado pelo admin; dados do pet nao o alteram.
    excecao_agenda_fechada_escopo = Column(String(100), nullable=True)

    # JSON de consentimento específico; NULL mantém a exclusão comum no banco.
    excecao_sobreposicao = Column(Text, nullable=True)
